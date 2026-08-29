"""Translate the parameter values in RPG Maker MV/MZ's `js/plugins.js`.

Only the *values* inside each plugin's `parameters` object are touched, and only
those that read as prose. Everything else is left byte-for-byte alone, because in
a real game this file mixes player-facing text with values the plugin's code
depends on:

    "配置場所": "描画FPSの設定"     <- the key is Japanese too; renaming it
                                     stops the plugin finding its own setting
    "imagePath": "./Mapshots"      <- a path
    "Chinese Font": "SimHei, ..."  <- a CSS font stack
    "Text Align": "left"           <- a keyword the code compares against

Plugin `.js` source files are deliberately not processed. Their Japanese string
literals are indistinguishable from lookup keys — in one real game, 749 of 740+
literals could not be told apart from `obj["味方X"]` variable lookups or from
code fragments passed to `eval`, and only 7 sat in an actual drawing call.
"""
from __future__ import annotations
import json
import re
from pathlib import Path
from typing import Any, Optional

from core import logger
from core.models import TextEntry
from parsers import js_parser as jsp
from validators.text_filter import is_plugin_value_translatable

#: Virtual file name used in entries so exports show where the text came from.
PLUGINS_FILE = "js/plugins.js"

#: Top-level plugin record keys that must never be translated.
_PROTECTED_KEYS = {"name", "status", "description"}

#: Parameter names whose value is an identifier the plugin's own code uses:
#: a command alias, a switch or variable name, a file, a key binding, a script.
#: The name of the setting is a far more reliable signal than the value itself —
#: `commandName: "particle,パーティクル"` reads like text but registers a plugin
#: command, and renaming it stops every event that calls it from working.
#: Matched as whole words, never as substrings: "ext" lives inside "text",
#: "me" inside "message" and "id" inside "width", so substring matching would
#: throw away exactly the display text this feature exists to translate.
_FUNCTIONAL_NAMES = {
    "command", "commands", "symbol", "switch", "switches", "variable",
    "variables", "keycode", "keybind", "button", "buttons", "key", "keys",
    "id", "ids", "type", "types", "mode", "font", "fonts", "path", "folder",
    "dir", "file", "filename", "files", "image", "images", "picture",
    "pictures", "sprite", "bgm", "bgs", "se", "me", "sound", "sounds",
    "audio", "align", "alignment", "code", "script", "scripts", "formula",
    "eval", "class", "method", "func", "function", "tag", "tags", "notetag",
    "regex", "pattern", "color", "colors", "colour", "anchor", "layer",
    "plugin", "scene", "window", "skin", "extension", "ext", "url", "api",
    "css", "selector", "event", "events",
    # A value under `name` is usually the handle the plugin matches on — the
    # entry of a struct list, a notetag, something stored in the save file — so
    # renaming it detaches the entry from everything that refers to it.
    "name", "names",
}

_TOKEN_SPLIT = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z]*|[a-z]+|\d+")


def _name_tokens(name: str) -> set[str]:
    """Split a parameter name into lowercase words (camelCase, spaces, dashes)."""
    return {t.lower() for t in _TOKEN_SPLIT.findall(name)}


def _is_functional_param(path: tuple) -> bool:
    """True if any key on the way to this value marks it as an identifier."""
    for part in path:
        if isinstance(part, str) and _name_tokens(part) & _FUNCTIONAL_NAMES:
            return True
    return False


def plugins_js_path(data_dir: Path) -> Optional[Path]:
    """Locate `js/plugins.js` relative to the game's data directory."""
    for candidate in (
        data_dir.parent / "js" / "plugins.js",
        data_dir.parent / "plugins.js",
        data_dir.parent.parent / "js" / "plugins.js",
    ):
        if candidate.is_file():
            return candidate
    return None


#: Notetags are written `<Key: value>`; those pieces are what a plugin matches
#: on. Matching against the *whole* note text instead was measured to be almost
#: entirely false positives, so only what sits inside the angle brackets counts.
_NOTETAG = re.compile(r"<([^<>\n]{1,120})>")


def notetag_keys(data_dir: Path) -> set[str]:
    """Every key and value written inside a `<...>` notetag."""
    import json as _json
    keys: set[str] = set()

    def add(note: str) -> None:
        for inner in _NOTETAG.findall(note):
            for piece in re.split(r"[:,;=]", inner):
                piece = piece.strip()
                if len(piece) >= 2:
                    keys.add(piece)

    def walk(obj: Any) -> None:
        if isinstance(obj, list):
            for item in obj:
                walk(item)
        elif isinstance(obj, dict):
            note = obj.get("note")
            if isinstance(note, str) and "<" in note:
                add(note)
            for value in obj.values():
                walk(value)

    for path in sorted(data_dir.glob("*.json")):
        try:
            walk(_json.loads(path.read_text(encoding="utf-8-sig")))
        except Exception:
            continue
    return keys


