"""Extractor for RPG Maker MV and MZ (JSON-based games)."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Callable, Optional

from core import logger
from core.models import ExtractionResult, TextEntry
from extractors.base import BaseExtractor
from parsers.json_parser import load as json_load, save as json_save
from validators.text_filter import is_translatable

# Command codes that contain translatable text
TEXT_COMMANDS = {101, 401, 102, 405}
CHOICE_COMMAND = 102
SCROLL_TEXT = 405

# JSON files and their translatable fields
SIMPLE_FILES: dict[str, list[str]] = {
    "Actors.json":    ["name", "nickname", "profile", "note"],
    "Armors.json":    ["name", "description", "note"],
    "Classes.json":   ["name", "note"],
    "Enemies.json":   ["name", "note"],
    "Items.json":     ["name", "description", "note"],
    "Skills.json":    ["name", "description", "message1", "message2", "note"],
    "States.json":    ["name", "note", "message1", "message2", "message3", "message4"],
    "Weapons.json":   ["name", "description", "note"],
    "Tilesets.json":  ["name", "note"],
    "CommonEvents.json": [],  # handled separately via event list
    "Troops.json":    ["name"],
}

SYSTEM_FIELDS = [
    "gameTitle", "currencyUnit",
    # Terms
    "terms.basic", "terms.params", "terms.commands", "terms.messages",
    "skillTypes", "weaponTypes", "armorTypes", "equipTypes",
]


class MvMzExtractor(BaseExtractor):
    @property
    def version(self) -> str:
        return "MV/MZ"

    def extract(self) -> ExtractionResult:
        result = ExtractionResult(
            game_path=str(self.game_dir),
            version=self.version,
        )
        files = self._get_target_files()
        total = len(files)

        for idx, fpath in enumerate(files):
            if self._cancelled():
                logger.info("Extraction cancelled.")
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
        self._result = result
        return result

    def reinsert(self, result: ExtractionResult) -> bool:
        """Write translated texts back into the JSON files."""
        # Group entries by file
        by_file: dict[str, list[TextEntry]] = {}
        for entry in result.entries:
            if entry.status == "translated" and entry.translation:
                by_file.setdefault(entry.file, []).append(entry)

        success = True
        total_files = len(by_file)
        for idx, (filename, entries) in enumerate(by_file.items()):
            if self._cancelled():
                logger.info("Reinsertion cancelled.")
                break
            self._progress(idx, total_files, filename)
            fpath = self.data_dir / filename
            if not fpath.exists():
                logger.warning(f"File not found for reinsertion: {filename}")
                continue
            try:
                data = json_load(fpath)
                data = self._reinsert_into_data(data, entries, filename)
                json_save(fpath, data)
                logger.success(f"Reinserted {len(entries)} texts into {filename}")
            except Exception as exc:
                logger.error(f"Reinsertion failed for {filename}: {exc}")
                success = False
        self._progress(total_files, total_files, "Done")
        return success

    # ---- private helpers ----

    def _get_target_files(self) -> list[Path]:
        files = []
        # Map files
        files.extend(sorted(self.data_dir.glob("Map[0-9]*.json")))
        # Known data files
        for name in SIMPLE_FILES:
            p = self.data_dir / name
            if p.exists():
                files.append(p)
        # System
        sys_path = self.data_dir / "System.json"
        if sys_path.exists():
            files.append(sys_path)
        return files

    def _extract_file(self, fpath: Path) -> list[TextEntry]:
        name = fpath.name
        data = json_load(fpath)

        if name.startswith("Map") and name[3].isdigit():
            return self._extract_map(data, name)
        if name == "System.json":
            return self._extract_system(data, name)
        if name == "CommonEvents.json":
            return self._extract_common_events(data, name)
        if name == "Troops.json":
            return self._extract_troops(data, name)
        if name in SIMPLE_FILES:
            return self._extract_simple(data, name, SIMPLE_FILES[name])
        return []

    def _extract_simple(
        self, data: Any, filename: str, fields: list[str]
    ) -> list[TextEntry]:
        entries = []
        if not isinstance(data, list):
            return entries
        for obj in data:
            if not isinstance(obj, dict):
                continue
            obj_id = obj.get("id", "?")
            for field in fields:
                text = obj.get(field, "")
                if not isinstance(text, str):
                    continue
                entry = self._make_entry(
                    filename,
                    f"[{obj_id}].{field}",
                    text,
                    len(entries),
                    {"id": obj_id, "field": field},
                )
                if entry:
                    entries.append(entry)
        return entries

    def _extract_system(self, data: Any, filename: str) -> list[TextEntry]:
        entries = []
        if not isinstance(data, dict):
            return entries

        def add(path: str, text: str) -> None:
            entry = self._make_entry(filename, path, text, len(entries), {"path": path})
            if entry:
                entries.append(entry)

        title = data.get("gameTitle", "")
        if title:
            add("gameTitle", title)

        currency = data.get("currencyUnit", "")
        if currency:
            add("currencyUnit", currency)

        terms = data.get("terms") or data.get("words") or {}
        if isinstance(terms, dict):
            for section, values in terms.items():
                if isinstance(values, list):
                    for i, v in enumerate(values):
                        if isinstance(v, str):
                            add(f"terms.{section}[{i}]", v)
                elif isinstance(values, str):
                    add(f"terms.{section}", values)
                elif isinstance(values, dict):
                    # e.g. terms.messages: {"alwaysDash": "Always Dash", ...}
                    for key, v in values.items():
                        if isinstance(v, str):
                            add(f"terms.{section}.{key}", v)

        for list_key in ("skillTypes", "weaponTypes", "armorTypes", "equipTypes"):
            lst = data.get(list_key, [])
            if isinstance(lst, list):
                for i, v in enumerate(lst):
                    if isinstance(v, str):
                        add(f"{list_key}[{i}]", v)

        return entries

    def _extract_map(self, data: Any, filename: str) -> list[TextEntry]:
        entries = []
        if not isinstance(data, dict):
            return entries
        display_name = data.get("displayName", "")
        if display_name:
            entry = self._make_entry(
                filename, "displayName", display_name, 0, {"field": "displayName"}
            )
            if entry:
                entries.append(entry)
        events = data.get("events", {})
        if isinstance(events, dict):
            for ev_id, event in events.items():
                if not isinstance(event, dict):
                    continue
                pages = event.get("pages", [])
                for pg_idx, page in enumerate(pages):
                    ev_entries = self._extract_event_list(
                        page.get("list", []),
                        filename,
                        f"event[{ev_id}].page[{pg_idx}]",
                    )
                    entries.extend(ev_entries)
        elif isinstance(events, list):
            for event in events:
                if not isinstance(event, dict):
                    continue
                pages = event.get("pages", [])
                ev_id = event.get("id", "?")
                for pg_idx, page in enumerate(pages):
                    ev_entries = self._extract_event_list(
                        page.get("list", []),
                        filename,
                        f"event[{ev_id}].page[{pg_idx}]",
                    )
                    entries.extend(ev_entries)
        return entries

    def _extract_common_events(self, data: Any, filename: str) -> list[TextEntry]:
        entries = []
        if not isinstance(data, list):
            return entries
        for obj in data:
            if not isinstance(obj, dict):
                continue
            ev_id = obj.get("id", "?")
            ev_list = obj.get("list", [])
            entries.extend(
                self._extract_event_list(ev_list, filename, f"event[{ev_id}]")
            )
        return entries

    def _extract_troops(self, data: Any, filename: str) -> list[TextEntry]:
        entries = []
        if not isinstance(data, list):
            return entries
        for obj in data:
            if not isinstance(obj, dict):
                continue
            troop_id = obj.get("id", "?")
            name = obj.get("name", "")
            entry = self._make_entry(
                filename, f"troop[{troop_id}].name", name, len(entries),
                {"id": troop_id, "field": "name"},
            )
            if entry:
                entries.append(entry)
            pages = obj.get("pages", [])
            for pg_idx, page in enumerate(pages):
                entries.extend(
                    self._extract_event_list(
                        page.get("list", []),
                        filename,
                        f"troop[{troop_id}].page[{pg_idx}]",
                    )
                )
        return entries

    def _extract_event_list(
        self, cmd_list: list, filename: str, context_prefix: str
    ) -> list[TextEntry]:
        """Parse RPG Maker event command list and extract dialogue/choices."""
        entries: list[TextEntry] = []
        if not isinstance(cmd_list, list):
            return entries

        i = 0
        block_idx = 0
        while i < len(cmd_list):
            cmd = cmd_list[i]
            if not isinstance(cmd, dict):
                i += 1
                continue
            code = cmd.get("code", 0)
            params = cmd.get("parameters", [])

            if code == 101:
                # Start of text block — collect all following 401 lines
                lines = []
                j = i + 1
                while j < len(cmd_list):
                    next_cmd = cmd_list[j]
                    if isinstance(next_cmd, dict) and next_cmd.get("code") == 401:
                        lines.append(next_cmd["parameters"][0] if next_cmd.get("parameters") else "")
                        j += 1
                    else:
                        break
                full_text = "\n".join(lines)
                if full_text:
                    ctx = f"{context_prefix}.dialogue[{block_idx}]"
                    meta = {
                        "type": "dialogue",
                        "block_start": i,
                        "line_count": len(lines),
                        "header_params": params,
                    }
                    entry = self._make_entry(filename, ctx, full_text, block_idx, meta)
                    if entry:
                        entries.append(entry)
                    block_idx += 1
                i = j
                continue

            elif code == 102:
                # Show Choices
                choices = params[0] if params else []
                if isinstance(choices, list):
                    for c_idx, choice in enumerate(choices):
                        if isinstance(choice, str):
                            ctx = f"{context_prefix}.choice[{block_idx}][{c_idx}]"
                            entry = self._make_entry(
                                filename, ctx, choice, block_idx * 100 + c_idx,
                                {"type": "choice", "cmd_index": i, "choice_index": c_idx},
                            )
                            if entry:
                                entries.append(entry)
                    block_idx += 1

            elif code == 405:
                # Scroll text line (standalone)
                text = params[0] if params else ""
                if isinstance(text, str):
                    ctx = f"{context_prefix}.scroll[{block_idx}]"
                    entry = self._make_entry(
                        filename, ctx, text, block_idx,
                        {"type": "scroll", "cmd_index": i},
                    )
                    if entry:
                        entries.append(entry)
                    block_idx += 1

            i += 1
        return entries

    def _reinsert_into_data(
        self, data: Any, entries: list[TextEntry], filename: str
    ) -> Any:
        """Apply translated entries back to parsed JSON data."""
        entry_map: dict[str, TextEntry] = {e.uid: e for e in entries}

        if filename.startswith("Map") and filename[3].isdigit():
            return self._reinsert_map(data, entry_map, filename)
        if filename == "System.json":
            return self._reinsert_system(data, entry_map, filename)
        if filename in ("CommonEvents.json", "Troops.json"):
            return self._reinsert_list_with_events(data, entry_map, filename)
        return self._reinsert_simple(data, entry_map, filename)

    def _reinsert_simple(
        self, data: Any, entry_map: dict, filename: str
    ) -> Any:
        if not isinstance(data, list):
            return data
        fields = SIMPLE_FILES.get(filename, [])
        # Index entries by (id, field) once so lookups are O(1) instead of
        # rescanning the whole entry list for every object/field.
        by_id_field: dict = {}
        for entry in entry_map.values():
            key = (entry.metadata.get("id"), entry.metadata.get("field"))
            by_id_field[key] = entry
        for obj in data:
            if not isinstance(obj, dict):
                continue
            obj_id = obj.get("id", "?")
            for field in fields:
                entry = by_id_field.get((obj_id, field))
                if entry is not None:
                    obj[field] = entry.translation
        return data

    def _reinsert_system(self, data: Any, entry_map: dict, filename: str) -> Any:
        if not isinstance(data, dict):
            return data
        for entry in entry_map.values():
            path = entry.metadata.get("path", "")
            if path == "gameTitle":
                data["gameTitle"] = entry.translation
            elif path == "currencyUnit":
                data["currencyUnit"] = entry.translation
            elif path.startswith("terms."):
                self._set_nested(data, path, entry.translation)
            elif "[" in path:
                self._set_nested(data, path, entry.translation)
        return data

    def _set_nested(self, data: dict, path: str, value: str) -> None:
        """Set a dot-notated path with optional array index like terms.basic[0]."""
        import re
        parts = re.split(r"\.", path)
        obj = data
        for i, part in enumerate(parts[:-1]):
            m = re.match(r"(\w+)\[(\d+)\]", part)
            if m:
                key, idx = m.group(1), int(m.group(2))
                if isinstance(obj, dict):
                    obj = obj.get(key, {})
                if isinstance(obj, list) and idx < len(obj):
                    obj = obj[idx]
            else:
                if isinstance(obj, dict):
                    obj = obj.get(part, {})
        last = parts[-1]
        m = re.match(r"(\w+)\[(\d+)\]", last)
        if m:
            key, idx = m.group(1), int(m.group(2))
            if isinstance(obj, dict) and key in obj and isinstance(obj[key], list):
                if idx < len(obj[key]):
                    obj[key][idx] = value
        else:
            if isinstance(obj, dict):
                obj[last] = value

    def _group_by_prefix(self, entry_map: dict) -> dict:
        """Group entries by their context prefix (everything before the final
        `.dialogue[..]` / `.choice[..]` / `.scroll[..]` segment) so each event
        list can fetch its entries in O(1) instead of rescanning every entry."""
        by_prefix: dict[str, list] = {}
        for entry in entry_map.values():
            prefix = entry.context.rsplit(".", 1)[0]
            by_prefix.setdefault(prefix, []).append(entry)
        return by_prefix

    def _reinsert_map(self, data: Any, entry_map: dict, filename: str) -> Any:
        if not isinstance(data, dict):
            return data
        by_prefix = self._group_by_prefix(entry_map)
        # displayName
        for entry in entry_map.values():
            if entry.metadata.get("field") == "displayName":
                data["displayName"] = entry.translation

        events = data.get("events", {})
        if isinstance(events, dict):
            for ev_id, event in events.items():
                if isinstance(event, dict):
                    for pg_idx, page in enumerate(event.get("pages", [])):
                        ctx = f"event[{ev_id}].page[{pg_idx}]"
                        self._reinsert_event_list(page.get("list", []), by_prefix.get(ctx, []))
        elif isinstance(events, list):
            for event in events:
                if isinstance(event, dict):
                    ev_id = event.get("id", "?")
                    for pg_idx, page in enumerate(event.get("pages", [])):
                        ctx = f"event[{ev_id}].page[{pg_idx}]"
                        self._reinsert_event_list(page.get("list", []), by_prefix.get(ctx, []))
        return data

    def _reinsert_list_with_events(
        self, data: Any, entry_map: dict, filename: str
    ) -> Any:
        if not isinstance(data, list):
            return data
        by_prefix = self._group_by_prefix(entry_map)
        # Index name entries by object id for O(1) lookup
        names_by_id: dict = {}
        for entry in entry_map.values():
            if entry.metadata.get("field") == "name":
                names_by_id[entry.metadata.get("id")] = entry
        for obj in data:
            if not isinstance(obj, dict):
                continue
            obj_id = obj.get("id")
            name_entry = names_by_id.get(obj_id)
            if name_entry is not None:
                obj["name"] = name_entry.translation
            # CommonEvents.json: top-level list per event
            if "list" in obj:
                ctx = f"event[{obj_id}]"
                self._reinsert_event_list(obj.get("list") or [], by_prefix.get(ctx, []))
            # Troops.json: pages with lists
            for pg_idx, page in enumerate(obj.get("pages", [])):
                ctx = f"troop[{obj_id}].page[{pg_idx}]"
                self._reinsert_event_list(page.get("list", []), by_prefix.get(ctx, []))
        return data

    def _reinsert_event_list(self, cmd_list: list, entries: list) -> None:
        """Apply translations back into an event command list (in-place).

        `entries` are already scoped to this event/page. They are indexed by
        command position so the command list is walked only once (O(n))."""
        if not entries:
            return

        dialogue_by_start: dict = {}
        choice_by_cmd: dict = {}
        scroll_by_cmd: dict = {}
        for entry in entries:
            meta = entry.metadata
            etype = meta.get("type")
            if etype == "dialogue":
                dialogue_by_start[meta.get("block_start")] = entry
            elif etype == "choice":
                choice_by_cmd.setdefault(meta.get("cmd_index"), []).append(entry)
            elif etype == "scroll":
                scroll_by_cmd[meta.get("cmd_index")] = entry

        i = 0
        n = len(cmd_list)
        while i < n:
            cmd = cmd_list[i]
            if not isinstance(cmd, dict):
                i += 1
                continue
            code = cmd.get("code", 0)

            if code == 101:
                entry = dialogue_by_start.get(i)
                if entry is not None:
                    lines = entry.translation.split("\n")
                    # Collect all consecutive 401 commands
                    orig_401: list = []
                    j = i + 1
                    while j < n:
                        nc = cmd_list[j]
                        if isinstance(nc, dict) and nc.get("code") == 401:
                            orig_401.append(nc)
                            j += 1
                        else:
                            break
                    # Write lines back; blank out any 401 entries beyond the translation
                    for k, nc in enumerate(orig_401):
                        if nc.get("parameters"):
                            nc["parameters"][0] = lines[k] if k < len(lines) else ""

            elif code == 102:
                for entry in choice_by_cmd.get(i, []):
                    c_idx = entry.metadata.get("choice_index", 0)
                    params = cmd.get("parameters", [])
                    if params and isinstance(params[0], list) and c_idx < len(params[0]):
                        params[0][c_idx] = entry.translation

            elif code == 405:
                entry = scroll_by_cmd.get(i)
                if entry is not None and cmd.get("parameters"):
                    cmd["parameters"][0] = entry.translation

            i += 1
