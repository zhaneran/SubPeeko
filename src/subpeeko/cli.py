"""Command-line entry point for SubPeeko."""

from __future__ import annotations

import argparse
import math
import os
import sys
import tempfile
import time
from pathlib import Path

from . import __version__
from .checkpoint import Checkpoint, CheckpointError, checkpoint_key
from .config import ConfigError, configure, load_config, show_config
from .model import BATCH_SIZE, DEFAULT_CONCURRENCY, DEFAULT_RPM, DEFAULT_TPM, ModelClient, ModelError
from .subtitles import AssFile, SubtitleError
from .vocabulary import LEVELS

OUTPUT_SUFFIX = ".subpeeko.ass"


def _batch_size(value: str) -> int:
    try:
        number = int(value)
        if 1 <= number <= 100:
            return number
    except ValueError:
        pass
    raise argparse.ArgumentTypeError("batch size must be an integer between 1 and 100")


def _positive_int(value: str) -> int:
    try:
        number = int(value)
        if number > 0:
            return number
    except ValueError:
        pass
    raise argparse.ArgumentTypeError("must be a positive integer")


def _positive_float(value: str) -> float:
    try:
        number = float(value)
        if math.isfinite(number) and number > 0:
            return number
    except ValueError:
        pass
    raise argparse.ArgumentTypeError("must be a positive finite number")


def _nonnegative_int(value: str) -> int:
    try:
        number = int(value)
        if number >= 0:
            return number
    except ValueError:
        pass
    raise argparse.ArgumentTypeError("must be a nonnegative integer")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="subpeeko",
        description="Create English-learning subtitles from bilingual ASS files.",
        epilog="Run 'subpeeko config' to configure the model API."
    )
    result.add_argument("input", type=Path, help="an ASS file or a directory of ASS files")
    result.add_argument("--level", choices=LEVELS, required=True, help="the learner's English level")
    result.add_argument("--recursive", action="store_true", help="include subdirectories")
    result.add_argument("--overwrite", action="store_true", help="replace existing generated output")
    result.add_argument("--dry-run", action="store_true", help="list input and output paths without calling the model")
    result.add_argument("--batch-size", type=_batch_size, default=BATCH_SIZE, help=f"dialogues per model request (default: {BATCH_SIZE})")
    result.add_argument("--concurrency", type=_positive_int, default=DEFAULT_CONCURRENCY, help=f"parallel model requests (default: {DEFAULT_CONCURRENCY})")
    result.add_argument("--rpm", type=_positive_int, default=DEFAULT_RPM, help=f"available requests per minute for this process (default: {DEFAULT_RPM})")
    result.add_argument("--tpm", type=_positive_int, default=DEFAULT_TPM, help=f"available input and output tokens per minute (default: {DEFAULT_TPM})")
    result.add_argument("--qps", type=_positive_float, help="maximum requests per second; defaults to RPM / 60")
    result.add_argument("--max-output-tokens", type=_positive_int, default=2048, help="output token reservation when rate limiting (default: 2048)")
    result.add_argument("--thinking", choices=("off", "on", "auto"), default="off", help="model thinking mode (default: off; auto omits the provider-specific setting)")
    result.add_argument("--reasoning-reserve", type=_nonnegative_int, default=8192, help="additional reasoning-token reservation for providers without a combined cap (default: 8192)")
    result.add_argument("--no-resume", action="store_true", help="do not read or write local checkpoints")
    result.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return result


def _config_command(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="subpeeko config", description="Manage model API configuration.")
    p.add_argument("action", nargs="?", choices=("set", "show", "test"), default="set")
    args = p.parse_args(argv)
    if args.action == "set":
        configure()
    elif args.action == "show":
        show_config()
    else:
        client = ModelClient(load_config())
        client.test_connection()
        print("Model API connection succeeded.")
    return 0


def input_files(path: Path, recursive: bool) -> list[Path]:
    if path.is_file():
        if path.suffix.casefold() != ".ass":
            raise SubtitleError("Input file must have an .ass extension")
        if path.name.casefold().endswith(OUTPUT_SUFFIX):
            raise SubtitleError("Generated SubPeeko subtitles cannot be used as input")
        return [path]
    if not path.is_dir():
        raise SubtitleError(f"Input path does not exist: {path}")
    items = path.rglob("*") if recursive else path.iterdir()
    try:
        return sorted(
            (item for item in items if item.is_file() and item.suffix.casefold() == ".ass"
             and not item.name.casefold().endswith(OUTPUT_SUFFIX)),
            key=lambda item: str(item).casefold(),
        )
    except OSError as exc:
        raise SubtitleError(f"Cannot read directory: {path}") from exc


def output_path(path: Path, level: str) -> Path:
    return path.with_name(f"{path.stem}.{level}{OUTPUT_SUFFIX}")


