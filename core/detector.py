"""Detect the RPG Maker version from a game folder.

Walks up parent directories so users can select any subfolder of the game.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class DetectionResult:
    version: str = "unknown"          # 'MV', 'MZ', 'VXAce', 'VX', 'XP', 'RM2003', 'RM2000'
    display_name: str = "Unknown"
    data_dir: Optional[Path] = None   # where the game data files live
    game_dir: Path = field(default_factory=Path)
    confidence: int = 0               # 0-100
    notes: list[str] = field(default_factory=list)

    @property
    def is_json_based(self) -> bool:
        return self.version in ("MV", "MZ")

    @property
    def is_marshal_based(self) -> bool:
        return self.version in ("XP", "VX", "VXAce")

    @property
    def is_binary_based(self) -> bool:
        return self.version in ("RM2000", "RM2003")

    @property
    def supported(self) -> bool:
        return self.version != "unknown"


def detect(game_path: str | Path) -> DetectionResult:
    """Return a DetectionResult for the given game folder.

    If the exact path does not match, walks up parent directories
    (up to 5 levels) so selecting any subfolder still works.
    """
    start = Path(game_path).resolve()
    if not start.is_dir():
        return DetectionResult(game_dir=start, notes=["Path is not a directory"])

    candidate = start
    for _ in range(6):
        result = _detect_at(candidate)
        if result.supported:
            return result
        parent = candidate.parent
        if parent == candidate:
            break
        candidate = parent

    result = DetectionResult(game_dir=start)
    result.notes.append("No recognizable RPG Maker structure found")
    return result


def _detect_at(root: Path) -> DetectionResult:
    """Try to detect RPG Maker version at exactly this directory."""
    result = DetectionResult(game_dir=root)

    # --- RPG Maker MZ ---
    mz_markers = [root / "js" / "rmmz_core.js", root / "js" / "rmmz_managers.js"]
    if any(p.exists() for p in mz_markers):
        result.version = "MZ"
        result.display_name = "RPG Maker MZ"
        result.confidence = 98
        result.data_dir = _find_json_data_dir(root)
        return result

    # --- RPG Maker MV ---
    mv_markers = [root / "js" / "rpg_core.js", root / "js" / "plugins.js"]
    if any(p.exists() for p in mv_markers):
        result.version = "MV"
        result.display_name = "RPG Maker MV"
        result.confidence = 97
        result.data_dir = _find_json_data_dir(root)
        return result

    # MV/MZ without js folder but with www/data JSON
    if (root / "www" / "data").is_dir() and _has_json_data(root / "www" / "data"):
        pkg = root / "package.json"
        if pkg.exists():
            try:
                import json
                info = json.loads(pkg.read_text(encoding="utf-8"))
                if "mz" in str(info).lower():
                    result.version = "MZ"
                    result.display_name = "RPG Maker MZ"
                else:
                    result.version = "MV"
                    result.display_name = "RPG Maker MV"
                result.confidence = 90
                result.data_dir = root / "www" / "data"
                return result
            except Exception:
                pass
        result.version = "MV"
        result.display_name = "RPG Maker MV"
        result.confidence = 80
        result.data_dir = root / "www" / "data"
        return result

    # JSON data directly in data/ (some MV/MZ deployments)
    for sub in ("data", "Data"):
        if (root / sub).is_dir() and _has_json_data(root / sub):
            result.version = "MV"
            result.display_name = "RPG Maker MV/MZ"
            result.confidence = 75
            result.data_dir = root / sub
            return result

    # Root itself is the data folder
    if _has_json_data(root):
        result.version = "MV"
        result.display_name = "RPG Maker MV/MZ"
        result.confidence = 70
        result.data_dir = root
        return result

    # --- RPG Maker VX Ace ---
    if (root / "Game.rvproj2").exists() or _has_ext(root / "Data", ".rvdata2"):
        result.version = "VXAce"
        result.display_name = "RPG Maker VX Ace"
        result.confidence = 96
        result.data_dir = root / "Data"
        return result

    # --- RPG Maker VX ---
    if (root / "Game.rvproj").exists() or _has_ext(root / "Data", ".rvdata"):
        result.version = "VX"
        result.display_name = "RPG Maker VX"
        result.confidence = 95
        result.data_dir = root / "Data"
        return result

    # --- RPG Maker XP ---
    if (root / "Game.rxproj").exists() or _has_ext(root / "Data", ".rxdata"):
        result.version = "XP"
        result.display_name = "RPG Maker XP"
        result.confidence = 95
        result.data_dir = root / "Data"
        return result

    # --- RPG Maker 2003 / 2000 ---
    if (root / "RPG_RT.lmt").exists():
        ldb = root / "RPG_RT.ldb"
        if ldb.exists():
            try:
                header = ldb.read_bytes()[:20]
                if b"2003" in header or b"LcfDataBase" in header:
                    result.version = "RM2003"
                    result.display_name = "RPG Maker 2003"
                else:
                    result.version = "RM2000"
                    result.display_name = "RPG Maker 2000"
            except Exception:
                result.version = "RM2003"
                result.display_name = "RPG Maker 2003"
        else:
            result.version = "RM2003"
            result.display_name = "RPG Maker 2003"
        result.confidence = 90
        result.data_dir = root
        return result

    if (root / "RPG_RT.ldb").exists():
        result.version = "RM2000"
        result.display_name = "RPG Maker 2000"
        result.confidence = 85
        result.data_dir = root
        return result

    return result  # version == "unknown"


def _find_json_data_dir(root: Path) -> Optional[Path]:
    for candidate in [root / "www" / "data", root / "data", root / "Data"]:
        if candidate.is_dir() and _has_json_data(candidate):
            return candidate
    return None


def _has_json_data(data_dir: Path) -> bool:
    key_files = [
        "Actors.json", "System.json", "Items.json", "Map001.json",
        "actors.json", "system.json", "items.json", "map001.json",
    ]
    return any((data_dir / f).exists() for f in key_files)


def _has_ext(directory: Path, ext: str) -> bool:
    if not directory.is_dir():
        return False
    return any(directory.glob(f"*{ext}"))
