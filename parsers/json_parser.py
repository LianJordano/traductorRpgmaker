"""Parse and write RPG Maker MV/MZ JSON data files."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any


def load(path: Path, encoding: str = "utf-8") -> Any:
    """Load a JSON file, trying multiple encodings if needed."""
    for enc in [encoding, "utf-8-sig", "utf-8", "latin-1"]:
        try:
            text = path.read_text(encoding=enc, errors="replace")
            return json.loads(text)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
    raise ValueError(f"Could not parse JSON: {path}")


def save(path: Path, data: Any, encoding: str = "utf-8") -> None:
    """Write data back as JSON, preserving MV/MZ formatting style."""
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    path.write_text(text, encoding=encoding)


def load_all(data_dir: Path) -> dict[str, Any]:
    """Load all JSON files from data_dir. Returns {filename: data}."""
    result = {}
    for p in sorted(data_dir.glob("*.json")):
        try:
            result[p.name] = load(p)
        except Exception:
            pass
    return result
