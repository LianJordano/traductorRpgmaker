"""Extractor for RPG Maker VX Ace (.rvdata2 Ruby Marshal files)."""
from __future__ import annotations
from pathlib import Path
from typing import Any, Optional

from core import logger
from core.models import ExtractionResult, TextEntry
from extractors.base import BaseExtractor
from parsers import marshal_parser as mp

# Chunk IDs for LCF-style
TEXT_COMMAND_CODES = {101, 401, 102, 405}

# Files and their attribute names in Ruby classes
FILE_FIELDS: dict[str, list[str]] = {
    "Actors.rvdata2":   ["name", "nickname", "description", "note"],
    "Armors.rvdata2":   ["name", "description", "note"],
    "Classes.rvdata2":  ["name", "note"],
    "Enemies.rvdata2":  ["name", "note"],
    "Items.rvdata2":    ["name", "description", "note"],
    "Skills.rvdata2":   ["name", "description", "message1", "message2", "note"],
    "States.rvdata2":   ["name", "note", "message1", "message2", "message3", "message4"],
    "Weapons.rvdata2":  ["name", "description", "note"],
    "Troops.rvdata2":   ["name"],
    "System.rvdata2":   ["game_title", "currency_unit"],
}

MAP_GLOB = "Map[0-9]*.rvdata2"
COMMON_EVENTS_FILE = "CommonEvents.rvdata2"


