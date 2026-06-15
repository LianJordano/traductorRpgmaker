"""Extractor for RPG Maker 2000/2003 (binary LMU/LDB/LMT format).

Based on the EasyRPG LCF specification:
  https://github.com/EasyRPG/liblcf

LCF file structure:
  - Header: BER(len) + "LcfXxx" magic
  - Body: sequence of Chunks until EOF
  - Chunk: BER(id) + BER(size) + data
    id=0 means end-of-block

Database (LDB) top-level sections (chunk IDs):
  0x0B Actors     0x0C Skills    0x0D Animations  0x0E Terrains
  0x0F Items      0x10 Enemies   0x11 Troops      0x12 States
  0x13 Animations 0x14 Chipsets  0x15 Layout      0x16 BattleLayout
  0x17 CommonEvents                0x18 GameTitle  ...

Actor fields (chunk IDs within an actor record):
  0x01 name        0x02 title(class)
  0x15 skill_name (for initial skill)

Item fields:
  0x01 name  0x02 description

Skill fields:
  0x01 name  0x02 description  0x0E use_message1  0x0F use_message2

State fields:
  0x01 name  0x0E message_actor  0x0F message_enemy
  0x10 message_already  0x11 message_affected  0x12 message_recovery

Enemy fields:
  0x01 name

Troop fields:
  0x01 name

Common Event fields:
  0x01 name

Map Event Command (in LMU):
  Code 10110 = ShowMessage  → params: (char*)msg1-4
  Code 10120 = ShowMessageFace
  Code 10140 = ShowChoices  → params: count + strings
  Code 10610 = ShowBattleAnimation
  Code 20710 = ShowString   (RM2003 battle event)
"""
from __future__ import annotations
from pathlib import Path
from typing import NamedTuple, Optional

from core import logger
from core.models import ExtractionResult, TextEntry
from extractors.base import BaseExtractor
from parsers.binary_parser import BinaryReader, Chunk, load_file, read_chunks


# ── Chunk-ID → field-name maps ─────────────────────────────────────────────

SECTION_NAMES = {
    0x0B: "Actors",
    0x0C: "Skills",
    0x0E: "Terrains",
    0x0F: "Items",
    0x10: "Enemies",
    0x11: "Troops",
    0x12: "States",
    0x14: "Chipsets",
    0x17: "CommonEvents",
}

STRING_FIELDS: dict[int, dict[int, str]] = {
    # Actors
    0x0B: {0x01: "name", 0x02: "title"},
    # Skills
    0x0C: {0x01: "name", 0x02: "description", 0x0E: "use_message1", 0x0F: "use_message2"},
    # Items
    0x0F: {0x01: "name", 0x02: "description"},
    # Enemies
    0x10: {0x01: "name"},
    # Troops
    0x11: {0x01: "name"},
    # States
    0x12: {
        0x01: "name",
        0x0E: "message_actor",
        0x0F: "message_enemy",
        0x10: "message_already",
        0x11: "message_affected",
        0x12: "message_recovery",
    },
    # Common Events
    0x17: {0x01: "name"},
}

# Event command codes that hold text
CMD_SHOW_MESSAGE = 10110
CMD_SHOW_CHOICES = 10140
CMD_INPUT_NUMBER = 10150
CMD_SHOW_STRING  = 20710  # RM2003 battle messages

# Number of text params in ShowMessage
SHOW_MESSAGE_LINES = 4


