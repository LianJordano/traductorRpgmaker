"""Extractor for RPG Maker VX Ace (.rvdata2 Ruby Marshal files).

Also serves as the base for VX (.rvdata) and XP (.rxdata), which use the same
Marshal container with slightly different class fields.
"""
from __future__ import annotations
from pathlib import Path
from typing import Any, Optional

from core import config, logger
from core.models import ExtractionResult, TextEntry
from extractors.base import BaseExtractor
from parsers import marshal_parser as mp
from utils.text_utils import layout_message

# --- Event command codes -----------------------------------------------------
CODE_SHOW_TEXT = 101        # header of a message block; 401 lines follow
CODE_TEXT_LINE = 401
CODE_SHOW_CHOICES = 102     # parameters[0] is the list of choice labels
CODE_CHOICE_BRANCH = 402    # parameters = [index, label]
CODE_SCROLL_TEXT = 105      # header of a scrolling-text block; 405 lines follow
CODE_SCROLL_LINE = 405
CODE_CHANGE_NAME = 320      # parameters = [actor_id, new name]
CODE_CHANGE_NICKNAME = 324
CODE_CHANGE_PROFILE = 325

# parameters[1] holds free text for these commands
NAME_COMMANDS = {CODE_CHANGE_NAME, CODE_CHANGE_NICKNAME, CODE_CHANGE_PROFILE}

# Translatable fields per database class, keyed by file stem so .rvdata2,
# .rvdata and .rxdata can all share the table.
DB_FIELDS: dict[str, list[str]] = {
    "Actors":  ["name", "nickname", "description"],
    "Armors":  ["name", "description"],
    "Classes": ["name", "description"],
    "Enemies": ["name"],
    "Items":   ["name", "description"],
    "Skills":  ["name", "description", "message1", "message2"],
    "States":  ["name", "message1", "message2", "message3", "message4"],
    "Weapons": ["name", "description"],
}

# `note` drives plugin/script behaviour far more often than it shows text to the
# player, and a translated notetag silently disables the script reading it. Opt
# in through the `translate_notes` setting.
NOTE_FIELD = "note"

# System fields worth translating. `switches` and `variables` are deliberately
# excluded: they are editor labels, but scripts do look them up by name.
SYSTEM_SIMPLE = ["game_title", "currency_unit"]
SYSTEM_LISTS = ["elements", "skill_types", "weapon_types", "armor_types"]
SYSTEM_OBJECTS = ["terms", "words"]


