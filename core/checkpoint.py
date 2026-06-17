"""Save and restore extraction/translation progress to allow resume after interruption."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Optional

from core import logger

CHECKPOINT_DIR = Path.home() / ".rpg_translator" / "checkpoints"
CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)


def _key_path(game_path: str | Path) -> Path:
    safe = Path(game_path).resolve().as_posix().replace("/", "_").replace(":", "")
    return CHECKPOINT_DIR / f"{safe}.json"


def save(game_path: str | Path, data: dict) -> None:
    path = _key_path(game_path)
    try:
        # Compact JSON (no indentation) — for 50k+ entries this is dramatically
        # smaller and faster to write/read than an indented dump. Write to a temp
        # file then replace, so an interrupted save can't corrupt the checkpoint.
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        tmp.replace(path)
        logger.debug(f"Checkpoint saved: {path.name}")
    except Exception as exc:
        logger.warning(f"Could not save checkpoint: {exc}")


def load(game_path: str | Path) -> Optional[dict]:
    path = _key_path(game_path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning(f"Could not load checkpoint: {exc}")
        return None


def delete(game_path: str | Path) -> None:
    path = _key_path(game_path)
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass


def exists(game_path: str | Path) -> bool:
    return _key_path(game_path).exists()
