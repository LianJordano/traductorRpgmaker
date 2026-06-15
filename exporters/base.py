from __future__ import annotations
from abc import ABC, abstractmethod
from pathlib import Path
from core.models import ExtractionResult


class BaseExporter(ABC):
    @abstractmethod
    def export(self, result: ExtractionResult, output_path: Path) -> Path:
        """Export entries to a file and return the output path."""
        ...
