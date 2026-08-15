"""Parse and write RPG Maker MV/MZ data files."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any


def load(path: Path, encoding: str = "utf-8") -> Any:
    """Load a JSON file, trying several encodings before giving up.

    Decoding is strict on purpose: replacing undecodable bytes would silently
    swap real characters for U+FFFD and that corruption would then be written
    straight back into the game.
    """
    raw = path.read_bytes()
    last_error: Exception | None = None
    for enc in (encoding, "utf-8-sig", "utf-8", "cp932", "cp1252"):
        try:
            return json.loads(raw.decode(enc))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            last_error = exc
            continue
    raise ValueError(f"Could not parse JSON: {path} ({last_error})")


def save(path: Path, data: Any, encoding: str = "utf-8") -> None:
    """Write data back as JSON in RPG Maker's compact style.

    Written through a temporary file and moved into place, so an interrupted
    write can never leave the game with a half-written data file.
    """
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    tmp = path.with_suffix(path.suffix + ".rpgt_tmp")
    tmp.write_text(text, encoding=encoding, newline="")
    tmp.replace(path)


def load_all(data_dir: Path) -> dict[str, Any]:
    """Load all JSON files from data_dir. Returns {filename: data}."""
    result = {}
    for p in sorted(data_dir.glob("*.json")):
        try:
            result[p.name] = load(p)
        except Exception:
            pass
    return result
