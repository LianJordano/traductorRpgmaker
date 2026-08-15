"""Extractor for RPG Maker XP (.rxdata Ruby Marshal files).

XP uses the same Marshal container as VX/VX Ace, so the whole extraction and
reinsertion pipeline is inherited. Two things differ:

* Ruby 1.8 dumps strings without an encoding marker, so every piece of text
  arrives as raw ``bytes`` and must be written back the same way.
* ``Show Text`` (code 101) keeps its first line inside the command itself
  instead of in a following ``401``.
"""
from __future__ import annotations

from extractors.rmvxace import VXAceExtractor

# RPG::Actor/Class/State in XP have fewer text fields than their VX Ace
# counterparts; missing ones are simply skipped at extraction time.
FILE_FIELDS: dict[str, list[str]] = {
    "Actors":  ["name"],
    "Armors":  ["name", "description"],
    "Classes": ["name"],
    "Enemies": ["name"],
    "Items":   ["name", "description"],
    "Skills":  ["name", "description"],
    "States":  ["name"],
    "Weapons": ["name", "description"],
}


class XPExtractor(VXAceExtractor):
    EXT = ".rxdata"
    TEXT_IN_HEADER = True
    RAW_BYTE_STRINGS = True

    @property
    def version(self) -> str:
        return "XP"

    def _fields_for(self, stem: str) -> list[str]:
        from core import config
        fields = list(FILE_FIELDS.get(stem, []))
        if fields and config.get("translate_notes"):
            fields.append("note")
        return fields

    def _get_target_files(self):
        files = sorted(self.data_dir.glob(f"Map[0-9]*{self.EXT}"))
        for stem in ("CommonEvents", "Troops", "System", *FILE_FIELDS):
            p = self.data_dir / f"{stem}{self.EXT}"
            if p.exists():
                files.append(p)
        return files
