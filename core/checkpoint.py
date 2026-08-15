"""Save and restore translation progress so a run can resume after interruption."""
from __future__ import annotations
import json
import time
from pathlib import Path
from typing import Optional

from core import logger

CHECKPOINT_DIR = Path.home() / ".rpg_translator" / "checkpoints"
CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)

#: Checkpoints older than this are dropped on startup.
MAX_AGE_DAYS = 30


def _key_path(game_path: str | Path) -> Path:
    safe = Path(game_path).resolve().as_posix().replace("/", "_").replace(":", "")
    return CHECKPOINT_DIR / f"{safe}.json"


def _compact(data: dict) -> dict:
    """Keep only what resuming actually needs.

    A full result dump repeats every original string and all reinsertion
    metadata, which is already recoverable by re-extracting the game — and for a
    100k-text game that is hundreds of megabytes rewritten every few seconds.
    Only finished translations are worth persisting.
    """
    return {
        "game_path": data.get("game_path", ""),
        "version": data.get("version", ""),
        "entries": [
            {"uid": e["uid"], "translation": e.get("translation", ""), "status": "translated"}
            for e in data.get("entries", [])
            if e.get("status") == "translated" and e.get("translation")
        ],
    }


def save(game_path: str | Path, data: dict) -> None:
    path = _key_path(game_path)
    try:
        # Compact JSON (no indentation) — for 50k+ entries this is dramatically
        # smaller and faster to write/read than an indented dump. Write to a temp
        # file then replace, so an interrupted save can't corrupt the checkpoint.
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(_compact(data), ensure_ascii=False, separators=(",", ":")),
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


def usage() -> tuple[int, int]:
    """Return (number of checkpoints, total bytes)."""
    files = list(CHECKPOINT_DIR.glob("*.json"))
    return len(files), sum(f.stat().st_size for f in files)


def prune(max_age_days: int = MAX_AGE_DAYS) -> int:
    """Delete checkpoints not touched in a long time. Returns bytes freed."""
    cutoff = time.time() - max_age_days * 86400
    freed = 0
    for path in list(CHECKPOINT_DIR.glob("*.json")) + list(CHECKPOINT_DIR.glob("*.json.tmp")):
        try:
            if path.stat().st_mtime < cutoff:
                freed += path.stat().st_size
                path.unlink()
        except Exception:
            pass
    if freed:
        logger.info(f"Puntos de control antiguos eliminados: {freed / (1024*1024):.1f} MB")
    return freed
