"""Locate string literals inside RPG Maker's `js/plugins.js`.

`plugins.js` is JavaScript, not JSON: RPG Maker writes quoted keys but external
tools reformat it with bare identifiers (`name:`), trailing commas and comments.
Parsing it into Python and dumping it back would silently reformat the whole
file, so instead this module finds each string literal's exact position and its
path inside the structure. Reinsertion then rewrites only the chosen literals
and leaves every other byte untouched.
"""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class JsString:
    """A string literal found in the source, with where it sits structurally."""
    start: int                       # offset of the opening quote
    end: int                         # offset just past the closing quote
    quote: str
    value: str                       # decoded text
    is_key: bool = False             # a `"key":` rather than a value
    path: tuple = field(default_factory=tuple)   # ("parameters", "configText")
    record: int = -1                 # index of the enclosing top-level element


_ESCAPES = {
    "n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f",
    "v": "\v", "0": "\0", '"': '"', "'": "'", "\\": "\\", "/": "/",
    "\n": "",   # line continuation
}


def _decode(raw: str) -> str:
    """Decode the body of a JS string literal (quotes already stripped)."""
    out: list[str] = []
    i = 0
    n = len(raw)
    while i < n:
        ch = raw[i]
        if ch != "\\" or i + 1 >= n:
            out.append(ch)
            i += 1
            continue
        nxt = raw[i + 1]
        if nxt == "u":
            if i + 2 < n and raw[i + 2] == "{":
                close = raw.find("}", i + 3)
                if close != -1:
                    try:
                        out.append(chr(int(raw[i + 3:close], 16)))
                        i = close + 1
                        continue
                    except ValueError:
                        pass
            try:
                out.append(chr(int(raw[i + 2:i + 6], 16)))
                i += 6
                continue
            except ValueError:
                pass
        elif nxt == "x":
            try:
                out.append(chr(int(raw[i + 2:i + 4], 16)))
                i += 4
                continue
            except ValueError:
                pass
        out.append(_ESCAPES.get(nxt, nxt))
        i += 2
    return "".join(out)


def encode(value: str, quote: str = '"') -> str:
    """Encode text as a JS string literal, escaping only what must be escaped.

    Non-ASCII is left as-is: `plugins.js` is read as UTF-8, and keeping the
    characters readable matches what RPG Maker itself writes.
    """
    out = [quote]
    for ch in value:
        if ch == "\\":
            out.append("\\\\")
        elif ch == quote:
            out.append("\\" + ch)
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < 0x20:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    out.append(quote)
    return "".join(out)


def _skip_ws(text: str, i: int) -> int:
    """Advance past whitespace and comments."""
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in " \t\r\n":
            i += 1
        elif text.startswith("//", i):
            nl = text.find("\n", i)
            i = n if nl == -1 else nl + 1
        elif text.startswith("/*", i):
            close = text.find("*/", i + 2)
            i = n if close == -1 else close + 2
        else:
            break
    return i


