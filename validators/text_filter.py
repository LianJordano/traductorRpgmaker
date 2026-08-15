"""Filter which strings are translatable game text vs code/metadata."""
from __future__ import annotations
import re
import unicodedata

# File extensions that indicate a resource path, not translatable text
_RESOURCE_EXTS = re.compile(
    r"\.(png|jpg|jpeg|bmp|gif|webp|ogg|wav|mp3|m4a|mid|midi|"
    r"flac|opus|aac|mp4|webm|ogv|js|json|csv|txt|rxdata|rvdata|rvdata2|"
    r"lmu|ldb|lmt|exe|dll|so)$",
    re.IGNORECASE,
)

# Common placeholders / variable references
_VARIABLE_RE = re.compile(r"^\s*[\$@]{1,2}[\w.]+\s*$")

# Looks like a hex color
_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{3,8}$")

# Looks like a purely numeric / symbol string
_NUMERIC_ONLY = re.compile(r"^[\d\s.,\-+%:/\\*()_]+$")

# HTML/BBCode tags only
_TAGS_ONLY = re.compile(r"^(\s*<[^>]+>\s*)+$")

# RPG Maker escape codes and plugin notetags — stripped before deciding whether
# anything translatable is left. Multi-letter codes come first so `\SE[5]` is
# removed whole instead of leaving `E[5]` behind.
_RPG_ESCAPE = re.compile(
    r"<[^\s<>\n][^<>\n]{0,99}>"
    r"|\\[A-Za-z]+\[[^\]\n]{0,40}\]"
    r"|\\[A-Za-z]{2,}"
    r"|\\[A-Za-z!|.><^{}$\\]"
    r"|%\d+"
)

# Scripts / code that must never be sent to a translator. Deliberately narrow:
# these patterns must never fire on ordinary prose, so no bare keyword (`if`,
# `end`, `return`) and no bare `this.` — a line of dialogue really can start
# with "This. " and losing it would drop the whole message.
_LOOKS_LIKE_CODE = re.compile(
    r"^\s*(?:"
    r"[$@][\w.\[\]]+\s*=(?!=)"                     # $game_switches[5] = true
    r"|(?:this|self|window|document)\.\w+\s*\("    # this.SetPict( ... )
    r"|\w+(?:\.\w+)*\([^)]*\)\s*;"                 # MobNameSet("x"); foo.bar(baz);
    r"|def\s+\w+\s*[(\n]"                          # def method(
    r"|(?://|/\*)"                                 # // comment, /* comment
    r")"
)

_CJK_RE = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯ｦ-ﾟ]")


def _has_letter(text: str) -> bool:
    """True if the text contains a real letter in any script.

    The previous character-class approach only recognised ASCII and CJK, so
    accented Latin ("Ábrete"), Cyrillic and Greek text was discarded as
    untranslatable.
    """
    return any(unicodedata.category(ch).startswith("L") for ch in text)


def is_translatable(text: str) -> bool:
    """Return True if this string should be sent for translation."""
    if not text or not isinstance(text, str):
        return False

    t = text.strip()
    if not t:
        return False

    # Pure whitespace / newlines
    if not t.replace("\n", "").replace("\r", "").strip():
        return False

    # Resource file path
    if _RESOURCE_EXTS.search(t):
        return False
    if "/" in t or "\\" in t:
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

    # Script fragments (Ruby/JS) — translating these breaks the game
    if _LOOKS_LIKE_CODE.match(t):
        return False

    # Strip RPG escape codes and notetags, then check what is actually left
    stripped = _RPG_ESCAPE.sub("", t).strip()
    if not stripped:
        return False

    # Must contain at least one real letter
    if not _has_letter(stripped):
        return False

    # A single CJK character is a whole word ("剣" = sword); a single Latin
    # letter almost never is.
    if len(stripped) < 2 and not _CJK_RE.search(stripped):
        return False

    return True


def clean_for_translation(text: str) -> str:
    """Return text with RPG escape codes preserved as placeholders for translation."""
    return text.strip()


def is_likely_japanese(text: str) -> bool:
    """Heuristic: does this text appear to be Japanese?"""
    total = len(text)
    if total == 0:
        return False
    return len(_CJK_RE.findall(text)) / total > 0.2


def filter_entries(texts: list[str]) -> list[tuple[int, str]]:
    """Return (original_index, text) pairs for only translatable entries."""
    return [(i, t) for i, t in enumerate(texts) if is_translatable(t)]
