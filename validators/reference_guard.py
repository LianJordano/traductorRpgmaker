"""Detect game text that scripts look up by its exact value.

If a plugin does `if (item.name === "Fire Crystal")`, translating that item's
name detaches it from the code that looks for it: nothing errors, the file stays
valid, and a whole system quietly stops working.

The test has to be narrow. An earlier attempt refused any name that merely
*appeared* somewhere in a script or notetag, and measuring it on real games
showed why that is wrong: of 72 matches in one game, **zero** were real lookups.
They were coincidences — a character's name inside a comment describing the
area, or inside a `D_TEXT` plugin command that is itself dialogue. Freezing 55
to 126 names per game to prevent nothing is a bad trade.

So only an explicit comparison or index counts: `=== "X"`, `["X"]`,
`.includes("X")`. That is the shape a lookup actually has.
"""
from __future__ import annotations
import json
import re
from pathlib import Path
from typing import Any

#: Event commands whose parameters are code rather than text.
_CODE_COMMANDS = {355, 655, 111, 122, 356, 357}

#: A string literal being compared against, or used as a key.
_LOOKUP_PATTERNS = (
    re.compile(r"[=!]==?\s*[\"']([^\"']{2,80})[\"']"),
    re.compile(r"[\"']([^\"']{2,80})[\"']\s*[=!]==?"),
    re.compile(r"\[\s*[\"']([^\"']{2,80})[\"']\s*\]"),
    re.compile(r"\.(?:includes|indexOf|startsWith|endsWith|match)\("
               r"\s*[\"']([^\"']{2,80})[\"']"),
    re.compile(r"\bcase\s+[\"']([^\"']{2,80})[\"']"),
)


class ReferenceGuard:
    """Knows which strings the game's own code looks up by value."""

    def __init__(self, looked_up: set[str]) -> None:
        self.looked_up = looked_up

    def is_referenced(self, text: str) -> bool:
        return bool(text) and text.strip() in self.looked_up

    def __len__(self) -> int:
        return len(self.looked_up)


def build(data_dir: Path) -> ReferenceGuard:
    """Collect every literal the game compares against or indexes with."""
    looked_up: set[str] = set()

    def scan(text: str) -> None:
        for pattern in _LOOKUP_PATTERNS:
            for match in pattern.finditer(text):
                value = match.group(1).strip()
                if len(value) >= 2:
                    looked_up.add(value)

    def walk(obj: Any) -> None:
        if isinstance(obj, list):
            for item in obj:
                walk(item)
        elif isinstance(obj, dict):
            note = obj.get("note")
            if isinstance(note, str) and note:
                scan(note)
            if obj.get("code") in _CODE_COMMANDS:
                for param in obj.get("parameters") or []:
                    if isinstance(param, str):
                        scan(param)
                    elif isinstance(param, list):
                        for sub in param:
                            if isinstance(sub, str):
                                scan(sub)
            for value in obj.values():
                walk(value)

    for path in sorted(Path(data_dir).glob("*.json")):
        try:
            walk(json.loads(path.read_text(encoding="utf-8-sig")))
        except Exception:
            continue
    return ReferenceGuard(looked_up)


def build_from_sources(sources: list[str]) -> ReferenceGuard:
    """Build a guard from raw code text (used for RGSS script archives)."""
    looked_up: set[str] = set()
    guard = ReferenceGuard(looked_up)
    for text in sources:
        for pattern in _LOOKUP_PATTERNS:
            for match in pattern.finditer(text):
                value = match.group(1).strip()
                if len(value) >= 2:
                    looked_up.add(value)
    return guard
