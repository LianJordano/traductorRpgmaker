"""Extractor for RPG Maker VX (.rvdata files).

VX uses the same Ruby Marshal format and the same class fields as VX Ace, so
only the file extension differs.
"""
from __future__ import annotations

from extractors.rmvxace import VXAceExtractor


class VXExtractor(VXAceExtractor):
    EXT = ".rvdata"

    @property
    def version(self) -> str:
        return "VX"
