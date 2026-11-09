"""Command-line entry point for SubPeeko."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

from . import __version__
from .config import ConfigError, configure, load_config, show_config
from .model import BATCH_SIZE, ModelClient, ModelError, local_simple
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
    result.add_argument("--all-model", action="store_true", help="also send simple exchanges to the model for comparison")
    result.add_argument("--batch-size", type=_batch_size, default=BATCH_SIZE, help=f"dialogues per model request (default: {BATCH_SIZE})")
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


def _convert(args: argparse.Namespace) -> int:
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
        try:
            if output.exists() and not args.overwrite:
                raise SubtitleError(f"Output already exists: {output} (use --overwrite to replace it)")
            subtitles = AssFile.read(path)
            if not subtitles.dialogues:
                raise SubtitleError("No supported bilingual dialogue found")
            if not args.all_model and all(local_simple(item, args.level) for item in subtitles.dialogues):
                notes = {item.id: "" for item in subtitles.dialogues}
            else:
                if client is None:
                    client = ModelClient(load_config(), batch_size=args.batch_size)
                print(f"Processing: {path} ({len(subtitles.dialogues)} bilingual dialogue(s))", flush=True)
                notes = client.analyze(
                    subtitles.dialogues, args.level, all_model=args.all_model,
                    progress=lambda done, total: print(f"  Reviewed {done}/{total} dialogue(s).", flush=True),
                    on_retry=lambda message: print(f"  {message}", file=sys.stderr, flush=True),
                )
            result = subtitles.render(notes)
            _write_output(output, result, args.overwrite)
            succeeded += 1
            print(f"Created: {output} ({len(subtitles.dialogues)} bilingual dialogue(s))")
            if any(len(note) > 90 for note in notes.values()):
                print("  Some annotations may be too long for the available display time.")
        except (ConfigError, ModelError, SubtitleError) as exc:
            failed += 1
            print(f"Failed: {path}: {exc}", file=sys.stderr)
    print(f"Finished: {succeeded} created, {failed} failed; {client.requests if client else 0} model request(s).")
    if client:
        print(f"Local simple exchanges: {client.local_count}; exact-context reuse: {client.cached_count}.")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        if argv and argv[0] == "config":
            return _config_command(argv[1:])
        return _convert(parser().parse_args(argv))
    except (ConfigError, ModelError, SubtitleError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("Interrupted.", file=sys.stderr)
        return 130
