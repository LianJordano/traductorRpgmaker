"""Export extraction results to CSV for manual translation."""
from __future__ import annotations
import csv
from pathlib import Path

from core.models import ExtractionResult
from exporters.base import BaseExporter

COLUMNS = ["uid", "file", "context", "original", "translation", "status"]


class CsvExporter(BaseExporter):
    def export(self, result: ExtractionResult, output_path: Path) -> Path:
        output_path = Path(output_path)
        if output_path.is_dir():
            output_path = output_path / "translation.csv"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with output_path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=COLUMNS)
            writer.writeheader()
            for entry in result.entries:
                writer.writerow({
                    "uid": entry.uid,
                    "file": entry.file,
                    "context": entry.context,
                    "original": entry.original,
                    "translation": entry.translation,
                    "status": entry.status,
                })
        return output_path