class VXAceExtractor(BaseExtractor):
    EXT = ".rvdata2"
    #: XP stores the first line of a message in the 101 command itself.
    TEXT_IN_HEADER = False
    #: XP (Ruby 1.8) has no string encoding marker, so text is raw bytes.
    RAW_BYTE_STRINGS = False

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._byte_encoding = "utf-8"

    @property
    def version(self) -> str:
        return "VXAce"

    def _detect_byte_encoding(self, data: Any) -> str:
        """Pick the encoding most of this file's raw byte strings use.

        Needed for RPG Maker XP, where nothing in the file records an encoding:
        a translation written back with the wrong charset renders as mojibake.
        """
        from collections import Counter
        counts: Counter = Counter()

        def walk(obj: Any, depth: int = 0) -> None:
            if depth > 16:
                return
            if isinstance(obj, bytes):
                if obj:
                    counts[mp.decode_bytes(obj).source_encoding] += 1
            elif isinstance(obj, list):
                for item in obj:
                    walk(item, depth + 1)
            elif isinstance(obj, dict):
                for item in obj.values():
                    walk(item, depth + 1)
            else:
                attrs = getattr(obj, "attributes", None)
                if isinstance(attrs, dict):
                    for item in attrs.values():
                        walk(item, depth + 1)

        walk(data)
        return counts.most_common(1)[0][0] if counts else "utf-8"

    def _as_marshal_str(self, text: str, template: Any = None) -> Any:
        """Convert a translation to the value format this engine expects."""
        if template is None and self.RAW_BYTE_STRINGS:
            return mp._encode_like(text, self._byte_encoding)
        if isinstance(template, bytes) and not template and self.RAW_BYTE_STRINGS:
            # An empty original tells us nothing about the charset; use the one
            # the rest of the file uses.
            return mp._encode_like(text, self._byte_encoding)
        return mp.make_string(text, template)

    def _set_ivar(self, obj: Any, name: str, text: str) -> None:
        """Write a translated instance variable, keeping the engine's format."""
        attrs = getattr(obj, "attributes", None)
        if not isinstance(attrs, dict):
            return
        key = "@" + name if ("@" + name) in attrs else (name if name in attrs else "@" + name)
        attrs[key] = self._as_marshal_str(text, attrs.get(key))

    # ------------------------------------------------------------------ setup

    def _fields_for(self, stem: str) -> list[str]:
        fields = list(DB_FIELDS.get(stem, []))
        if fields and config.get("translate_notes"):
            fields.append(NOTE_FIELD)
        return fields

    def _get_target_files(self) -> list[Path]:
        files: list[Path] = sorted(self.data_dir.glob(f"Map[0-9]*{self.EXT}"))
        for stem in ("CommonEvents", "Troops", "System", *DB_FIELDS):
            p = self.data_dir / f"{stem}{self.EXT}"
            if p.exists():
                files.append(p)
        return files

    # ------------------------------------------------------------- extraction

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

    def _extract_file(self, fpath: Path) -> list[TextEntry]:
        name = fpath.name
        stem = fpath.stem
        data = mp.load(fpath)
        if stem.startswith("Map") and len(stem) > 3 and stem[3].isdigit():
            return self._extract_map(data, name)
        if stem == "CommonEvents":
            return self._extract_common_events(data, name)
        if stem == "Troops":
            return self._extract_troops(data, name)
        if stem == "System":
            return self._extract_system(data, name)
        fields = self._fields_for(stem)
        if fields:
            return self._extract_database_file(data, name, fields)
        return []

    def _extract_database_file(
        self, data: Any, filename: str, fields: list[str]
    ) -> list[TextEntry]:
        entries: list[TextEntry] = []
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

    def _extract_system(self, data: Any, filename: str) -> list[TextEntry]:
        """Extract the System record — the game title, currency, element and
        equipment type names, and every UI term.

        System is a single Ruby object rather than a list, so the generic
        database path skipped it entirely and left the whole menu untranslated.
        """
        entries: list[TextEntry] = []

        def add(path: str, text: Any) -> None:
            if not isinstance(text, str):
                return
            entry = self._make_entry(
                filename, f"system.{path}", text, len(entries), {"path": path}
            )
            if entry:
                entries.append(entry)

        for field in SYSTEM_SIMPLE:
            add(field, self._get_attr(data, field, None))

        for field in SYSTEM_LISTS:
            values = self._get_attr(data, field, None)
            if isinstance(values, list):
                for i, v in enumerate(values):
                    add(f"{field}[{i}]", mp.to_str(v))

        for field in SYSTEM_OBJECTS:
            holder = self._get_attr(data, field, None)
            if holder is None or isinstance(holder, (str, bytes, list)):
                continue
            attrs = getattr(holder, "attributes", None)
            if not isinstance(attrs, dict):
                continue
            for key in sorted(attrs):
                sub = key.lstrip("@")
                value = mp.to_str(attrs[key])
                if isinstance(value, str):
                    add(f"{field}.{sub}", value)
                elif isinstance(value, list):
                    for i, v in enumerate(value):
                        add(f"{field}.{sub}[{i}]", mp.to_str(v))
        return entries

    def _extract_map(self, data: Any, filename: str) -> list[TextEntry]:
        entries: list[TextEntry] = []
        display = self._get_attr(data, "display_name", "")
        if isinstance(display, str):
            entry = self._make_entry(
                filename, "display_name", display, 0, {"field": "display_name"}
            )
            if entry:
                entries.append(entry)
        events = self._get_attr(data, "events", {})
        if isinstance(events, dict):
            for ev_id, event in events.items():
                pages = self._get_attr(event, "pages", []) or []
                for pg_idx, page in enumerate(pages):
                    ev_list = self._get_attr(page, "list", [])
                    entries.extend(
                        self._extract_event_list(
                            ev_list, filename, f"event[{ev_id}].page[{pg_idx}]"
                        )
                    )
        return entries

    def _extract_common_events(self, data: Any, filename: str) -> list[TextEntry]:
        entries: list[TextEntry] = []
        if not isinstance(data, list):
            return entries
        for obj in data:
            if obj is None:
                continue
            ev_id = self._get_attr(obj, "id", "?")
            name = self._get_attr(obj, "name", "")
            if isinstance(name, str):
                entry = self._make_entry(
                    filename, f"event[{ev_id}].name", name, len(entries),
                    {"id": ev_id, "field": "name"},
                )
                if entry:
                    entries.append(entry)
            ev_list = self._get_attr(obj, "list", [])
            entries.extend(
                self._extract_event_list(ev_list, filename, f"event[{ev_id}]")
            )
        return entries

    def _extract_troops(self, data: Any, filename: str) -> list[TextEntry]:
        """Troop names *and* their battle event pages.

        Battle dialogue lives in the troop pages; extracting only `name` left
        every mid-battle line in the original language.
        """
        entries: list[TextEntry] = []
        if not isinstance(data, list):
            return entries
        for obj in data:
            if obj is None:
                continue
            troop_id = self._get_attr(obj, "id", "?")
            name = self._get_attr(obj, "name", "")
            if isinstance(name, str):
                entry = self._make_entry(
                    filename, f"troop[{troop_id}].name", name, len(entries),
                    {"id": troop_id, "field": "name"},
                )
                if entry:
                    entries.append(entry)
            for pg_idx, page in enumerate(self._get_attr(obj, "pages", []) or []):
                ev_list = self._get_attr(page, "list", [])
                entries.extend(
                    self._extract_event_list(
                        ev_list, filename, f"troop[{troop_id}].page[{pg_idx}]"
                    )
                )
        return entries

    def _extract_event_list(
        self, cmd_list: Any, filename: str, ctx_prefix: str
    ) -> list[TextEntry]:
        entries: list[TextEntry] = []
        if not isinstance(cmd_list, list):
            return entries
        i = 0
        block_idx = 0
        n = len(cmd_list)
        while i < n:
            cmd = cmd_list[i]
            code = self._get_attr(cmd, "code", 0)
            params = self._get_attr(cmd, "parameters", [])
            if not isinstance(params, list):
                params = []

            if code == CODE_SHOW_TEXT:
                lines, j = self._collect_block(cmd_list, i, CODE_TEXT_LINE)
                text = "\n".join(lines)
                if text.strip():
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

            if code == CODE_SCROLL_TEXT:
                lines, j = self._collect_block(cmd_list, i, CODE_SCROLL_LINE)
                text = "\n".join(lines)
                if text.strip():
                    entry = self._make_entry(
                        filename, f"{ctx_prefix}.scroll[{block_idx}]", text,
                        block_idx,
                        {"type": "scroll", "block_start": i, "line_count": len(lines)},
                    )
                    if entry:
                        entries.append(entry)
                    block_idx += 1
                i = j
                continue

            if code == CODE_SHOW_CHOICES and params:
                choices = params[0]
                if isinstance(choices, list):
                    for c_idx, choice in enumerate(choices):
                        choice = mp.to_str(choice)
                        if isinstance(choice, str):
                            entry = self._make_entry(
                                filename,
                                f"{ctx_prefix}.choice[{block_idx}][{c_idx}]",
                                choice, block_idx * 1000 + c_idx,
                                {"type": "choice", "cmd_index": i, "choice_index": c_idx},
                            )
                            if entry:
                                entries.append(entry)
                    block_idx += 1

            elif code == CODE_CHOICE_BRANCH and len(params) > 1:
                label = mp.to_str(params[1])
                if isinstance(label, str):
                    entry = self._make_entry(
                        filename, f"{ctx_prefix}.branch[{i}]", label, i,
                        {"type": "param", "cmd_index": i, "param_index": 1},
                    )
                    if entry:
                        entries.append(entry)

            elif code in NAME_COMMANDS and len(params) > 1:
                value = mp.to_str(params[1])
                if isinstance(value, str):
                    entry = self._make_entry(
                        filename, f"{ctx_prefix}.name[{i}]", value, i,
                        {"type": "param", "cmd_index": i, "param_index": 1},
                    )
                    if entry:
                        entries.append(entry)

            i += 1
        return entries

    def _collect_block(self, cmd_list: list, start: int, line_code: int) -> tuple[list[str], int]:
        """Collect the text lines belonging to the block that starts at `start`.

        Returns (lines, index_after_block).
        """
        lines: list[str] = []
        if self.TEXT_IN_HEADER:
            params = self._get_attr(cmd_list[start], "parameters", []) or []
            if params:
                header = mp.to_str(params[0])
                if isinstance(header, str):
                    lines.append(header)
        j = start + 1
        n = len(cmd_list)
        while j < n:
            if self._get_attr(cmd_list[j], "code", 0) != line_code:
                break
            params = self._get_attr(cmd_list[j], "parameters", []) or []
            value = mp.to_str(params[0]) if params else ""
            lines.append(value if isinstance(value, str) else "")
            j += 1
        return lines, j

    def _get_attr(self, obj: Any, name: str, default: Any = None) -> Any:
        if obj is None:
            return default
        if isinstance(obj, dict):
            return mp.to_str(obj.get(name, default))
        attrs = getattr(obj, "attributes", None)
        if isinstance(attrs, dict):
            # Ruby instance variables are stored with a leading '@'
            for key in ("@" + name, name):
                if key in attrs:
                    return mp.to_str(attrs[key])
            return default
        return getattr(obj, name, default)

    # ------------------------------------------------------------ reinsertion

    def reinsert(self, result: ExtractionResult) -> bool:
        if not mp.is_available():
            logger.error("rubymarshal not available for reinsertion")
            return False

        by_file: dict[str, list[TextEntry]] = {}
        for entry in result.entries:
            if entry.status == "translated" and entry.translation:
                by_file.setdefault(entry.file, []).append(entry)

        success = True
        total = len(by_file)
        for idx, (filename, entries) in enumerate(by_file.items()):
            if self._cancelled():
                logger.info("Reinsertion cancelled.")
                break
            self._progress(idx, total, filename)
            fpath = self.data_dir / filename
            if not fpath.exists():
                logger.warning(f"File not found for reinsertion: {filename}")
                continue
            # Keep the original bytes so we can roll back if the written file
            # turns out to be unreadable — a corrupt data file makes RPG Maker
            # fail to load the map (missing-graphic errors), so a working
            # untranslated file is always preferable to a broken one.
            original_bytes = fpath.read_bytes()
            try:
                data = mp.load(fpath)
                if self.RAW_BYTE_STRINGS:
                    self._byte_encoding = self._detect_byte_encoding(data)
                self._reinsert_into(data, entries, filename)
                mp.save(fpath, data)
                # Verify the file we just wrote can be parsed back.
                mp.loads(fpath.read_bytes())
                logger.success(f"Reinserted {len(entries)} into {filename}")
            except Exception as exc:
                logger.error(f"Reinsertion failed for {filename}: {exc}")
                try:
                    fpath.write_bytes(original_bytes)
                    logger.warning(f"Restored original {filename} (left untranslated).")
                except Exception as restore_exc:
                    logger.error(f"Could not restore {filename}: {restore_exc}")
                success = False
        self._progress(total, total, "Done")
        return success

    def _reinsert_into(self, data: Any, entries: list[TextEntry], filename: str) -> None:
        stem = Path(filename).stem
        entry_map = {e.uid: e for e in entries}
        if stem.startswith("Map") and len(stem) > 3 and stem[3].isdigit():
            self._ri_map(data, entry_map)
        elif stem == "CommonEvents":
            self._ri_common_events(data, entry_map)
        elif stem == "Troops":
            self._ri_troops(data, entry_map)
        elif stem == "System":
            self._ri_system(data, entry_map)
        elif entry_map:
            self._ri_database(data, entry_map)

    def _by_context_prefix(self, entry_map: dict) -> dict[str, list[TextEntry]]:
        """Group entries by the context prefix identifying their event list."""
        grouped: dict[str, list[TextEntry]] = {}
        for entry in entry_map.values():
            prefix = entry.context.rsplit(".", 1)[0]
            grouped.setdefault(prefix, []).append(entry)
        return grouped

    def _ri_database(self, data: Any, entry_map: dict) -> None:
        if not isinstance(data, list):
            return
        by_id_field: dict = {}
        for e in entry_map.values():
            key = (e.metadata.get("id"), e.metadata.get("field"))
            by_id_field[key] = e
        for obj in data:
            if obj is None:
                continue
            obj_id = self._get_attr(obj, "id", None)
            for (oid, field), entry in by_id_field.items():
                if oid == obj_id and field:
                    self._set_ivar(obj, field, entry.translation)

    def _ri_system(self, data: Any, entry_map: dict) -> None:
        for entry in entry_map.values():
            path = entry.metadata.get("path", "")
            if not path:
                continue
            self._set_system_path(data, path, entry.translation)

    def _set_system_path(self, data: Any, path: str, value: str) -> None:
        import re
        m = re.fullmatch(r"(\w+)(?:\.(\w+))?(?:\[(\d+)\])?", path)
        if not m:
            return
        field, sub, index = m.group(1), m.group(2), m.group(3)
        target = data
        if sub is not None:
            target = mp.get_ivar(data, field)
            if target is None:
                return
            field = sub
        if index is None:
            self._set_ivar(target, field, value)
            return
        values = mp.get_ivar(target, field)
        if isinstance(values, list):
            i = int(index)
            if i < len(values):
                values[i] = self._as_marshal_str(value, values[i])

    def _ri_map(self, data: Any, entry_map: dict) -> None:
        for entry in entry_map.values():
            if entry.metadata.get("field") == "display_name":
                self._set_ivar(data, "display_name", entry.translation)
                break
        by_prefix = self._by_context_prefix(entry_map)
        events = self._get_attr(data, "events", {}) or {}
        if isinstance(events, dict):
            for ev_id, event in events.items():
                pages = self._get_attr(event, "pages", []) or []
                for pg_idx, page in enumerate(pages):
                    ctx = f"event[{ev_id}].page[{pg_idx}]"
                    self._ri_event_list(page, by_prefix.get(ctx, []))

    def _ri_common_events(self, data: Any, entry_map: dict) -> None:
        if not isinstance(data, list):
            return
        by_prefix = self._by_context_prefix(entry_map)
        names = {e.metadata.get("id"): e for e in entry_map.values()
                 if e.metadata.get("field") == "name"}
        for obj in data:
            if obj is None:
                continue
            ev_id = self._get_attr(obj, "id", "?")
            if ev_id in names:
                self._set_ivar(obj, "name", names[ev_id].translation)
            self._ri_event_list(obj, by_prefix.get(f"event[{ev_id}]", []))

    def _ri_troops(self, data: Any, entry_map: dict) -> None:
        if not isinstance(data, list):
            return
        by_prefix = self._by_context_prefix(entry_map)
        names = {e.metadata.get("id"): e for e in entry_map.values()
                 if e.metadata.get("field") == "name"}
        for obj in data:
            if obj is None:
                continue
            troop_id = self._get_attr(obj, "id", "?")
            if troop_id in names:
                self._set_ivar(obj, "name", names[troop_id].translation)
            for pg_idx, page in enumerate(self._get_attr(obj, "pages", []) or []):
                ctx = f"troop[{troop_id}].page[{pg_idx}]"
                self._ri_event_list(page, by_prefix.get(ctx, []))

    # -- event lists ---------------------------------------------------------

    def _set_param(self, cmd: Any, index: int, text: str) -> None:
        params = self._get_attr(cmd, "parameters", None)
        if isinstance(params, list) and index < len(params):
            params[index] = self._as_marshal_str(text, params[index])

    def _make_line_command(self, template: Any, code: int, text: str, value_template: Any) -> Any:
        return mp.clone_command(template, code, [self._as_marshal_str(text, value_template)])

    def _ri_event_list(self, holder: Any, entries: list[TextEntry]) -> None:
        """Apply translations to the command list owned by `holder`.

        The list is rebuilt rather than patched in place: a translation almost
        always needs a different number of lines than the original Japanese, and
        writing only into the existing slots either truncated the text or left
        blank lines behind. Extra `401`/`405` commands are cloned as needed and
        long messages are split into additional pages so nothing overflows the
        message window.
        """
        cmd_list = self._get_attr(holder, "list", None)
        if not isinstance(cmd_list, list) or not entries:
            return

        dialogue: dict[int, TextEntry] = {}
        scroll: dict[int, TextEntry] = {}
        choices: dict[int, list[TextEntry]] = {}
        params_by_cmd: dict[int, list[TextEntry]] = {}
        for entry in entries:
            meta = entry.metadata
            etype = meta.get("type")
            if etype == "dialogue":
                dialogue[meta.get("block_start")] = entry
            elif etype == "scroll":
                scroll[meta.get("block_start")] = entry
            elif etype == "choice":
                choices.setdefault(meta.get("cmd_index"), []).append(entry)
            elif etype == "param":
                params_by_cmd.setdefault(meta.get("cmd_index"), []).append(entry)

        wrap = bool(config.get("wrap_text", True))
        max_lines = int(config.get("max_message_lines", 4))

        new_list: list = []
        i = 0
        n = len(cmd_list)
        while i < n:
            cmd = cmd_list[i]
            code = self._get_attr(cmd, "code", 0)

            if code == CODE_SHOW_TEXT and i in dialogue:
                _, j = self._collect_block(cmd_list, i, CODE_TEXT_LINE)
                new_list.extend(self._rebuild_block(
                    cmd_list, i, j, dialogue[i], CODE_TEXT_LINE,
                    wrap=wrap, max_lines=max_lines,
                ))
                i = j
                continue

            if code == CODE_SCROLL_TEXT and i in scroll:
                _, j = self._collect_block(cmd_list, i, CODE_SCROLL_LINE)
                new_list.extend(self._rebuild_block(
                    cmd_list, i, j, scroll[i], CODE_SCROLL_LINE,
                    wrap=wrap, max_lines=0,   # scrolling text has no page limit
                ))
                i = j
                continue

            if code == CODE_SHOW_CHOICES and i in choices:
                params = self._get_attr(cmd, "parameters", None)
                if isinstance(params, list) and params and isinstance(params[0], list):
                    labels = params[0]
                    for entry in choices[i]:
                        c_idx = entry.metadata.get("choice_index", 0)
                        if 0 <= c_idx < len(labels):
                            labels[c_idx] = self._as_marshal_str(entry.translation, labels[c_idx])

            elif i in params_by_cmd:
                for entry in params_by_cmd[i]:
                    self._set_param(cmd, entry.metadata.get("param_index", 1), entry.translation)

            new_list.append(cmd)
            i += 1

        cmd_list[:] = new_list

    def _rebuild_block(
        self, cmd_list: list, start: int, end: int, entry: TextEntry,
        line_code: int, wrap: bool, max_lines: int,
    ) -> list:
        """Return the replacement commands for the message block [start, end)."""
        header = cmd_list[start]
        originals = [cmd_list[k] for k in range(start + 1, end)]
        # A template for the string values so XP's raw byte strings stay bytes
        # and VX Ace's UTF-8 RubyStrings stay RubyStrings.
        value_template: Any = None
        for cmd in originals:
            params = self._get_attr(cmd, "parameters", None)
            if isinstance(params, list) and params:
                value_template = params[0]
                break
        if value_template is None and self.TEXT_IN_HEADER:
            # XP messages often have no 401 lines at all; the header's own
            # parameter is then the only sample of the file's string format.
            head_params = self._get_attr(header, "parameters", None)
            if isinstance(head_params, list) and head_params:
                value_template = head_params[0]

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
            if self.TEXT_IN_HEADER:
                # XP keeps the first line inside the 101 command itself.
                head = header if page_idx == 0 else mp.clone_command(
                    header, self._get_attr(header, "code", CODE_SHOW_TEXT),
                    list(self._get_attr(header, "parameters", []) or []),
                )
                self._set_param(head, 0, lines[0] if lines else "")
                out.append(head)
                rest = lines[1:]
            else:
                head = header if page_idx == 0 else mp.clone_command(
                    header, self._get_attr(header, "code", CODE_SHOW_TEXT),
                    list(self._get_attr(header, "parameters", []) or []),
                )
                out.append(head)
                rest = lines
            for line in rest:
                if spare:
                    cmd = spare.pop(0)
                    self._set_param(cmd, 0, line)
                    out.append(cmd)
                else:
                    made = self._make_line_command(
                        originals[0] if originals else header, line_code, line, value_template
                    )
                    if made is not None:
                        out.append(made)
        return out
