"""Extractor for RPG Maker XP (.rxdata Ruby Marshal files)."""
from __future__ import annotations
from pathlib import Path
from typing import Any

from core import logger
from core.models import ExtractionResult, TextEntry
from extractors.base import BaseExtractor
from parsers import marshal_parser as mp

FILE_FIELDS: dict[str, list[str]] = {
    "Actors.rxdata":    ["name", "description"],
    "Armors.rxdata":    ["name", "description"],
    "Classes.rxdata":   ["name"],
    "Enemies.rxdata":   ["name"],
    "Items.rxdata":     ["name", "description"],
    "Skills.rxdata":    ["name", "description"],
    "States.rxdata":    ["name", "message1", "message2", "message3", "message4"],
    "Weapons.rxdata":   ["name", "description"],
    "Troops.rxdata":    ["name"],
    "System.rxdata":    ["game_title", "words"],
}

MAP_GLOB = "Map[0-9]*.rxdata"
COMMON_EVENTS_FILE = "CommonEvents.rxdata"


class XPExtractor(BaseExtractor):
    @property
    def version(self) -> str:
        return "XP"

    def extract(self) -> ExtractionResult:
        if not mp.is_available():
            return ExtractionResult(
                game_path=str(self.game_dir),
                version=self.version,
                errors=["rubymarshal library not installed. Run: pip install rubymarshal"],
            )

        result = ExtractionResult(game_path=str(self.game_dir), version=self.version)
        files = self._get_target_files()
        total = len(files)

        for idx, fpath in enumerate(files):
            if self._cancelled():
                break
            self._progress(idx, total, fpath.name)
            logger.info(f"Extracting: {fpath.name}")
            try:
                entries = self._extract_file(fpath)
                result.entries.extend(entries)
                logger.success(f"  → {len(entries)} texts from {fpath.name}")
            except Exception as exc:
                msg = f"Error in {fpath.name}: {exc}"
                logger.error(msg)
                result.errors.append(msg)

        self._progress(total, total, "Done")
        return result

    def reinsert(self, result: ExtractionResult) -> bool:
        logger.warning("XP reinsertion not fully implemented yet.")
        return False

    def _get_target_files(self) -> list[Path]:
        files = list(sorted(self.data_dir.glob(MAP_GLOB)))
        p = self.data_dir / COMMON_EVENTS_FILE
        if p.exists():
            files.append(p)
        for name in FILE_FIELDS:
            p = self.data_dir / name
            if p.exists():
                files.append(p)
        return files

    def _extract_file(self, fpath: Path) -> list[TextEntry]:
        name = fpath.name
        data = mp.load(fpath)
        if name.startswith("Map") and name[3].isdigit():
            return self._extract_map(data, name)
        if name == COMMON_EVENTS_FILE:
            return self._extract_array_events(data, name)
        if name in FILE_FIELDS:
            return self._extract_db(data, name, FILE_FIELDS[name])
        return []

    def _get(self, obj: Any, key: str, default: Any = None) -> Any:
        if isinstance(obj, dict):
            return obj.get(key, default)
        if hasattr(obj, "attributes"):
            return obj.attributes.get(key, default)
        return getattr(obj, key, default)

    def _extract_db(self, data: Any, filename: str, fields: list[str]) -> list[TextEntry]:
        entries = []
        items = data if isinstance(data, list) else []
        for obj in items:
            if obj is None:
                continue
            obj_id = self._get(obj, "id", "?")
            for field in fields:
                text = self._get(obj, field, "")
                if isinstance(text, str):
                    entry = self._make_entry(
                        filename, f"[{obj_id}].{field}", text, len(entries),
                        {"id": obj_id, "field": field},
                    )
                    if entry:
                        entries.append(entry)
        return entries

    def _extract_map(self, data: Any, filename: str) -> list[TextEntry]:
        entries = []
        events = self._get(data, "events", {})
        if isinstance(events, dict):
            for ev_id, event in events.items():
                pages = self._get(event, "pages", [])
                for pg_idx, page in enumerate(pages):
                    ev_list = self._get(page, "list", [])
                    entries.extend(
                        self._extract_event_list(
                            ev_list, filename, f"event[{ev_id}].page[{pg_idx}]"
                        )
                    )
        return entries

    def _extract_array_events(self, data: Any, filename: str) -> list[TextEntry]:
        entries = []
        items = data if isinstance(data, list) else []
        for obj in items:
            if obj is None:
                continue
            ev_id = self._get(obj, "id", "?")
            ev_list = self._get(obj, "list", [])
            entries.extend(
                self._extract_event_list(ev_list, filename, f"event[{ev_id}]")
            )
        return entries

    def _extract_event_list(
        self, cmd_list: Any, filename: str, ctx_prefix: str
    ) -> list[TextEntry]:
        entries = []
        if not isinstance(cmd_list, list):
            return entries
        i = 0
        block_idx = 0
        while i < len(cmd_list):
            cmd = cmd_list[i]
            code = self._get(cmd, "code", 0)
            params = self._get(cmd, "parameters", []) or []

            if code == 101:
                # In XP, code 101 has the text directly in parameters[0]
                text = str(params[0]) if params else ""
                lines = [text] if text else []
                j = i + 1
                while j < len(cmd_list):
                    nc = cmd_list[j]
                    if self._get(nc, "code", 0) == 401:
                        nc_params = self._get(nc, "parameters", []) or []
                        lines.append(str(nc_params[0]) if nc_params else "")
                        j += 1
                    else:
                        break
                full = "\n".join(l for l in lines if l)
                if full:
                    entry = self._make_entry(
                        filename, f"{ctx_prefix}.dialogue[{block_idx}]",
                        full, block_idx,
                        {"type": "dialogue", "block_start": i, "line_count": len(lines)},
                    )
                    if entry:
                        entries.append(entry)
                    block_idx += 1
                i = j
                continue

            elif code == 102 and params:
                choices = params[0] if params else []
                if isinstance(choices, list):
                    for c_idx, choice in enumerate(choices):
                        if isinstance(choice, str):
                            entry = self._make_entry(
                                filename,
                                f"{ctx_prefix}.choice[{block_idx}][{c_idx}]",
                                choice, block_idx * 100 + c_idx,
                                {"type": "choice", "cmd_index": i, "choice_index": c_idx},
                            )
                            if entry:
                                entries.append(entry)
                    block_idx += 1

            i += 1
        return entries
