"""Extractor for RPG Maker MV and MZ (JSON-based games)."""
from __future__ import annotations
import re
from pathlib import Path
from typing import Any

from core import config, logger
from core.models import ExtractionResult, TextEntry
from extractors.base import BaseExtractor
from parsers.json_parser import load as json_load, save as json_save
from utils.text_utils import layout_message

# --- Event command codes -----------------------------------------------------
CODE_SHOW_TEXT = 101        # [faceName, faceIndex, background, position, speaker?]
CODE_TEXT_LINE = 401
CODE_SHOW_CHOICES = 102     # parameters[0] is the list of choice labels
CODE_CHOICE_BRANCH = 402    # [index, label]
CODE_SCROLL_TEXT = 105      # header of a scrolling-text block
CODE_SCROLL_LINE = 405
CODE_CHANGE_NAME = 320      # [actorId, name]
CODE_CHANGE_NICKNAME = 324
CODE_CHANGE_PROFILE = 325

NAME_COMMANDS = {CODE_CHANGE_NAME, CODE_CHANGE_NICKNAME, CODE_CHANGE_PROFILE}
#: MZ added a speaker-name box; the name lives in parameters[4] of code 101.
SPEAKER_PARAM = 4

# JSON files and their translatable fields
SIMPLE_FILES: dict[str, list[str]] = {
    "Actors.json":    ["name", "nickname", "profile"],
    "Armors.json":    ["name", "description"],
    "Classes.json":   ["name"],
    "Enemies.json":   ["name"],
    "Items.json":     ["name", "description"],
    "Skills.json":    ["name", "description", "message1", "message2"],
    "States.json":    ["name", "message1", "message2", "message3", "message4"],
    "Weapons.json":   ["name", "description"],
    "Tilesets.json":  ["name"],
    "CommonEvents.json": [],  # handled separately via event list
    "Troops.json":    ["name"],
}

# `note` is what plugins parse for their notetags; translating it silently
# breaks them, so it is opt-in through the `translate_notes` setting.
NOTE_FIELD = "note"

