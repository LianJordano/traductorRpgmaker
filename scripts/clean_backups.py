"""Reclaim disk space taken by RPG Translator backups.

Older builds copied the backup directory into each new backup, so when a game's
data folder and its root folder were the same the copies nested inside one
another and doubled in size every run. This sweeps a folder tree, removes those
nested duplicates, keeps the oldest (untranslated) backup of every game plus the
newest few, and reports what it freed.

    python scripts/clean_backups.py D:\\rhgames            # dry run, shows the plan
    python scripts/clean_backups.py D:\\rhgames --apply    # actually delete
    python scripts/clean_backups.py D:\\rhgames --apply --keep 2
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import backup as bk  # noqa: E402


def human(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:,.1f} {unit}"
        size /= 1024.0
    return f"{size:,.1f} TB"


def find_games(root: Path) -> list[Path]:
    """Every game folder that owns a top-level backup directory.

    The walk never descends into a backup directory: anything inside one is a
    nested duplicate, and those are removed together with their parent. Not
    descending also keeps the scan away from the over-long paths the nesting
    created.
    """
    import os
    games: list[Path] = []
    for cur, dirs, _ in os.walk(bk.long_path(root), onerror=lambda e: None):
        if bk.BACKUP_DIR_NAME in dirs:
            games.append(Path(cur))
            dirs.remove(bk.BACKUP_DIR_NAME)
    return sorted(set(games))


def main() -> int:
    ap = argparse.ArgumentParser(description="Limpia los backups de RPG Translator Pro.")
    ap.add_argument("root", type=Path, help="Carpeta a recorrer (p. ej. D:\\rhgames)")
    ap.add_argument("--apply", action="store_true",
                    help="Ejecuta la limpieza (sin esto solo muestra el plan)")
    ap.add_argument("--keep", type=int, default=1,
                    help="Copias recientes a conservar además del original (por defecto 1)")
    args = ap.parse_args()

    if not args.root.is_dir():
        print(f"No es una carpeta: {args.root}")
        return 1

    print(f"Buscando backups en {args.root} ...\n")
    games = find_games(args.root)
    if not games:
        print("No se han encontrado carpetas _rpgt_backups.")
        return 0

    total_before = 0
    total_freed = 0
    for game in games:
        count, size = bk.usage(game)
        total_before += size
        print(f"{human(size):>12}  {count:>2} copias  {game}")
        for b in bk.list_backups(game):
            nested = "" if b.is_file() else (
                "  (contiene copias anidadas)" if bk._find_nested(b) else ""
            )
            print(f"                 - {b.name}{nested}")

        if args.apply:
            freed = bk.reclaim_space(game, keep=args.keep)
            total_freed += freed
            print(f"                 => liberado {human(freed)}\n")
        else:
            print()

    print("-" * 70)
    print(f"Ocupado por backups: {human(total_before)} en {len(games)} juegos")
    if args.apply:
        print(f"Espacio liberado   : {human(total_freed)}")
        print(f"Ocupado ahora      : {human(total_before - total_freed)}")
    else:
        print("\nEjecución en seco. Añade --apply para borrar de verdad.")
        print("Se conserva siempre el backup más antiguo de cada juego (el sin traducir).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
