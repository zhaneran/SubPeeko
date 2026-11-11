"""Refresh the bundled vocabulary in the isolated package build tree."""

from __future__ import annotations

import json
import re
import warnings
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

REPOSITORY = "https://github.com/KyleBing/english-vocabulary"
API = "https://api.github.com/repos/KyleBing/english-vocabulary/commits/master"
RAW = "https://raw.githubusercontent.com/KyleBing/english-vocabulary"
SOURCES = (
    ("1 初中-乱序.txt", 0),
    ("2 高中-乱序.txt", 0),
    ("3 四级-乱序.txt", 1),
    ("4 六级-乱序.txt", 2),
    ("5 考研-乱序.txt", 3),
)
WORD = re.compile(r"[a-z]+(?:[ '\-][a-z]+)*")


def _read(url: str, limit: int = 2_000_000) -> bytes:
    request = Request(url, headers={"User-Agent": "SubPeeko-vocabulary-build"})
    with urlopen(request, timeout=10) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("upstream response exceeded the size limit")
    return data


def refresh(data_dir: Path) -> None:
    """Check the upstream revision, falling back to the packaged snapshot."""
    source_path = data_dir / "vocabulary-source.json"
    if not all((data_dir / name).is_file() for name in ("vocabulary.json", "vocabulary-source.json", "LICENSE-KyleBing.txt")):
        raise RuntimeError("Bundled vocabulary snapshot is incomplete")
    try:
        current = json.loads(source_path.read_text(encoding="utf-8"))
        if (not isinstance(current, dict) or current.get("repository") != REPOSITORY
                or not isinstance(current.get("revision"), str)
                or not re.fullmatch(r"[0-9a-f]{40}", current["revision"])):
            raise ValueError("invalid bundled vocabulary source")
    except (OSError, ValueError) as exc:
        raise RuntimeError("Bundled vocabulary provenance is invalid") from exc
    try:
        latest = json.loads(_read(API))["sha"]
        if not isinstance(latest, str) or not re.fullmatch(r"[0-9a-f]{40}", latest):
            raise ValueError("upstream returned an invalid revision")
        if current.get("revision") == latest:
            print(f"Vocabulary is up to date ({latest}).")
            return

        base = f"{RAW}/{latest}/"
        license_bytes = _read(base + "LICENSE")
        if license_bytes.replace(b"\r\n", b"\n") != (data_dir / "LICENSE-KyleBing.txt").read_bytes().replace(b"\r\n", b"\n"):
            raise ValueError("upstream license changed; review it before updating")
        words: dict[str, int] = {}
        for name, rank in SOURCES:
            lines = _read(base + quote(name)).decode("utf-8-sig").splitlines()
            count = 0
            for line in lines:
                word = line.split("\t", 1)[0].strip().casefold()
                if WORD.fullmatch(word):
                    words[word] = min(rank, words.get(word, rank))
                    count += 1
            if count < 100:
                raise ValueError(f"upstream vocabulary file is unexpectedly small: {name}")
        if len(words) < 1000:
            raise ValueError("upstream vocabulary is unexpectedly small")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        warnings.warn(f"Vocabulary update check failed; using the bundled snapshot: {exc}", stacklevel=2)
        return

    # A write failure must stop the build rather than package mismatched provenance.
    (data_dir / "vocabulary.json").write_text(
        json.dumps(words, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )
    source_path.write_text(json.dumps({"repository": REPOSITORY, "revision": latest}, indent=2) + "\n", encoding="utf-8")
    print(f"Updated vocabulary to {latest} ({len(words)} entries).")