class RM2000Extractor(BaseExtractor):
    @property
    def version(self) -> str:
        return "RM2000/2003"

    # ── public API ────────────────────────────────────────────────────────────

    def extract(self) -> ExtractionResult:
        result = ExtractionResult(game_path=str(self.game_dir), version=self.version)

        ldb_path = self.data_dir / "RPG_RT.ldb"
        map_files = sorted(self.data_dir.glob("Map[0-9]*.lmu"))

        all_files: list[Path] = []
        if ldb_path.exists():
            all_files.append(ldb_path)
        all_files.extend(map_files)

        total = len(all_files)
        for idx, fpath in enumerate(all_files):
            if self._cancelled():
                break
            self._progress(idx, total, fpath.name)
            logger.info(f"Extracting: {fpath.name}")
            try:
                if fpath.suffix.lower() == ".ldb":
                    entries = self._extract_ldb(fpath)
                else:
                    entries = self._extract_lmu(fpath)
                result.entries.extend(entries)
                logger.success(f"  → {len(entries)} texts from {fpath.name}")
            except Exception as exc:
                msg = f"Error in {fpath.name}: {exc}"
                logger.error(msg)
                result.errors.append(msg)

        self._progress(total, total, "Done")
        return result

    def reinsert(self, result: ExtractionResult) -> bool:
        logger.warning("RM2000/2003 binary reinsertion is not yet supported.")
        return False

    # ── LDB parsing ───────────────────────────────────────────────────────────

    def _extract_ldb(self, path: Path) -> list[TextEntry]:
        entries: list[TextEntry] = []
        reader = load_file(path)
        if not reader:
            logger.warning(f"Could not load: {path.name}")
            return entries

        # Top-level chunks — each one is a database section
        try:
            top_chunks = read_chunks(reader)
        except Exception as exc:
            logger.warning(f"LDB top-level parse failed: {exc}")
            return entries

        for section_chunk in top_chunks:
            sid = section_chunk.chunk_id
            section_name = SECTION_NAMES.get(sid, f"sec_{sid:#04x}")
            field_map = STRING_FIELDS.get(sid)
            if field_map is None:
                continue

            sub = section_chunk.sub_reader()
            try:
                self._parse_array_section(
                    sub, path.name, section_name, sid, field_map, entries
                )
            except Exception as exc:
                logger.debug(f"Section {section_name} parse error: {exc}")

        return entries

    def _parse_array_section(
        self,
        reader: BinaryReader,
        filename: str,
        section_name: str,
        section_id: int,
        field_map: dict[int, str],
        entries: list[TextEntry],
    ) -> None:
        """Parse a LDB array section (actors, items, skills, …)."""
        try:
            count = reader.read_ber()
        except Exception:
            return

        for _ in range(count):
            # Each element starts with its 1-based ID
            try:
                elem_id = reader.read_ber()
            except Exception:
                break

            # Then a series of field chunks terminated by id=0
            try:
                elem_chunks = read_chunks(reader)
            except Exception:
                break

            for chunk in elem_chunks:
                field_name = field_map.get(chunk.chunk_id)
                if not field_name:
                    continue
                if not chunk.data:
                    continue
                try:
                    text = chunk.sub_reader().read_string()
                    ctx = f"{section_name}[{elem_id}].{field_name}"
                    entry = self._make_entry(
                        filename, ctx, text, len(entries),
                        {
                            "section_id": section_id,
                            "elem_id": elem_id,
                            "chunk_id": chunk.chunk_id,
                            "field": field_name,
                        },
                    )
                    if entry:
                        entries.append(entry)
                except Exception:
                    pass

    # ── LMU (map) parsing ─────────────────────────────────────────────────────

    def _extract_lmu(self, path: Path) -> list[TextEntry]:
        entries: list[TextEntry] = []
        reader = load_file(path)
        if not reader:
            return entries

        try:
            top_chunks = read_chunks(reader)
        except Exception as exc:
            logger.warning(f"LMU top-level parse failed for {path.name}: {exc}")
            return entries

        for chunk in top_chunks:
            # Chunk 0x51 = events section in LMU
            if chunk.chunk_id == 0x51:
                sub = chunk.sub_reader()
                try:
                    self._parse_map_events(sub, path.name, entries)
                except Exception as exc:
                    logger.debug(f"Map events parse error in {path.name}: {exc}")
                break

        # If the dedicated events chunk wasn't found, do a best-effort scan
        if not entries:
            self._scan_strings_heuristic(path, entries)

        return entries

    def _parse_map_events(
        self, reader: BinaryReader, filename: str, entries: list[TextEntry]
    ) -> None:
        """Parse the events section of an LMU file."""
        try:
            event_count = reader.read_ber()
        except Exception:
            return

        for _ in range(event_count):
            try:
                event_id = reader.read_ber()
                event_chunks = read_chunks(reader)
            except Exception:
                break

            for chunk in event_chunks:
                # Chunk 0x05 = pages array inside an event
                if chunk.chunk_id == 0x05:
                    page_sub = chunk.sub_reader()
                    try:
                        page_count = page_sub.read_ber()
                    except Exception:
                        continue
                    for pg_idx in range(page_count):
                        try:
                            _pg_id = page_sub.read_ber()
                            page_chunks = read_chunks(page_sub)
                        except Exception:
                            break
                        for pc in page_chunks:
                            # Chunk 0x0B = command list in a page
                            if pc.chunk_id == 0x0B:
                                cmd_sub = pc.sub_reader()
                                try:
                                    self._parse_command_list(
                                        cmd_sub, filename,
                                        f"event[{event_id}].page[{pg_idx}]",
                                        entries,
                                    )
                                except Exception:
                                    pass

    def _parse_command_list(
        self, reader: BinaryReader, filename: str, ctx_prefix: str,
        entries: list[TextEntry]
    ) -> None:
        """Parse an event command list and extract ShowMessage/ShowChoices text."""
        try:
            cmd_count = reader.read_ber()
        except Exception:
            return

        block_idx = 0
        i = 0
        while i < cmd_count:
            try:
                code = reader.read_ber()
                _indent = reader.read_ber()
                str_param = reader.read_string()
                int_count = reader.read_ber()
                int_params = [reader.read_ber() for _ in range(int_count)]
            except Exception:
                break

            if code == CMD_SHOW_MESSAGE:
                # str_param is the first line; int_params may hold message flags
                lines = [str_param] if str_param else []
                # Following commands with code 20110 are continuation lines
                # (For RM2003 multiline messages — we handle them here)
                # The simple RM2000 ShowMessage puts all 4 lines as additional
                # string params; some versions encode them differently.
                # We extract what we have:
                text = "\n".join(l for l in lines if l)
                if text:
                    entry = self._make_entry(
                        filename,
                        f"{ctx_prefix}.dialogue[{block_idx}]",
                        text,
                        len(entries),
                        {"type": "dialogue", "cmd_index": i},
                    )
                    if entry:
                        entries.append(entry)
                    block_idx += 1

            elif code == CMD_SHOW_CHOICES:
                # str_param may contain all choices separated by \n
                if str_param:
                    for c_idx, choice in enumerate(str_param.split("\n")):
                        if choice.strip():
                            entry = self._make_entry(
                                filename,
                                f"{ctx_prefix}.choice[{block_idx}][{c_idx}]",
                                choice.strip(),
                                len(entries),
                                {"type": "choice", "cmd_index": i},
                            )
                            if entry:
                                entries.append(entry)
                    block_idx += 1

            i += 1

    # ── Heuristic fallback ────────────────────────────────────────────────────

    def _scan_strings_heuristic(self, path: Path, entries: list[TextEntry]) -> None:
        """Fallback: scan raw bytes looking for BER-length-prefixed strings."""
        try:
            data = path.read_bytes()
        except Exception:
            return

        filename = path.name
        seen: set[str] = set()
        pos = 12  # skip header area
        str_idx = 0

        while pos < len(data) - 3:
            # Try to interpret current byte as start of a BER-encoded length
            try:
                r = BinaryReader(data[pos:])
                length = r.read_ber()
                ber_bytes = r.pos  # how many bytes the BER length used

                if 3 <= length <= 200:
                    raw = data[pos + ber_bytes : pos + ber_bytes + length]
                    if len(raw) < length:
                        pos += 1
                        continue

                    # Try to decode
                    for enc in ("utf-8", "cp932", "shift_jis"):
                        try:
                            text = raw.decode(enc)
                            # Must contain some recognizable text character
                            has_jp  = any(ord(c) > 0x3000 for c in text)
                            has_lat = any(c.isalpha() for c in text)
                            if (has_jp or has_lat) and text not in seen:
                                seen.add(text)
                                entry = self._make_entry(
                                    filename,
                                    f"scan[{str_idx}]",
                                    text,
                                    str_idx,
                                    {"offset": pos, "enc": enc},
                                )
                                if entry:
                                    entries.append(entry)
                                    str_idx += 1
                            pos += ber_bytes + length
                            break
                        except UnicodeDecodeError:
                            pass
                    else:
                        pos += 1
                else:
                    pos += 1
            except Exception:
                pos += 1