def _read(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "cp932", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _write(path: Path, text: str, original: bytes) -> None:
    """Write the file back, preserving its byte-order mark if it had one."""
    payload = text.encode("utf-8")
    if original.startswith(b"\xef\xbb\xbf") and not payload.startswith(b"\xef\xbb\xbf"):
        payload = b"\xef\xbb\xbf" + payload
    tmp = path.with_suffix(path.suffix + ".rpgt_tmp")
    tmp.write_bytes(payload)
    tmp.replace(path)


def _is_parameter_value(item: jsp.JsString) -> bool:
    """True for a string that sits somewhere under a plugin's `parameters`."""
    if item.is_key or not item.path:
        return False
    if item.path[0] in _PROTECTED_KEYS:
        return False
    if item.path[0] != "parameters" or len(item.path) < 2:
        return False
    return not _is_functional_param(item.path[1:])


def _path_label(path: tuple) -> str:
    parts = []
    for part in path:
        parts.append(f"[{part}]" if isinstance(part, int) else str(part))
    return ".".join(p for p in parts if p)


# --------------------------------------------------------------------------- #
# Nested JSON parameters
# --------------------------------------------------------------------------- #

def _walk_nested(data: Any, prefix: str = ""):
    """Yield (json_path, text) for every string inside a nested parameter."""
    if isinstance(data, dict):
        for key, value in data.items():
            yield from _walk_nested(value, f"{prefix}/{key}")
    elif isinstance(data, list):
        for i, value in enumerate(data):
            yield from _walk_nested(value, f"{prefix}/{i}")
    elif isinstance(data, str):
        inner = jsp.parse_nested(data)
        if inner is not None:
            yield from _walk_nested(inner, prefix)
        else:
            yield prefix, data


def _set_nested(data: Any, json_path: str, new_text: str) -> bool:
    """Set the value at `json_path`, re-encoding any JSON-in-string on the way."""
    steps = [s for s in json_path.split("/") if s]
    return _set_nested_steps(data, steps, new_text)


def _set_nested_steps(data: Any, steps: list[str], new_text: str) -> bool:
    if not steps:
        return False
    step = steps[0]
    rest = steps[1:]

    if isinstance(data, dict):
        if step not in data:
            return False
        if not rest:
            current = data[step]
            if isinstance(current, str):
                data[step] = new_text
                return True
            return False
        child = data[step]
        if isinstance(child, str):
            inner = jsp.parse_nested(child)
            if inner is None:
                return False
            if _set_nested_steps(inner, rest, new_text):
                data[step] = jsp.dump_nested(inner)
                return True
            return False
        return _set_nested_steps(child, rest, new_text)

    if isinstance(data, list):
        try:
            index = int(step)
        except ValueError:
            return False
        if not 0 <= index < len(data):
            return False
        if not rest:
            if isinstance(data[index], str):
                data[index] = new_text
                return True
            return False
        child = data[index]
        if isinstance(child, str):
            inner = jsp.parse_nested(child)
            if inner is None:
                return False
            if _set_nested_steps(inner, rest, new_text):
                data[index] = jsp.dump_nested(inner)
                return True
            return False
        return _set_nested_steps(child, rest, new_text)

    return False


# --------------------------------------------------------------------------- #
# Extraction
# --------------------------------------------------------------------------- #

def extract(data_dir: Path, make_entry) -> list[TextEntry]:
    """Extract translatable plugin parameter values.

    `make_entry(file, context, text, index, metadata)` is the extractor's own
    entry factory, so the same filtering and uid scheme applies as everywhere
    else.
    """
    path = plugins_js_path(data_dir)
    if path is None:
        return []

    text = _read(path)
    items = jsp.scan(text)
    names = jsp.plugin_names(items)
    from validators.reference_guard import build as build_guard
    vocabulary = notetag_keys(data_dir)
    guard = build_guard(data_dir)
    entries: list[TextEntry] = []
    skipped_keys = 0

    def is_text(value: str) -> bool:
        nonlocal skipped_keys
        if not is_plugin_value_translatable(value):
            return False
        stripped = value.strip()
        if stripped in vocabulary or guard.is_referenced(stripped):
            skipped_keys += 1
            return False
        return True

    for item in items:
        if not _is_parameter_value(item):
            continue
        plugin = names.get(item.record, f"record{item.record}")
        param = _path_label(item.path[1:])

        nested = jsp.parse_nested(item.value)
        if nested is not None:
            # A struct / struct-array parameter: descend into its JSON.
            for json_path, value in _walk_nested(nested):
                if not is_text(value):
                    continue
                entry = make_entry(
                    PLUGINS_FILE,
                    f"plugin[{plugin}].{param}{json_path}",
                    value,
                    len(entries),
                    {"type": "plugin_param", "record": item.record,
                     "param_path": list(item.path), "json_path": json_path},
                )
                if entry:
                    entries.append(entry)
            continue

        if not is_text(item.value):
            continue
        entry = make_entry(
            PLUGINS_FILE,
            f"plugin[{plugin}].{param}",
            item.value,
            len(entries),
            {"type": "plugin_param", "record": item.record,
             "param_path": list(item.path), "json_path": ""},
        )
        if entry:
            entries.append(entry)

    if entries:
        logger.info(f"  → {len(entries)} textos de parámetros de plugin en {path.name}")
    if skipped_keys:
        logger.info(
            f"  → {skipped_keys} parámetros omitidos: el juego los usa como clave "
            f"(notetag o consulta desde un script)"
        )
    return entries


# --------------------------------------------------------------------------- #
# Reinsertion
# --------------------------------------------------------------------------- #

def reinsert(data_dir: Path, entries: list[TextEntry]) -> bool:
    """Write translated parameter values back into `js/plugins.js`.

    Literals are located by re-scanning the file and matching the recorded
    structural path, never by a stored byte offset, so an edit made to the game
    in the meantime cannot cause a write at the wrong place. The result is
    verified before replacing the original, and rolled back on any doubt.
    """
    path = plugins_js_path(data_dir)
    if path is None:
        logger.warning("No se encontró js/plugins.js; se omiten los plugins.")
        return True

    original_bytes = path.read_bytes()
    text = _read(path)
    items = jsp.scan(text)

    # Index the file's literals by (record, path) so entries can find their own.
    by_key: dict[tuple, jsp.JsString] = {}
    for item in items:
        if _is_parameter_value(item):
            by_key[(item.record, tuple(item.path))] = item

    # Group entries by target literal: a nested parameter has several.
    grouped: dict[tuple, list[TextEntry]] = {}
    for entry in entries:
        meta = entry.metadata
        key = (meta.get("record"), tuple(meta.get("param_path") or ()))
        grouped.setdefault(key, []).append(entry)

    edits: list[tuple[int, int, str]] = []
    applied = skipped = 0

    for key, group in grouped.items():
        item = by_key.get(key)
        if item is None:
            skipped += len(group)
            continue

        nested = jsp.parse_nested(item.value)
        if nested is not None:
            changed = False
            for entry in group:
                json_path = entry.metadata.get("json_path", "")
                if _set_nested(nested, json_path, entry.translation):
                    changed = True
                    applied += 1
                else:
                    skipped += 1
            if changed:
                edits.append((item.start, item.end,
                              jsp.encode(jsp.dump_nested(nested), item.quote)))
            continue

        entry = group[0]
        # The literal must still hold exactly what we extracted.
        if item.value != entry.original:
            skipped += len(group)
            continue
        edits.append((item.start, item.end, jsp.encode(entry.translation, item.quote)))
        applied += 1
        skipped += len(group) - 1

    if not edits:
        if skipped:
            logger.warning(f"plugins.js: no se aplicó nada ({skipped} textos no localizados).")
        return True

    new_text = jsp.replace(text, edits)

    if not _verify(text, new_text, len(edits)):
        logger.error("plugins.js: la comprobación de integridad falló; no se modifica.")
        return False

    try:
        _write(path, new_text, original_bytes)
        # Re-read and re-scan: the file must still have the same structure.
        check = jsp.scan(_read(path))
        if len(check) != len(items):
            raise ValueError(
                f"el número de literales cambió ({len(items)} -> {len(check)})"
            )
        logger.success(
            f"plugins.js: {applied} parámetros traducidos"
            + (f", {skipped} omitidos" if skipped else "")
        )
        return True
    except Exception as exc:
        logger.error(f"plugins.js: fallo al escribir ({exc}); se restaura el original.")
        try:
            path.write_bytes(original_bytes)
        except Exception as restore_exc:
            logger.error(f"No se pudo restaurar plugins.js: {restore_exc}")
        return False


def _verify(before: str, after: str, expected_edits: int) -> bool:
    """Sanity-check the rewritten file before it touches the disk.

    Keys, plugin names and structure must be identical; only the values we chose
    may differ. A mismatch means the scanner misread something, and the safe
    response is to leave the file alone.
    """
    old = jsp.scan(before)
    new = jsp.scan(after)
    if len(old) != len(new):
        logger.error(f"plugins.js: literales {len(old)} -> {len(new)}")
        return False

    changed = 0
    for a, b in zip(old, new):
        if a.is_key != b.is_key or a.path != b.path or a.record != b.record:
            logger.error(f"plugins.js: la estructura cambió en {a.path}")
            return False
        if a.is_key and a.value != b.value:
            logger.error(f"plugins.js: se modificó una clave: {a.value!r}")
            return False
        if a.value != b.value:
            changed += 1
    if changed != expected_edits:
        logger.error(
            f"plugins.js: cambiaron {changed} valores, se esperaban {expected_edits}"
        )
        return False
    return True
