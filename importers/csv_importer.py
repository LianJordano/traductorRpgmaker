"""Import translations from a CSV file back into an ExtractionResult."""
from __future__ import annotations
import csv
from pathlib import Path

from core.models import ExtractionResult, TextEntry
from core import logger


def import_csv(csv_path: Path, result: ExtractionResult) -> int:
    """Merge translations from CSV into result. Returns count of updated entries."""
    uid_map: dict[str, TextEntry] = {e.uid: e for e in result.entries}
    updated = 0

    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            uid = row.get("uid", "").strip()
            translation = row.get("translation", "").strip()
            if uid in uid_map and translation:
                uid_map[uid].translation = translation
                uid_map[uid].status = "translated"
                updated += 1

    logger.success(f"Imported {updated} translations from CSV")
    return updated


def import_json(json_path: Path, result: ExtractionResult) -> int:
    """Import from a JSON file (same format as our JSON export)."""
    import json
    uid_map: dict[str, TextEntry] = {e.uid: e for e in result.entries}
    updated = 0

    data = json.loads(json_path.read_text(encoding="utf-8"))
    for entry_data in data.get("entries", []):
        uid = entry_data.get("uid", "")
        translation = entry_data.get("translation", "").strip()
        if uid in uid_map and translation:
            uid_map[uid].translation = translation
            uid_map[uid].status = "translated"
            updated += 1

    logger.success(f"Imported {updated} translations from JSON")
    return updated


def import_excel(xlsx_path: Path, result: ExtractionResult) -> int:
    """Import from an Excel file."""
    try:
        import openpyxl
    except ImportError:
        logger.error("openpyxl not installed for Excel import")
        return 0

    uid_map: dict[str, TextEntry] = {e.uid: e for e in result.entries}
    updated = 0

    wb = openpyxl.load_workbook(xlsx_path)
    ws = wb.active

    headers = [cell.value for cell in next(ws.iter_rows(min_row=1, max_row=1))]
    try:
        uid_col = headers.index("UID")
        trans_col = headers.index("Translation")
    except ValueError:
        logger.error("Excel file missing UID or Translation column")
        return 0

    for row in ws.iter_rows(min_row=2, values_only=True):
        uid = str(row[uid_col] or "").strip()
        translation = str(row[trans_col] or "").strip()
        if uid in uid_map and translation:
            uid_map[uid].translation = translation
            uid_map[uid].status = "translated"
            updated += 1

    logger.success(f"Imported {updated} translations from Excel")
    return updated
