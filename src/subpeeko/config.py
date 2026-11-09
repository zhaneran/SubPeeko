"""Local configuration and system credential storage."""

from __future__ import annotations

import getpass
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values

SERVICE = "subpeeko"
KEY_NAME = "model-api-key"
SECURE_BACKENDS = {
    "keyring.backends.Windows",
    "keyring.backends.SecretService",
    "keyring.backends.kwallet",
    "keyring.backends.macOS",
}


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    base_url: str = ""
    model_name: str = ""
    api_key: str = field(default="", repr=False)


def config_path() -> Path:
    if sys.platform == "win32":
        root = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
        if not root.is_absolute():
            root = Path.home() / ".config"
    return root / SERVICE / "config.json"


def _read_saved() -> dict[str, str]:
    path = config_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigError(f"Cannot read configuration: {path}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"Invalid configuration: {path}")
    return {key: value for key, value in data.items() if isinstance(value, str)}


def _keyring():
    try:
        import keyring

        backend = keyring.get_keyring()
        if type(backend).__module__ == "keyring.backends.chainer":
            backend = next((item for item in backend.backends if type(item).__module__ in SECURE_BACKENDS), None)
            if backend is None:
                return None
        if type(backend).__module__ not in SECURE_BACKENDS:
            return None
        return backend
    except Exception:
        return None


def _stored_key() -> str:
    backend = _keyring()
    if backend is None:
        return ""
    try:
        return backend.get_password(SERVICE, KEY_NAME) or ""
    except Exception:
        return ""


def load_config(require: bool = True) -> Config:
    saved = _read_saved()
    try:
        dotenv = dotenv_values(Path.cwd() / ".env")
    except OSError as exc:
        raise ConfigError("Cannot read the local .env file") from exc

    def value(name: str, default: str = "") -> str:
        return (os.environ.get(name) or dotenv.get(name) or default).strip()

    config = Config(
        base_url=value("SUBPEEKO_BASE_URL", saved.get("base_url", "")),
        model_name=value("SUBPEEKO_MODEL_NAME", saved.get("model_name", "")),
        api_key=value("SUBPEEKO_API_KEY") or _stored_key(),
    )
    if require:
        missing = [
            name for name, item in (
                ("base URL", config.base_url),
                ("model name", config.model_name),
                ("API key", config.api_key),
            ) if not item
        ]
        if missing:
            raise ConfigError(
                "Missing " + ", ".join(missing)
                + ". Run 'subpeeko config' or set the SUBPEEKO_* environment variables."
            )
        validate_base_url(config.base_url)
    return config


def validate_base_url(url: str) -> None:
    try:
        parsed = urlsplit(url)
        valid = (parsed.scheme in {"http", "https"} and parsed.hostname
                 and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment)
    except ValueError:
        valid = False
    if not valid:
        raise ConfigError("Base URL must be an HTTP(S) API root without credentials or a query string")


def configure() -> None:
    saved = _read_saved()
    print("Configure an OpenAI-compatible Chat Completions API.")
    base = input(f"Base URL [{saved.get('base_url', '')}]: ").strip() or saved.get("base_url", "")
    model = input(f"Model name [{saved.get('model_name', '')}]: ").strip() or saved.get("model_name", "")
    if not base or not model:
        raise ConfigError("Both base URL and model name are required")
    validate_base_url(base)

    path = config_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"base_url": base, "model_name": model}, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"Cannot save configuration: {path}") from exc

    backend = _keyring()
    if backend is None:
        print("No supported system credential store is available; set SUBPEEKO_API_KEY in the environment.")
    else:
        if not sys.stdin.isatty():
            raise ConfigError("An interactive terminal is required to enter a key; use SUBPEEKO_API_KEY otherwise")
        key = getpass.getpass("API key (leave blank to keep the existing key): ").strip()
        if key:
            try:
                backend.set_password(SERVICE, KEY_NAME, key)
            except Exception as exc:
                raise ConfigError("Cannot save the API key in the system credential store; use SUBPEEKO_API_KEY") from exc
    print(f"Configuration saved to {path}. API keys are never stored in this file.")


def show_config() -> None:
    config = load_config(require=False)
    base_url = config.base_url or "(not set)"
    if config.base_url:
        try:
            validate_base_url(config.base_url)
        except ConfigError:
            base_url = "(invalid URL)"
    print(f"Base URL: {base_url}")
    print(f"Model: {config.model_name or '(not set)'}")
    print(f"API key: {'configured' if config.api_key else '(not set)'}")
