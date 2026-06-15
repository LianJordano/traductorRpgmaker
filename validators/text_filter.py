"""Filter which strings are translatable game text vs code/metadata."""
from __future__ import annotations
import re

# File extensions that indicate a resource path, not translatable text
_RESOURCE_EXTS = re.compile(
    r"\.(png|jpg|jpeg|bmp|gif|webp|ogg|wav|mp3|m4a|mid|midi|"
    r"flac|opus|aac|mp4|webm|ogv|js|json|csv|txt|rxdata|rvdata|rvdata2|"
    r"lmu|ldb|lmt|exe|dll|so)$",
    re.IGNORECASE,
)

# Strings that are purely RPG Maker control codes / escape sequences
_CONTROL_ONLY = re.compile(
    r"^(\\[A-Za-z]\[[\d,]*\]|\\[A-Za-z]|\s|[^\w　-鿿一-鿿])*$"
)

# Common placeholders / variable references
_VARIABLE_RE = re.compile(r"^\s*[\$@]{1,2}[\w.]+\s*$")

# Looks like a hex color
_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{3,8}$")

# Contains at least one actual letter (Latin or CJK)
_HAS_LETTER = re.compile(r"[A-Za-z　-鿿一-鿿぀-ヿ가-힯]")

# Looks like a purely numeric / symbol string
_NUMERIC_ONLY = re.compile(r"^[\d\s.,\-+%:/\\*()_]+$")

# HTML/BBCode tags only
_TAGS_ONLY = re.compile(r"^(\s*<[^>]+>\s*)+$")

# RPG Maker escape codes (for cleaning, not exclusion alone)
_RPG_ESCAPE = re.compile(r"\\[A-Za-z](?:\[\d+\])?")

MIN_CHARS_AFTER_STRIP = 2


def is_translatable(text: str) -> bool:
    """Return True if this string should be sent for translation."""
    if not text or not isinstance(text, str):
        return False

    t = text.strip()
    if len(t) < 1:
        return False

    # Pure whitespace / newlines
    if not t.replace("\n", "").replace("\r", "").strip():
        return False

    # Resource file path
    if _RESOURCE_EXTS.search(t):
        return False
    if "/" in t or "\\" in t:
        # Might be a path; if no letters after stripping path separators, skip
        base = re.split(r"[/\\]", t)[-1]
        if _RESOURCE_EXTS.search(base):
            return False

    # Hex color
    if _HEX_COLOR.match(t):
        return False

    # Variable reference
    if _VARIABLE_RE.match(t):
        return False

    # Only digits and symbols
    if _NUMERIC_ONLY.match(t):
        return False

    # Only HTML/BBCode tags
    if _TAGS_ONLY.match(t):
        return False

    # Strip RPG escape codes and check what remains
    stripped = _RPG_ESCAPE.sub("", t).strip()
    if len(stripped) < MIN_CHARS_AFTER_STRIP:
        return False

    # Must contain at least one real letter
    if not _HAS_LETTER.search(stripped):
        return False

    return True


def clean_for_translation(text: str) -> str:
    """Return text with RPG escape codes preserved as placeholders for translation."""
    return text.strip()


def is_likely_japanese(text: str) -> bool:
    """Heuristic: does this text appear to be Japanese?"""
    jp = re.compile(r"[぀-ヿ一-鿿]")
    total = len(text)
    if total == 0:
        return False
    jp_chars = len(jp.findall(text))
    return jp_chars / total > 0.2


def filter_entries(texts: list[str]) -> list[tuple[int, str]]:
    """Return (original_index, text) pairs for only translatable entries."""
    return [(i, t) for i, t in enumerate(texts) if is_translatable(t)]
