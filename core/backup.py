"""Create and manage backups of a game's data directory.

Backups are compressed ZIP archives rather than raw folder copies, and a new one
is only written when the data has actually changed. The very first backup of a
game is kept forever and never counts toward the retention limit: it is the only
copy of the *untranslated* game, and every later backup contains data that has
already been modified.
"""
from __future__ import annotations
import hashlib
import os
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from core import config, logger

BACKUP_DIR_NAME = "_rpgt_backups"
ORIGINAL_PREFIX = "original_"
ROLLING_PREFIX = "backup_"
_CHUNK = 1 << 20


def long_path(path: Path | str) -> str:
    r"""Windows extended-length form of an absolute path.

    Nested backups produced by older builds can bury a file far past Windows'
    260-character limit, at which point `scandir` and `rmtree` fail outright —
    which would leave exactly the folders that most need deleting undeletable.
    The `\\?\` prefix lifts that limit.
    """
    resolved = os.path.abspath(str(path))
    if sys.platform == "win32" and not resolved.startswith("\\\\?\\"):
        return "\\\\?\\" + resolved
    return resolved


def tree_size(path: Path) -> int:
    """Total bytes under `path`, tolerating unreadable or over-long entries."""
    p = Path(path)
    if p.is_file():
        try:
            return p.stat().st_size
        except OSError:
            return 0
    total = 0
    for root, _, files in os.walk(long_path(p), onerror=lambda e: None):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def remove_tree(path: Path) -> None:
    """Delete a directory tree, including paths beyond the Windows limit."""
    shutil.rmtree(long_path(path), ignore_errors=False)


def backup_root(game_dir: Path) -> Path:
    return Path(game_dir) / BACKUP_DIR_NAME


def _game_files(data_dir: Path) -> list[Path]:
    """Every game file under data_dir, excluding our own working files.

    Excluding the backup directory is essential: when the game folder and the
    data folder are the same (common for MV projects opened at `www/data`), the
    backup lands *inside* what gets copied, so each new backup contains all the
    previous ones and the folder doubles in size every single time. That is how
    a 200 MB game turned into 27 GB of nested copies.
    """
    out: list[Path] = []
    for path in sorted(data_dir.rglob("*")):
        if not path.is_file():
            continue
        parts = path.relative_to(data_dir).parts
        if BACKUP_DIR_NAME in parts:
            continue
        if path.name.endswith(".rpgt_tmp") or path.suffix == ".rpgt_tmp":
            continue
        out.append(path)
    return out


# --------------------------------------------------------------------------- #
# Fingerprinting
# --------------------------------------------------------------------------- #

def _fingerprint(data_dir: Path) -> str:
    """Content hash of a data directory, used to skip redundant backups."""
    h = hashlib.blake2b(digest_size=16)
    for path in _game_files(data_dir):
        h.update(path.relative_to(data_dir).as_posix().encode("utf-8") + b"\0")
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(_CHUNK), b""):
                h.update(chunk)
    return h.hexdigest()


def _stored_fingerprint(backup: Path) -> str:
    """Read the fingerprint recorded in a backup, or "" if unavailable."""
    if backup.suffix == ".zip":
        try:
            with zipfile.ZipFile(backup) as z:
                return (z.comment or b"").decode("utf-8", "replace")
        except Exception:
            return ""
    marker = backup / ".rpgt_fingerprint"
    try:
        return marker.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


# --------------------------------------------------------------------------- #
# Listing
# --------------------------------------------------------------------------- #

def list_backups(game_dir: Path) -> list[Path]:
    """Every backup for this game, newest first.

    Includes both the current ZIP archives and the folder copies older versions
    of the tool produced, so both can be listed, restored and cleaned up.
    """
    root = backup_root(game_dir)
    if not root.is_dir():
        return []
    items = [
        p for p in root.iterdir()
        if (p.is_dir() and not p.name.startswith("."))
        or (p.is_file() and p.suffix == ".zip")
    ]
    return sorted(items, key=lambda p: p.name, reverse=True)


def is_original(backup: Path) -> bool:
    return backup.name.startswith(ORIGINAL_PREFIX)


def usage(game_dir: Path) -> tuple[int, int]:
    """Return (number of backups, total bytes on disk)."""
    backups = list_backups(game_dir)
    return len(backups), sum(tree_size(b) for b in backups)