def _write_output(path: Path, data: bytes, overwrite: bool) -> None:
    if not overwrite:
        try:
            with path.open("xb") as destination:
                try:
                    destination.write(data)
                except OSError:
                    destination.close()
                    path.unlink(missing_ok=True)
                    raise
        except FileExistsError as exc:
            raise SubtitleError(f"Output already exists: {path} (use --overwrite to replace it)") from exc
        except OSError as exc:
            raise SubtitleError(f"Cannot write output: {path}") from exc
        return
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".subpeeko-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        os.replace(temporary, path)
    except OSError as exc:
        raise SubtitleError(f"Cannot write output: {path}") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _report_request(event: dict) -> None:
    usage = event["usage"] or {}
    def count(name):
        value = usage.get(name)
        return str(value) if type(value) is int and value >= 0 else "?"
    print(
        f"  Request {event['id']}: targets={event['targets']}, status={event['status']}, "
        f"network={event['request_seconds']:.2f}s, wait={event['wait_seconds']:.2f}s, "
        f"tokens in/out/reasoning={count('prompt_tokens')}/{count('completion_tokens')}/{count('reasoning_tokens')}",
        flush=True,
    )


def _convert(args: argparse.Namespace) -> int:
    clients = []
    started = time.monotonic()
    try:
        return _convert_files(args, clients)
    finally:
        if clients:
            client = clients[0]
            def total(key):
                count = client.usage_counts[key]
                if not count:
                    return "?"
                value = str(client.usage[key])
                return value if count == client.usage_responses else f"{value} (partial {count}/{client.usage_responses})"
            print(f"Elapsed: {time.monotonic() - started:.2f}s. Usage: input={total('prompt_tokens')}, output={total('completion_tokens')}, "
                  f"reasoning={total('reasoning_tokens')}; usage reported for {client.usage_responses}/{client.requests} requests; "
                  f"{client.retries} retry/split event(s).")


def _convert_files(args: argparse.Namespace, clients: list[ModelClient]) -> int:
    paths = input_files(args.input, args.recursive)
    if not paths:
        print("No input ASS files found.")
        return 0
    if args.dry_run:
        for path in paths:
            print(f"{path} -> {output_path(path, args.level)}")
        print(f"{len(paths)} file(s); no changes made and no model requests sent.")
        return 0

    client = None
    succeeded = failed = 0
    for path in paths:
        output = output_path(path, args.level)
        checkpoint = None
        try:
            if output.exists() and not args.overwrite:
                raise SubtitleError(f"Output already exists: {output} (use --overwrite to replace it)")
            subtitles = AssFile.read(path)
            if not subtitles.dialogues:
                raise SubtitleError("No supported bilingual dialogue found")
            if client is None:
                client = ModelClient(
                    load_config(), batch_size=args.batch_size, workers=args.concurrency,
                    rpm=args.rpm, tpm=args.tpm, qps=args.qps, max_output_tokens=args.max_output_tokens,
                    thinking=args.thinking, reasoning_reserve=args.reasoning_reserve, on_request=_report_request,
                )
                clients.append(client)
            cached = {}
            if not args.no_resume:
                key = checkpoint_key(path, subtitles.source_hash, client.config, args.level,
                                     batch_size=args.batch_size, thinking=client.thinking,
                                     max_output_tokens=args.max_output_tokens)
                checkpoint = Checkpoint(key)
                cached = checkpoint.load({item.id for item in subtitles.dialogues})
                if cached:
                    print(f"Resuming: {len(cached)}/{len(subtitles.dialogues)} dialogue(s) from local checkpoint.")
            print(f"Processing: {path} ({len(subtitles.dialogues)} bilingual dialogue(s))", flush=True)
            notes = client.analyze(
                subtitles.dialogues, args.level,
                progress=lambda done, total: print(f"  Reviewed {done}/{total} dialogue(s).", flush=True),
                on_retry=lambda message: print(f"  {message}", file=sys.stderr, flush=True),
                initial_results=cached, on_batch=checkpoint.save if checkpoint else None,
            )
            result = subtitles.render(notes)
            _write_output(output, result, args.overwrite)
            succeeded += 1
            print(f"Created: {output} ({len(subtitles.dialogues)} bilingual dialogue(s))")
            if any(len(note) > 90 for note in notes.values()):
                print("  Some annotations may be too long for the available display time.")
        except (CheckpointError, ConfigError, ModelError, SubtitleError) as exc:
            failed += 1
            print(f"Failed: {path}: {exc}", file=sys.stderr)
        finally:
            if checkpoint is not None:
                checkpoint.close()
    print(f"Finished: {succeeded} created, {failed} failed; {client.requests if client else 0} model request(s).")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    # Redirected Windows output may use an encoding that cannot represent paths.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        if argv and argv[0] == "config":
            return _config_command(argv[1:])
        p = parser()
        args = p.parse_args(argv)
        if args.concurrency > 32:
            p.error("--concurrency must not exceed 32")
        return _convert(args)
    except (CheckpointError, ConfigError, ModelError, SubtitleError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("Interrupted.", file=sys.stderr)
        return 130