def scan(text: str) -> list[JsString]:
    """Return every string literal with its structural path.

    Containers are tracked as a stack so a value's path is the chain of keys
    that leads to it, and `record` identifies which element of the top-level
    `$plugins` array it belongs to.
    """
    results: list[JsString] = []
    stack: list[dict] = []          # {"kind": "obj"|"arr", "key": str|None, "index": int}
    record = -1
    i = 0
    n = len(text)

    def current_path() -> tuple:
        parts: list = []
        for frame in stack:
            if frame["kind"] == "obj":
                if frame["key"] is not None:
                    parts.append(frame["key"])
            else:
                parts.append(frame["index"])
        # Drop the position inside the top-level `$plugins` array: which plugin
        # a literal belongs to is tracked separately as `record`, so the path is
        # kept relative to the plugin object ("parameters", "configTextHelp").
        while parts and isinstance(parts[0], int):
            parts.pop(0)
        return tuple(parts)

    while i < n:
        ch = text[i]

        if ch in " \t\r\n":
            i += 1
            continue
        if text.startswith("//", i) or text.startswith("/*", i):
            i = _skip_ws(text, i)
            continue

        if ch in "\"'`":
            quote = ch
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == quote:
                    break
                j += 1
            raw = text[i + 1:j]
            after = _skip_ws(text, j + 1)
            is_key = after < n and text[after] == ":"
            item = JsString(
                start=i, end=j + 1, quote=quote, value=_decode(raw),
                is_key=is_key, record=record,
            )
            if is_key:
                if stack and stack[-1]["kind"] == "obj":
                    stack[-1]["key"] = item.value
                item.path = current_path()
            else:
                item.path = current_path()
            results.append(item)
            i = j + 1
            continue

        if ch == "{":
            stack.append({"kind": "obj", "key": None, "index": 0})
            i += 1
            continue
        if ch == "[":
            stack.append({"kind": "arr", "key": None, "index": 0})
            i += 1
            continue
        if ch in "}]":
            if stack:
                stack.pop()
            # Array positions advance on the separating comma, not here, so a
            # closing brace must not bump the parent's index as well.
            i += 1
            continue
        if ch == ",":
            if stack:
                frame = stack[-1]
                if frame["kind"] == "obj":
                    frame["key"] = None
                else:
                    frame["index"] += 1
            i += 1
            continue

        # A bare identifier used as a key: `name:` / `useMapName:`
        if ch.isalpha() or ch in "_$":
            j = i
            while j < n and (text[j].isalnum() or text[j] in "_$"):
                j += 1
            after = _skip_ws(text, j)
            if after < n and text[after] == ":" and stack and stack[-1]["kind"] == "obj":
                stack[-1]["key"] = text[i:j]
            i = j
            continue

        i += 1

    # Assign the record index: everything inside element k of the top array.
    _assign_records(text, results)
    return results


def _assign_records(text: str, items: list[JsString]) -> None:
    """Number the top-level array elements and tag each literal with its own."""
    depth = 0
    record = -1
    boundaries: list[tuple[int, int]] = []   # (offset, record index)
    i = 0
    n = len(text)
    in_top_array = False
    while i < n:
        ch = text[i]
        if ch in "\"'`":
            quote = ch
            i += 1
            while i < n:
                if text[i] == "\\":
                    i += 2
                    continue
                if text[i] == quote:
                    break
                i += 1
            i += 1
            continue
        if text.startswith("//", i) or text.startswith("/*", i):
            i = _skip_ws(text, i)
            continue
        if ch == "[":
            depth += 1
            if depth == 1:
                in_top_array = True
            i += 1
            continue
        if ch == "]":
            depth -= 1
            i += 1
            continue
        if ch == "{":
            if in_top_array and depth == 1:
                record += 1
                boundaries.append((i, record))
            depth += 1
            i += 1
            continue
        if ch == "}":
            depth -= 1
            i += 1
            continue
        i += 1

    for item in items:
        current = -1
        for offset, idx in boundaries:
            if offset <= item.start:
                current = idx
            else:
                break
        item.record = current


def plugin_names(items: list[JsString]) -> dict[int, str]:
    """Map each top-level record to its plugin `name`."""
    names: dict[int, str] = {}
    for item in items:
        if not item.is_key and item.path == ("name",):
            names.setdefault(item.record, item.value)
    return names


def replace(text: str, edits: list[tuple[int, int, str]]) -> str:
    """Apply (start, end, replacement) edits, right to left so offsets hold."""
    out = text
    for start, end, replacement in sorted(edits, key=lambda e: -e[0]):
        out = out[:start] + replacement + out[end:]
    return out


# --------------------------------------------------------------------------- #
# Nested JSON parameters (MZ struct types)
# --------------------------------------------------------------------------- #

def parse_nested(value: str) -> Optional[Any]:
    """Return the JSON structure a parameter string holds, if it holds one.

    MZ struct and struct-array parameters are stored as JSON encoded inside the
    parameter string. Plain scalars are rejected so a value like `"26"` is not
    mistaken for structured data.
    """
    stripped = value.strip()
    if not stripped or stripped[0] not in "[{":
        return None
    try:
        parsed = json.loads(stripped)
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, (list, dict)) else None


def dump_nested(data: Any) -> str:
    """Re-encode nested parameter data the way RPG Maker writes it."""
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))