def _human(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{size} B"
        size /= 1024.0
    return f"{size:.1f} TB"


# --------------------------------------------------------------------------- #
# Creating
# --------------------------------------------------------------------------- #

def create_backup(data_dir: Path, game_dir: Path) -> Optional[Path]:
    """Back up data_dir, skipping the work when nothing has changed."""
    data_dir = Path(data_dir)
    game_dir = Path(game_dir)
    if not data_dir.is_dir():
        logger.warning(f"Backup skipped – directory not found: {data_dir}")
        return None

    migrate_legacy(game_dir)
    existing = list_backups(game_dir)
    fingerprint = _fingerprint(data_dir)

    # Nothing changed since a backup we already hold — writing another copy of
    # identical bytes is what makes these folders grow without bound.
    for previous in existing:
        if _stored_fingerprint(previous) == fingerprint:
            logger.info(
                f"Los archivos no han cambiado desde {previous.name}; "
                f"no se crea otra copia."
            )
            return previous

    first = not any(is_original(b) for b in existing)
    prefix = ORIGINAL_PREFIX if first else ROLLING_PREFIX
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    root = backup_root(game_dir)
    root.mkdir(parents=True, exist_ok=True)

    try:
        if config.get("backup_compress", True):
            dest = _write_archive(data_dir, root / f"{prefix}{stamp}.zip", fingerprint)
        else:
            dest = _write_folder(data_dir, root / f"{prefix}{stamp}" / data_dir.name,
                                 fingerprint)
    except Exception as exc:
        logger.error(f"Backup failed: {exc}")
        return None

    size = tree_size(dest)
    label = "original (se conserva siempre)" if first else "copia de seguridad"
    logger.success(f"Backup creado [{label}]: {dest.name} – {_human(size)}")

    cleanup_old_backups(game_dir, keep=int(config.get("backup_keep", 1)))
    return dest


def _write_archive(data_dir: Path, dest: Path, fingerprint: str) -> Path:
    """Write data_dir into a compressed archive, atomically."""
    tmp = dest.with_suffix(".zip.tmp")
    top = data_dir.name
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        z.comment = fingerprint.encode("utf-8")
        for path in _game_files(data_dir):
            z.write(path, f"{top}/{path.relative_to(data_dir).as_posix()}")
    tmp.replace(dest)
    return dest


def _write_folder(data_dir: Path, dest: Path, fingerprint: str) -> Path:
    shutil.copytree(
        data_dir, dest,
        ignore=shutil.ignore_patterns(BACKUP_DIR_NAME, "*.rpgt_tmp"),
    )
    try:
        (dest.parent / ".rpgt_fingerprint").write_text(fingerprint, encoding="utf-8")
    except Exception:
        pass
    return dest.parent


# --------------------------------------------------------------------------- #
# Restoring
# --------------------------------------------------------------------------- #

def restore_backup(backup_path: Path, data_dir: Path) -> bool:
    """Restore a backup over data_dir, rolling back if anything goes wrong.

    Accepts a ZIP archive, the `backup_<timestamp>` folder, or the data folder
    inside it.
    """
    backup_path = Path(backup_path)
    data_dir = Path(data_dir)
    if not backup_path.exists():
        logger.error(f"Backup path does not exist: {backup_path}")
        return False

    staging = data_dir.parent / (data_dir.name + "_rpgt_restore_new")
    temp_aside = data_dir.parent / (data_dir.name + "_rpgt_restore_old")
    for leftover in (staging, temp_aside):
        if leftover.exists():
            shutil.rmtree(long_path(leftover), ignore_errors=True)

    moved = False
    try:
        # Unpack into a staging folder *first*. The archive frequently lives
        # inside the very directory being replaced, so reading it after moving
        # that directory aside would fail — and a half-restored game is worse
        # than no restore at all.
        _unpack(backup_path, staging, data_dir.name)

        if data_dir.exists():
            data_dir.rename(temp_aside)
            moved = True
        staging.rename(data_dir)

        # The backup directory itself is excluded from every archive, so carry
        # it across rather than destroying every backup on the first restore.
        old_backups = temp_aside / BACKUP_DIR_NAME
        if moved and old_backups.is_dir():
            old_backups.rename(data_dir / BACKUP_DIR_NAME)

        if moved:
            shutil.rmtree(long_path(temp_aside), ignore_errors=True)
        logger.success(f"Restored backup from: {backup_path.name}")
        return True
    except Exception as exc:
        logger.error(f"Restore failed: {exc}")
        shutil.rmtree(long_path(staging), ignore_errors=True)
        if moved and temp_aside.exists():
            try:
                if data_dir.exists():
                    shutil.rmtree(long_path(data_dir), ignore_errors=True)
                temp_aside.rename(data_dir)
                logger.info("Restore rolled back — original data preserved.")
            except Exception as rb_exc:
                logger.error(
                    f"Rollback also failed: {rb_exc}. Original data may be at: {temp_aside}"
                )
        return False


def _unpack(backup_path: Path, dest: Path, data_name: str) -> None:
    """Materialise a backup into `dest`, from either an archive or a folder."""
    if backup_path.is_file() and backup_path.suffix == ".zip":
        dest.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(backup_path) as z:
            for info in z.infolist():
                if info.is_dir():
                    continue
                # Strip the leading data-folder name recorded in the archive.
                rel = Path(info.filename)
                parts = rel.parts[1:] if len(rel.parts) > 1 else rel.parts
                target = dest.joinpath(*parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
        return

    # Folder backup: the game files usually sit one level down.
    source = backup_path
    inner = backup_path / data_name
    if inner.is_dir():
        source = inner
    shutil.copytree(
        source, dest,
        ignore=shutil.ignore_patterns(BACKUP_DIR_NAME, "*.rpgt_tmp"),
    )


# --------------------------------------------------------------------------- #
# Retention
# --------------------------------------------------------------------------- #

def migrate_legacy(game_dir: Path) -> None:
    """Promote the oldest pre-existing backup to `original_`.

    Older versions of the tool named every backup `backup_<timestamp>`, so the
    untranslated copy is simply the oldest one. Marking it means retention can
    delete the rest without throwing away the only pristine data.
    """
    backups = list_backups(game_dir)
    if not backups or any(is_original(b) for b in backups):
        return
    oldest = backups[-1]
    if not oldest.name.startswith(ROLLING_PREFIX):
        return
    target = oldest.with_name(ORIGINAL_PREFIX + oldest.name[len(ROLLING_PREFIX):])
    try:
        oldest.rename(target)
        logger.info(f"Backup más antiguo marcado como original: {target.name}")
    except Exception as exc:
        logger.warning(f"No se pudo marcar el backup original: {exc}")


def purge_nested(game_dir: Path) -> int:
    """Delete backup folders nested inside other backups. Returns bytes freed.

    These only exist because older builds copied the backup directory into each
    new backup; every one of them duplicates a sibling that is still present.
    """
    freed = 0
    for backup in list_backups(game_dir):
        if backup.is_file():
            continue
        for nested in _find_nested(backup):
            try:
                freed += tree_size(nested)
                remove_tree(nested)
                logger.info(f"Copia anidada eliminada: {nested.name} (en {backup.name})")
            except Exception as exc:
                logger.warning(f"No se pudo eliminar {nested}: {exc}")
    return freed


def _find_nested(backup: Path) -> list[Path]:
    """Backup directories inside `backup`, without descending into them."""
    found: list[Path] = []
    for root, dirs, _ in os.walk(long_path(backup), onerror=lambda e: None):
        if BACKUP_DIR_NAME in dirs:
            found.append(Path(os.path.join(root, BACKUP_DIR_NAME)))
            dirs.remove(BACKUP_DIR_NAME)
    return found


def reclaim_space(game_dir: Path, keep: Optional[int] = None) -> int:
    """Full maintenance pass over one game's backups. Returns bytes freed."""
    game_dir = Path(game_dir)
    before = usage(game_dir)[1]
    migrate_legacy(game_dir)
    purge_nested(game_dir)
    cleanup_old_backups(game_dir, keep if keep is not None else int(config.get("backup_keep", 1)))
    freed = before - usage(game_dir)[1]
    if freed > 0:
        logger.success(f"Espacio recuperado en {game_dir.name}: {_human(freed)}")
    else:
        logger.info(f"No hay backups sobrantes en {game_dir.name}.")
    return freed


def cleanup_old_backups(game_dir: Path, keep: int = 1) -> int:
    """Delete rolling backups beyond the newest `keep`. Returns bytes freed.

    The `original_*` backup is never removed: it is the only untranslated copy
    of the game. Note this deletes the backups themselves — removing
    `old.parent` would wipe out the whole `_rpgt_backups` directory.
    """
    rolling = [b for b in list_backups(game_dir) if not is_original(b)]
    freed = 0
    for old in rolling[max(0, keep):]:
        try:
            size = tree_size(old)
            if old.is_file():
                old.unlink()
            else:
                remove_tree(old)
            freed += size
            logger.info(f"Backup antiguo eliminado: {old.name}")
        except Exception as exc:
            logger.warning(f"Could not remove old backup: {exc}")
    if freed:
        logger.success(f"Espacio liberado: {_human(freed)}")
    return freed
