"""Export extraction results to JSON."""
from __future__ import annotations
import json
from pathlib import Path

from core.models import ExtractionResult
from exporters.base import BaseExporter


class JsonExporter(BaseExporter):
    def export(self, result: ExtractionResult, output_path: Path) -> Path:
        output_path = Path(output_path)
        if output_path.is_dir():
            output_path = output_path / "translation.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(result.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return output_path
