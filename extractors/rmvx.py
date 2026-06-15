"""Extractor for RPG Maker VX (.rvdata files). Delegates to VXAce with adapted field names."""
from __future__ import annotations
from pathlib import Path

from core.models import ExtractionResult
from extractors.rmvxace import VXAceExtractor

FILE_FIELDS_VX: dict[str, list[str]] = {
    "Actors.rvdata":    ["name", "nickname", "description", "note"],
    "Armors.rvdata":    ["name", "description", "note"],
    "Classes.rvdata":   ["name", "note"],
    "Enemies.rvdata":   ["name", "note"],
    "Items.rvdata":     ["name", "description", "note"],
    "Skills.rvdata":    ["name", "description", "message1", "message2", "note"],
    "States.rvdata":    ["name", "note", "message1", "message2", "message3", "message4"],
    "Weapons.rvdata":   ["name", "description", "note"],
    "Troops.rvdata":    ["name"],
    "System.rvdata":    ["game_title", "currency_unit"],
}


class VXExtractor(VXAceExtractor):
    """VX uses same Ruby Marshal format as VX Ace but with .rvdata extension."""

    @property
    def version(self) -> str:
        return "VX"

    def _get_target_files(self) -> list[Path]:
        files = list(sorted(self.data_dir.glob("Map[0-9]*.rvdata")))
        p = self.data_dir / "CommonEvents.rvdata"
        if p.exists():
            files.append(p)
        for name in FILE_FIELDS_VX:
            p = self.data_dir / name
            if p.exists():
                files.append(p)
        return files

    def _extract_file(self, fpath: Path):  # type: ignore[override]
        from parsers import marshal_parser as mp
        name = fpath.name
        data = mp.load(fpath)
        fields = FILE_FIELDS_VX.get(name, [])
        if name.startswith("Map") and name[3].isdigit():
            return self._extract_map(data, name)
        if name == "CommonEvents.rvdata":
            return self._extract_common_events(data, name)
        if fields:
            return self._extract_database_file(data, name, fields)
        return []
