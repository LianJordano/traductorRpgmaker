"""Create and manage timestamped backups of game data directories."""
from __future__ import annotations
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from core import logger


def create_backup(data_dir: Path, game_dir: Path) -> Optional[Path]:
    """Copy data_dir into a timestamped backup folder inside game_dir."""
    if not data_dir.is_dir():
        logger.warning(f"Backup skipped – directory not found: {data_dir}")
        return None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = game_dir / "_rpgt_backups"
    backup_dest = backup_root / f"backup_{timestamp}" / data_dir.name

    try:
        shutil.copytree(data_dir, backup_dest)
        logger.success(f"Backup created: {backup_dest}")
        return backup_dest
    except Exception as exc:
        logger.error(f"Backup failed: {exc}")
        return None


def list_backups(game_dir: Path) -> list[Path]:
    backup_root = game_dir / "_rpgt_backups"
    if not backup_root.is_dir():
        return []
    return sorted(backup_root.iterdir(), reverse=True)


def restore_backup(backup_path: Path, data_dir: Path) -> bool:
    """Restore a specific backup over the current data_dir (atomic: rename then copy)."""
    if not backup_path.is_dir():
        logger.error(f"Backup path does not exist: {backup_path}")
        return False

    # Move existing data aside first so we can roll back if the copy fails
    temp_aside = data_dir.parent / (data_dir.name + "_rpgt_restore_tmp")
    moved = False
    try:
        if data_dir.exists():
            data_dir.rename(temp_aside)
            moved = True
        shutil.copytree(backup_path, data_dir)
        # Copy succeeded — remove the old data
        if moved:
            shutil.rmtree(temp_aside, ignore_errors=True)
        logger.success(f"Restored backup from: {backup_path}")
        return True
    except Exception as exc:
        logger.error(f"Restore failed: {exc}")
        # Roll back: put original data back
        if moved and temp_aside.exists() and not data_dir.exists():
            try:
                temp_aside.rename(data_dir)
                logger.info("Restore rolled back — original data preserved.")
            except Exception as rb_exc:
                logger.error(f"Rollback also failed: {rb_exc}. Original data may be at: {temp_aside}")
        return False


def cleanup_old_backups(game_dir: Path, keep: int = 5) -> None:
    backups = list_backups(game_dir)
    for old in backups[keep:]:
        try:
            shutil.rmtree(old.parent)
            logger.info(f"Removed old backup: {old.parent}")
        except Exception as exc:
            logger.warning(f"Could not remove old backup: {exc}")
