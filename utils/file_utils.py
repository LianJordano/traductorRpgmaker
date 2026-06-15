"""File system utilities."""
from __future__ import annotations
import shutil
from pathlib import Path
from typing import Iterator


def iter_game_files(data_dir: Path, extensions: list[str]) -> Iterator[Path]:
    for ext in extensions:
        yield from sorted(data_dir.glob(f"*{ext}"))


def safe_copy(src: Path, dst: Path) -> bool:
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return True
    except Exception:
        return False


def dir_size_mb(path: Path) -> float:
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return total / (1024 * 1024)


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path
