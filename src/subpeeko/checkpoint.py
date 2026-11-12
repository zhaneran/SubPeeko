"""Local checkpoints for model results already reviewed for an exact input."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import sys
from pathlib import Path
from threading import Lock

from . import model, subtitles, vocabulary
from .config import Config


class CheckpointError(Exception):
    pass


def cache_dir() -> Path:
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        root = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
        if not root.is_absolute():
            root = Path.home() / ".cache"
    return root / "subpeeko" / "checkpoints"


def checkpoint_key(path: Path, source_hash: bytes, config: Config, level: str, *, batch_size: int,
                   thinking: str, max_output_tokens: int) -> str:
    digest = hashlib.sha256()
    try:
        values = (
            b"subpeeko-checkpoint-v1", str(path.resolve()).encode(), source_hash,
            config.base_url.encode(), config.model_name.encode(), config.api_key.encode(),
            level.encode(), str(batch_size).encode(), thinking.encode(), str(max_output_tokens).encode(),
            Path(model.__file__).read_bytes(), Path(subtitles.__file__).read_bytes(),
            Path(vocabulary.__file__).read_bytes(),
            vocabulary.files("subpeeko").joinpath("data/vocabulary.json").read_bytes(),
        )
    except OSError as exc:
        raise CheckpointError("Cannot read checkpoint inputs") from exc
    for value in values:
        digest.update(len(value).to_bytes(8, "big"))
        digest.update(value)
    return digest.hexdigest()


class Checkpoint:
    def __init__(self, key: str):
        self.lock = Lock()
        self.connection = None
        try:
            root = cache_dir()
            root.mkdir(mode=0o700, parents=True, exist_ok=True)
            path = root / f"{key}.sqlite3"
            descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
            os.close(descriptor)
            self.connection = sqlite3.connect(path, timeout=30, check_same_thread=False)
            self.connection.execute("CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY, note TEXT NOT NULL)")
            self.connection.commit()
        except (OSError, sqlite3.Error) as exc:
            if self.connection is not None:
                self.connection.close()
            raise CheckpointError("Cannot open the local checkpoint; use --no-resume to disable it") from exc

    def load(self, valid_ids: set[int]) -> dict[int, str]:
        try:
            with self.lock:
                rows = self.connection.execute("SELECT id, note FROM notes").fetchall()
            if any(type(identifier) is not int or identifier not in valid_ids or not isinstance(note, str)
                   or any(char in note for char in "{}\\\r\n") for identifier, note in rows):
                raise CheckpointError("Local checkpoint contains invalid results; use --no-resume")
            return dict(rows)
        except sqlite3.Error as exc:
            raise CheckpointError("Cannot read the local checkpoint; use --no-resume") from exc

    def save(self, notes: dict[int, str]) -> None:
        try:
            with self.lock, self.connection:
                self.connection.executemany("INSERT OR REPLACE INTO notes (id, note) VALUES (?, ?)", notes.items())
        except sqlite3.Error as exc:
            raise CheckpointError("Cannot save the local checkpoint; completed batches remain available") from exc

    def close(self) -> None:
        if self.connection is not None:
            self.connection.close()
