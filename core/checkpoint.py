"""Save and restore translation progress so a run can resume after interruption."""
from __future__ import annotations
import json
import re
import sys
import time
from pathlib import Path
from typing import Optional

from core import logger


def _app_dir() -> Path:
    """Folder the app lives in: next to the .exe when frozen, else the repo root.

    PyInstaller unpacks a onefile build into a temp dir that is wiped on exit,
    so `__file__` is not a place anything may be stored.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


#: Kept inside the app folder, not in the user profile, so the whole cache can
#: be deleted by dragging one visible folder to the bin.
CHECKPOINT_DIR = _app_dir() / "traducciones_ejecutadas"
CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)

#: Checkpoints older than this are dropped on startup.
MAX_AGE_DAYS = 30

#: A checkpoint touched this recently is never deleted by housekeeping — not by
#: the age rule, not by the size cap. An interrupted translation is the only
#: copy of that work on disk, so resuming it must never depend on how many other
#: games happen to be cached. If the cap cannot be met without touching recent
#: work, the folder is allowed to run over and a warning is logged instead.
PROTECTED_DAYS = 7

#: Hard ceiling for the whole folder. Reached, the least recently used
#: checkpoints are deleted first. A big game costs ~15 MB, so this still keeps
#: dozens of games resumable while capping the folder well short of a gigabyte.
MAX_TOTAL_MB = 400

#: Where checkpoints lived before they moved into the app folder. Nothing is
#: written here any more, but an old install can still be holding data.
LEGACY_DIR = Path.home() / ".rpg_translator" / "checkpoints"


def sibling_dirs() -> list[Path]:
    """Checkpoint folders that exist but are not the one this run writes to.

    Running from source and running the built .exe resolve `_app_dir()` to
    different places, so each keeps its own folder. Without listing the other
    one, cleaning from here reports an empty cache while up to MAX_TOTAL_MB sits
    invisible in the other — the exact accumulation this is meant to prevent.
    """
    app = _app_dir()
    candidates = [
        LEGACY_DIR,
        app / "dist" / "traducciones_ejecutadas",      # source run -> built exe
    ]
    if app.name.lower() == "dist":
        candidates.append(app.parent / "traducciones_ejecutadas")  # exe -> source

    found: list[Path] = []
    for path in candidates:
        try:
            if path.resolve() == CHECKPOINT_DIR.resolve():
                continue
            if path.is_dir() and any(path.glob("*.json")):
                found.append(path)
        except Exception:
            continue
    return found


def dir_usage(directory: Path) -> tuple[int, int]:
    """Return (number of checkpoints, total bytes) for any checkpoint folder."""
    try:
        files = list(Path(directory).glob("*.json"))
    except Exception:
        return 0, 0
    total = 0
    for f in files:
        try:
            total += f.stat().st_size
        except Exception:
            pass
    return len(files), total


def clear_dir(directory: Path) -> int:
    """Delete every checkpoint in an arbitrary folder. Returns bytes freed."""
    directory = Path(directory)
    freed = 0
    for path in list(directory.glob("*.json")) + list(directory.glob("*.json.tmp")):
        try:
            freed += path.stat().st_size
            path.unlink()
        except Exception:
            pass
    return freed


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
    """Return (number of checkpoints, total bytes) for the active folder."""
    return dir_usage(CHECKPOINT_DIR)


def _peek_game_path(path: Path) -> str:
    """Read the game path out of a checkpoint without parsing the whole file.

    A checkpoint for a large game is tens of MB; json.loads on every one of them
    just to fill a list would stall the window for seconds. `_compact` always
    writes "game_path" first, so the head of the file is enough.
    """
    try:
        with path.open("r", encoding="utf-8") as fh:
            head = fh.read(2048)
        match = re.search(r'"game_path"\s*:\s*"((?:[^"\\]|\\.)*)"', head)
        if match:
            return json.loads(f'"{match.group(1)}"')
    except Exception:
        pass
    return ""


def entries() -> list[dict]:
    """One record per stored checkpoint, largest first.

    Keys: path, game_path, name, size, mtime.
    """
    protected_after = time.time() - PROTECTED_DAYS * 86400
    out: list[dict] = []
    for path in CHECKPOINT_DIR.glob("*.json"):
        try:
            stat = path.stat()
        except Exception:
            continue
        game_path = _peek_game_path(path)
        out.append({
            "path": path,
            "game_path": game_path,
            "name": Path(game_path).name if game_path else path.stem,
            "size": stat.st_size,
            "mtime": stat.st_mtime,
            # Housekeeping will not touch this one; only an explicit delete will.
            "protected": stat.st_mtime >= protected_after,
        })
    out.sort(key=lambda e: e["size"], reverse=True)
    return out


def delete_file(path: str | Path) -> int:
    """Delete one checkpoint by its own path. Returns bytes freed."""
    path = Path(path)
    try:
        size = path.stat().st_size
        path.unlink()
        return size
    except Exception:
        return 0


def clear() -> int:
    """Delete every checkpoint in the active folder. Returns bytes freed."""
    freed = clear_dir(CHECKPOINT_DIR)
    if freed:
        logger.info(f"Traducciones ejecutadas borradas: {freed / (1024*1024):.1f} MB")
    return freed


def prune(max_age_days: int = MAX_AGE_DAYS, max_total_mb: int = MAX_TOTAL_MB) -> int:
    """Keep the folder small: drop stale checkpoints, then enforce a size cap.

    Without the cap the folder only ever grows — every game translated leaves a
    few MB behind forever, and nothing ages out until a month has passed.
    Returns bytes freed.
    """
    now = time.time()
    cutoff = now - max_age_days * 86400
    protected_after = now - PROTECTED_DAYS * 86400
    freed = 0

    def _files() -> list[Path]:
        return list(CHECKPOINT_DIR.glob("*.json")) + list(CHECKPOINT_DIR.glob("*.json.tmp"))

    for path in _files():
        try:
            if path.stat().st_mtime < cutoff:
                freed += path.stat().st_size
                path.unlink()
        except Exception:
            pass

    # Still over budget: evict least recently used first until it fits, but
    # never a recent one — that could be a translation someone left half done.
    budget = max_total_mb * 1024 * 1024
    try:
        remaining = sorted(_files(), key=lambda f: f.stat().st_mtime, reverse=True)
    except Exception:
        remaining = []
    total = 0
    kept_over_budget = 0
    for path in remaining:
        try:
            stat = path.stat()
            if total + stat.st_size <= budget:
                total += stat.st_size
                continue
            if stat.st_mtime >= protected_after:
                total += stat.st_size
                kept_over_budget += stat.st_size
                continue
            path.unlink()
            freed += stat.st_size
        except Exception:
            pass

    if freed:
        logger.info(f"Puntos de control antiguos eliminados: {freed / (1024*1024):.1f} MB")
    if kept_over_budget:
        logger.warning(
            f"Se supera el limite de {max_total_mb} MB en "
            f"{kept_over_budget / (1024*1024):.1f} MB: son traducciones de los ultimos "
            f"{PROTECTED_DAYS} dias y no se borran. Usa 'Limpiar traducciones' si necesitas espacio."
        )
    return freed
