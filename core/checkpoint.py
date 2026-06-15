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
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
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