class VXAceExtractor(BaseExtractor):
    @property
    def version(self) -> str:
        return "VXAce"

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
        if not mp.is_available():
            logger.error("rubymarshal not available for reinsertion")
            return False

        by_file: dict[str, list[TextEntry]] = {}
        for entry in result.entries:
            if entry.status == "translated" and entry.translation:
                by_file.setdefault(entry.file, []).append(entry)

        success = True
        for filename, entries in by_file.items():
            fpath = self.data_dir / filename
            if not fpath.exists():
                continue
            try:
                data = mp.load(fpath)
                self._reinsert_into(data, entries, filename)
                mp.save(fpath, data)
                logger.success(f"Reinserted {len(entries)} into {filename}")
            except Exception as exc:
                logger.error(f"Reinsertion failed for {filename}: {exc}")
                success = False
        return success

    def _get_target_files(self) -> list[Path]:
        files = []
        files.extend(sorted(self.data_dir.glob(MAP_GLOB)))
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
            return self._extract_common_events(data, name)
        if name in FILE_FIELDS:
            return self._extract_database_file(data, name, FILE_FIELDS[name])
        return []

    def _extract_database_file(
        self, data: Any, filename: str, fields: list[str]
    ) -> list[TextEntry]:
        entries = []
        if not isinstance(data, list):
            return entries
        for obj in data:
            if obj is None:
                continue
            obj_id = self._get_attr(obj, "id", "?")
            for field in fields:
                text = self._get_attr(obj, field, "")
                if not isinstance(text, str):
                    continue
                entry = self._make_entry(
                    filename, f"[{obj_id}].{field}", text, len(entries),
                    {"id": obj_id, "field": field},
                )
                if entry:
                    entries.append(entry)
        return entries

    def _extract_map(self, data: Any, filename: str) -> list[TextEntry]:
        entries = []
        display = self._get_attr(data, "display_name", "")
        if display:
            entry = self._make_entry(
                filename, "display_name", display, 0, {"field": "display_name"}
            )
            if entry:
                entries.append(entry)
        events = self._get_attr(data, "events", {})
        if isinstance(events, dict):
            for ev_id, event in events.items():
                pages = self._get_attr(event, "pages", [])
                for pg_idx, page in enumerate(pages):
                    ev_list = self._get_attr(page, "list", [])
                    entries.extend(
                        self._extract_event_list(
                            ev_list, filename, f"event[{ev_id}].page[{pg_idx}]"
                        )
                    )
        return entries

    def _extract_common_events(self, data: Any, filename: str) -> list[TextEntry]:
        entries = []
        if not isinstance(data, list):
            return entries
        for obj in data:
            if obj is None:
                continue
            ev_id = self._get_attr(obj, "id", "?")
            ev_list = self._get_attr(obj, "list", [])
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
            code = self._get_attr(cmd, "code", 0)
            params = self._get_attr(cmd, "parameters", [])
            if not isinstance(params, list):
                params = []

            if code == 101:
                lines = []
                j = i + 1
                while j < len(cmd_list):
                    nc = cmd_list[j]
                    nc_code = self._get_attr(nc, "code", 0)
                    nc_params = self._get_attr(nc, "parameters", [])
                    if nc_code == 401 and nc_params:
                        lines.append(str(nc_params[0]))
                        j += 1
                    else:
                        break
                text = "\n".join(lines)
                if text:
                    entry = self._make_entry(
                        filename, f"{ctx_prefix}.dialogue[{block_idx}]", text,
                        block_idx,
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

    def _get_attr(self, obj: Any, name: str, default: Any = None) -> Any:
        if obj is None:
            return default
        if isinstance(obj, dict):
            return obj.get(name, default)
        if hasattr(obj, "attributes"):
            return obj.attributes.get(name, default)
        return getattr(obj, name, default)

    def _reinsert_into(
        self, data: Any, entries: list[TextEntry], filename: str
    ) -> None:
        entry_map = {e.uid: e for e in entries}
        # Use stem (name without extension) so VX (.rvdata) and VXAce (.rvdata2) both work
        stem = Path(filename).stem
        if stem.startswith("Map") and len(stem) > 3 and stem[3].isdigit():
            self._ri_map(data, entry_map)
        elif stem == "CommonEvents":
            self._ri_common_events(data, entry_map)
        elif entry_map:
            self._ri_database(data, entry_map)

    def _ri_database(self, data: Any, entry_map: dict) -> None:
        if not isinstance(data, list):
            return
        # Group entries by obj_id for efficiency
        by_id: dict = {}
        for e in entry_map.values():
            oid = e.metadata.get("id")
            if oid is not None:
                by_id.setdefault(oid, []).append(e)
        for obj in data:
            if obj is None:
                continue
            obj_id = self._get_attr(obj, "id", None)
            for entry in by_id.get(obj_id, []):
                field = entry.metadata.get("field", "")
                if field:
                    mp.set_ivar(obj, field, entry.translation)

    def _ri_map(self, data: Any, entry_map: dict) -> None:
        for entry in entry_map.values():
            if entry.metadata.get("field") == "display_name":
                mp.set_ivar(data, "display_name", entry.translation)
                break
        events = self._get_attr(data, "events", {}) or {}
        if isinstance(events, dict):
            for ev_id, event in events.items():
                pages = self._get_attr(event, "pages", []) or []
                for pg_idx, page in enumerate(pages):
                    ctx = f"event[{ev_id}].page[{pg_idx}]"
                    ev_list = self._get_attr(page, "list", []) or []
                    self._ri_event_list(ev_list, entry_map, ctx)

    def _ri_common_events(self, data: Any, entry_map: dict) -> None:
        if not isinstance(data, list):
            return
        for obj in data:
            if obj is None:
                continue
            ev_id = self._get_attr(obj, "id", "?")
            ctx = f"event[{ev_id}]"
            ev_list = self._get_attr(obj, "list", []) or []
            self._ri_event_list(ev_list, entry_map, ctx)

    def _ri_event_list(self, cmd_list: Any, entry_map: dict, ctx_prefix: str) -> None:
        if not isinstance(cmd_list, list):
            return
        relevant = {uid: e for uid, e in entry_map.items()
                    if e.context.startswith(ctx_prefix + ".")}
        if not relevant:
            return
        i = 0
        while i < len(cmd_list):
            cmd = cmd_list[i]
            code = self._get_attr(cmd, "code", 0)

            if code == 101:
                for entry in relevant.values():
                    meta = entry.metadata
                    if meta.get("type") == "dialogue" and meta.get("block_start") == i:
                        lines = entry.translation.split("\n")
                        j = i + 1
                        k = 0
                        while j < len(cmd_list):
                            nc = cmd_list[j]
                            if self._get_attr(nc, "code", 0) == 401:
                                params = self._get_attr(nc, "parameters", []) or []
                                if isinstance(params, list):
                                    params[0] = lines[k] if k < len(lines) else ""
                                    mp.set_ivar(nc, "parameters", params)
                                k += 1
                                j += 1
                            else:
                                break
                        break

            elif code == 102:
                for entry in relevant.values():
                    meta = entry.metadata
                    if meta.get("type") == "choice" and meta.get("cmd_index") == i:
                        c_idx = meta.get("choice_index", 0)
                        params = self._get_attr(cmd, "parameters", []) or []
                        if isinstance(params, list) and len(params) > 0:
                            choices = params[0]
                            if isinstance(choices, list) and c_idx < len(choices):
                                choices[c_idx] = entry.translation
                                mp.set_ivar(cmd, "parameters", params)

            i += 1