SYSTEM_LIST_FIELDS = ("skillTypes", "weaponTypes", "armorTypes", "equipTypes")


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
            original_bytes = fpath.read_bytes()
            try:
                data = json_load(fpath)
                data = self._reinsert_into_data(data, entries, filename)
                json_save(fpath, data)
                # Verify the game can still read what we just wrote.
                json_load(fpath)
                logger.success(f"Reinserted {len(entries)} texts into {filename}")
            except Exception as exc:
                logger.error(f"Reinsertion failed for {filename}: {exc}")
                try:
                    fpath.write_bytes(original_bytes)
                    logger.warning(f"Restored original {filename} (left untranslated).")
                except Exception as restore_exc:
                    logger.error(f"Could not restore {filename}: {restore_exc}")
                success = False
        self._progress(total_files, total_files, "Done")
        return success

    # ---- private helpers ----

    def _fields_for(self, filename: str) -> list[str]:
        fields = list(SIMPLE_FILES.get(filename, []))
        if fields and config.get("translate_notes"):
            fields.append(NOTE_FIELD)
        return fields

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
            return self._extract_simple(data, name, self._fields_for(name))
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

        for list_key in SYSTEM_LIST_FIELDS:
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
        for ev_id, event in self._iter_events(data.get("events")):
            pages = event.get("pages", [])
            for pg_idx, page in enumerate(pages):
                if not isinstance(page, dict):
                    continue
                entries.extend(self._extract_event_list(
                    page.get("list", []), filename, f"event[{ev_id}].page[{pg_idx}]"
                ))
        return entries

    @staticmethod
    def _iter_events(events: Any):
        """Yield (id, event) for both the dict and list shapes MV/MZ maps use."""
        if isinstance(events, dict):
            for ev_id, event in events.items():
                if isinstance(event, dict):
                    yield ev_id, event
        elif isinstance(events, list):
            for event in events:
                if isinstance(event, dict):
                    yield event.get("id", "?"), event

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
                if not isinstance(page, dict):
                    continue
                entries.extend(
                    self._extract_event_list(
                        page.get("list", []),
                        filename,
                        f"troop[{troop_id}].page[{pg_idx}]",
                    )
                )
        return entries

    # -- event command lists -------------------------------------------------

    @staticmethod
    def _collect_block(cmd_list: list, start: int, line_code: int) -> tuple[list[str], int]:
        """Collect the text lines of the block starting at `start`."""
        lines: list[str] = []
        j = start + 1
        n = len(cmd_list)
        while j < n:
            cmd = cmd_list[j]
            if not isinstance(cmd, dict) or cmd.get("code") != line_code:
                break
            params = cmd.get("parameters") or []
            lines.append(params[0] if params and isinstance(params[0], str) else "")
            j += 1
        return lines, j

    def _extract_event_list(
        self, cmd_list: list, filename: str, context_prefix: str
    ) -> list[TextEntry]:
        """Parse an RPG Maker event command list and extract every visible text."""
        entries: list[TextEntry] = []
        if not isinstance(cmd_list, list):
            return entries

        i = 0
        block_idx = 0
        n = len(cmd_list)
        while i < n:
            cmd = cmd_list[i]
            if not isinstance(cmd, dict):
                i += 1
                continue
            code = cmd.get("code", 0)
            params = cmd.get("parameters", []) or []

            if code == CODE_SHOW_TEXT:
                # MZ keeps the speaker-name box in parameters[4].
                if len(params) > SPEAKER_PARAM and isinstance(params[SPEAKER_PARAM], str):
                    entry = self._make_entry(
                        filename, f"{context_prefix}.speaker[{i}]",
                        params[SPEAKER_PARAM], i,
                        {"type": "param", "cmd_index": i, "param_index": SPEAKER_PARAM},
                    )
                    if entry:
                        entries.append(entry)
                lines, j = self._collect_block(cmd_list, i, CODE_TEXT_LINE)
                full_text = "\n".join(lines)
                if full_text.strip():
                    entry = self._make_entry(
                        filename, f"{context_prefix}.dialogue[{block_idx}]",
                        full_text, block_idx,
                        {"type": "dialogue", "block_start": i, "line_count": len(lines)},
                    )
                    if entry:
                        entries.append(entry)
                    block_idx += 1
                i = j
                continue

            if code == CODE_SCROLL_TEXT:
                lines, j = self._collect_block(cmd_list, i, CODE_SCROLL_LINE)
                full_text = "\n".join(lines)
                if full_text.strip():
                    entry = self._make_entry(
                        filename, f"{context_prefix}.scroll[{block_idx}]",
                        full_text, block_idx,
                        {"type": "scroll", "block_start": i, "line_count": len(lines)},
                    )
                    if entry:
                        entries.append(entry)
                    block_idx += 1
                i = j
                continue

            if code == CODE_SHOW_CHOICES:
                choices = params[0] if params else []
                if isinstance(choices, list):
                    for c_idx, choice in enumerate(choices):
                        if isinstance(choice, str):
                            entry = self._make_entry(
                                filename,
                                f"{context_prefix}.choice[{block_idx}][{c_idx}]",
                                choice, block_idx * 1000 + c_idx,
                                {"type": "choice", "cmd_index": i, "choice_index": c_idx},
                            )
                            if entry:
                                entries.append(entry)
                    block_idx += 1

            elif code == CODE_CHOICE_BRANCH and len(params) > 1 and isinstance(params[1], str):
                entry = self._make_entry(
                    filename, f"{context_prefix}.branch[{i}]", params[1], i,
                    {"type": "param", "cmd_index": i, "param_index": 1},
                )
                if entry:
                    entries.append(entry)

            elif code in NAME_COMMANDS and len(params) > 1 and isinstance(params[1], str):
                entry = self._make_entry(
                    filename, f"{context_prefix}.name[{i}]", params[1], i,
                    {"type": "param", "cmd_index": i, "param_index": 1},
                )
                if entry:
                    entries.append(entry)

            i += 1
        return entries

    # -- reinsertion ---------------------------------------------------------

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

    def _reinsert_simple(self, data: Any, entry_map: dict, filename: str) -> Any:
        if not isinstance(data, list):
            return data
        fields = self._fields_for(filename)
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
            elif path:
                self._set_nested(data, path, entry.translation)
        return data

    def _set_nested(self, data: dict, path: str, value: str) -> None:
        """Set a dot-notated path with optional array index like terms.basic[0]."""
        parts = path.split(".")
        obj: Any = data
        for part in parts[:-1]:
            m = re.fullmatch(r"(\w+)\[(\d+)\]", part)
            if m:
                key, idx = m.group(1), int(m.group(2))
                if not isinstance(obj, dict) or not isinstance(obj.get(key), list):
                    return
                obj = obj[key]
                if idx >= len(obj):
                    return
                obj = obj[idx]
            else:
                if not isinstance(obj, dict) or part not in obj:
                    return
                obj = obj[part]
        last = parts[-1]
        m = re.fullmatch(r"(\w+)\[(\d+)\]", last)
        if m:
            key, idx = m.group(1), int(m.group(2))
            if isinstance(obj, dict) and isinstance(obj.get(key), list) and idx < len(obj[key]):
                obj[key][idx] = value
        elif isinstance(obj, dict):
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
        for entry in entry_map.values():
            if entry.metadata.get("field") == "displayName":
                data["displayName"] = entry.translation
                break

        for ev_id, event in self._iter_events(data.get("events")):
            for pg_idx, page in enumerate(event.get("pages", [])):
                if not isinstance(page, dict):
                    continue
                ctx = f"event[{ev_id}].page[{pg_idx}]"
                self._reinsert_event_list(page, by_prefix.get(ctx, []))
        return data

    def _reinsert_list_with_events(
        self, data: Any, entry_map: dict, filename: str
    ) -> Any:
        if not isinstance(data, list):
            return data
        by_prefix = self._group_by_prefix(entry_map)
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
                self._reinsert_event_list(obj, by_prefix.get(f"event[{obj_id}]", []))
            # Troops.json: pages with lists
            for pg_idx, page in enumerate(obj.get("pages", [])):
                if not isinstance(page, dict):
                    continue
                ctx = f"troop[{obj_id}].page[{pg_idx}]"
                self._reinsert_event_list(page, by_prefix.get(ctx, []))
        return data

    def _reinsert_event_list(self, holder: dict, entries: list) -> None:
        """Apply translations back into an event command list (in place).

        The list is rebuilt rather than patched: a translation rarely needs the
        same number of lines as the original, and writing only into the existing
        `401` slots dropped every extra line and left blanks behind. Extra line
        commands are created as needed, and long messages are split into further
        pages so nothing overflows the four-line message window.
        """
        cmd_list = holder.get("list")
        if not isinstance(cmd_list, list) or not entries:
            return

        dialogue: dict[int, TextEntry] = {}
        scroll: dict[int, TextEntry] = {}
        choice_by_cmd: dict[int, list] = {}
        params_by_cmd: dict[int, list] = {}
        for entry in entries:
            meta = entry.metadata
            etype = meta.get("type")
            if etype == "dialogue":
                dialogue[meta.get("block_start")] = entry
            elif etype == "scroll":
                scroll[meta.get("block_start")] = entry
            elif etype == "choice":
                choice_by_cmd.setdefault(meta.get("cmd_index"), []).append(entry)
            elif etype == "param":
                params_by_cmd.setdefault(meta.get("cmd_index"), []).append(entry)

        wrap = bool(config.get("wrap_text", True))
        max_lines = int(config.get("max_message_lines", 4))

        new_list: list = []
        i = 0
        n = len(cmd_list)
        while i < n:
            cmd = cmd_list[i]
            if not isinstance(cmd, dict):
                new_list.append(cmd)
                i += 1
                continue
            code = cmd.get("code", 0)

            for entry in params_by_cmd.get(i, []):
                idx = entry.metadata.get("param_index", 1)
                params = cmd.get("parameters")
                if isinstance(params, list) and idx < len(params):
                    params[idx] = entry.translation

            if code == CODE_SHOW_TEXT and i in dialogue:
                _, j = self._collect_block(cmd_list, i, CODE_TEXT_LINE)
                new_list.extend(self._rebuild_block(
                    cmd_list, i, j, dialogue[i], CODE_TEXT_LINE, wrap, max_lines
                ))
                i = j
                continue

            if code == CODE_SCROLL_TEXT and i in scroll:
                _, j = self._collect_block(cmd_list, i, CODE_SCROLL_LINE)
                new_list.extend(self._rebuild_block(
                    cmd_list, i, j, scroll[i], CODE_SCROLL_LINE, wrap, 0
                ))
                i = j
                continue

            if code == CODE_SHOW_CHOICES and i in choice_by_cmd:
                params = cmd.get("parameters")
                if isinstance(params, list) and params and isinstance(params[0], list):
                    for entry in choice_by_cmd[i]:
                        c_idx = entry.metadata.get("choice_index", 0)
                        if 0 <= c_idx < len(params[0]):
                            params[0][c_idx] = entry.translation

            new_list.append(cmd)
            i += 1

        holder["list"] = new_list

    def _rebuild_block(
        self, cmd_list: list, start: int, end: int, entry: TextEntry,
        line_code: int, wrap: bool, max_lines: int,
    ) -> list:
        """Return the replacement commands for the message block [start, end)."""
        header = cmd_list[start]
        originals = [cmd_list[k] for k in range(start + 1, end)]
        indent = header.get("indent", 0)

        text = entry.translation
        if wrap:
            pages = layout_message(text, self.version, max_lines)
        else:
            lines = text.split("\n")
            pages = [lines] if max_lines <= 0 else [
                lines[k:k + max_lines] for k in range(0, len(lines), max_lines)
            ]
        if not pages:
            pages = [[""]]

        out: list = []
        spare = list(originals)
        for page_idx, lines in enumerate(pages):
            if page_idx == 0:
                out.append(header)
            else:
                out.append({
                    "code": header.get("code", CODE_SHOW_TEXT),
                    "indent": indent,
                    "parameters": list(header.get("parameters", [])),
                })
            for line in lines:
                if spare:
                    cmd = spare.pop(0)
                    params = cmd.get("parameters")
                    if isinstance(params, list) and params:
                        params[0] = line
                    else:
                        cmd["parameters"] = [line]
                    out.append(cmd)
                else:
                    out.append({"code": line_code, "indent": indent, "parameters": [line]})
        return out
