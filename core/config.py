"""Global application configuration with JSON persistence."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any

APP_NAME = "RPG Translator Pro"
APP_VERSION = "1.0.0"
CONFIG_FILE = Path.home() / ".rpg_translator" / "config.json"

DEFAULTS: dict[str, Any] = {
    "theme": "dark",
    "language_from": "en",
    "language_to": "es",
    "translator": "google",
    "batch_size": 50,
    "delay_ms": 200,
    "max_workers": 8,  # concurrent translation requests
    "backup_enabled": True,
    "checkpoint_enabled": True,
    "openai_api_key": "",
    "openai_model": "gpt-4o-mini",
    "deepl_api_key": "",
    "output_dir": "",
    "last_game_path": "",
    "max_text_length": 5000,
    "skip_already_latin": False,
    "export_format": "csv",
    # Re-wrap translated messages to the window width and split them into
    # extra pages; without this, longer translations run off the message box.
    "wrap_text": True,
    "max_message_lines": 4,
    # `note` fields are what plugins and scripts read their notetags from, so
    # translating them usually breaks the game rather than the text.
    "translate_notes": False,
    # Backups: the untranslated `original_` copy is always kept; this is how
    # many later copies to retain on top of it. They are stored compressed.
    "backup_keep": 1,
    "backup_compress": True,
}

_config: dict[str, Any] = {}


def load() -> dict[str, Any]:
    global _config
    _config = dict(DEFAULTS)
    if CONFIG_FILE.exists():
        try:
            stored = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            _config.update(stored)
        except Exception:
            pass
    return _config


def get(key: str, default: Any = None) -> Any:
    if not _config:
        load()
    return _config.get(key, DEFAULTS.get(key, default))


def set(key: str, value: Any) -> None:
    if not _config:
        load()
    _config[key] = value
    save()


def save() -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(
        json.dumps(_config, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def update(data: dict[str, Any]) -> None:
    if not _config:
        load()
    _config.update(data)
    save()


load()
