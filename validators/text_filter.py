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


# --------------------------------------------------------------------------- #
# Plugin parameter values
# --------------------------------------------------------------------------- #

# A plugin's `parameters` object mixes text the player reads with values the
# plugin's own code depends on. Translating a configuration value silently
# changes behaviour — a font stack, an alignment keyword or a file path stops
# resolving — so only values that clearly read as prose are accepted.

# Single bare token: `png`, `left`, `GameFont`, `true`.
_SINGLE_TOKEN = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\-]*$")
# Numbers, percentages, key codes, coordinate pairs.
_CONFIG_NUMBER = re.compile(r"^[-+]?\d+(?:\.\d+)?%?$")
_BOOLEAN_LIKE = {"true", "false", "on", "off", "null", "none", "undefined", "yes", "no"}

# Plugins routinely express a boolean or an enum in Japanese and then compare the
# parameter against that exact literal (`if (param === 'いいえ')`). Translating
# one silently flips the setting, so the whole vocabulary is refused.
_ENUM_WORDS = {
    "はい", "いいえ", "オン", "オフ", "有効", "無効", "する", "しない",
    "あり", "なし", "表示", "非表示", "使用する", "使用しない", "使用",
    "左", "右", "中央", "上", "下", "中", "前", "後", "縦", "横",
    "通常", "自動", "手動", "常時", "無し", "有り", "全て", "個別",
    "左寄せ", "右寄せ", "中央寄せ", "デフォルト", "カスタム",
    "enable", "disable", "enabled", "disabled", "auto", "manual",
    "default", "custom", "always", "never", "center", "middle",
}

# A comma-separated list with no spaces at all is an identifier or alias list
# (`particle,パーティクル` registers a plugin command under both names), not a
# sentence a player reads.
_ALIAS_LIST = re.compile(r"^[^\s,]+(?:,[^\s,]+)+$")
# CSS-ish values that must survive untouched.
_CSS_VALUE = re.compile(
    r"sans-serif|monospace|\bserif\b|cursive|fantasy|rgba?\(|^#[0-9A-Fa-f]{3,8}$",
    re.IGNORECASE,
)
# A comma-separated list of plain tokens: font stacks, id lists, key names.
_TOKEN_LIST = re.compile(r"^[A-Za-z0-9 ,._\-]+$")
# Script or template fragments.
_SCRIPT_FRAGMENT = re.compile(r"\$game|\bthis\.|=>|\$\{|\bfunction\b|;\s*$|\breturn\b")

# Many plugins accept a JavaScript expression where a plain value would fit —
# `Graphics.boxWidth - 350`, `f * 0.4`, `Input.isPressed('control') && ...`.
# These read as text to a naive filter, and translating one breaks the plugin.
# A dotted identifier chain (no spaces around the dot, lowercase continuation)
# is the reliable tell, since prose puts a space after a full stop.
_DOTTED_IDENTIFIER = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*\.[a-z_$][A-Za-z0-9_$]+")
# Operators applied between identifiers or numbers.
_EXPRESSION_OP = re.compile(
    r"&&|\|\||[=!]==|[\w)\]]\s*[*/]\s*[\w(]|[\w)\]]\s{0,3}[+\-]\s{0,3}[\w(]"
)
# Anything with a path separator or a file extension.
_PATHLIKE = re.compile(r"[/\\]|\.[A-Za-z0-9]{2,4}$")


def is_plugin_value_translatable(value: str) -> bool:
    """True if a plugin parameter value is text the player reads.

    Deliberately conservative: a value is only accepted when it reads as a
    phrase (contains a space or sentence punctuation) or contains non-Latin
    script, which is what distinguishes `"描画FPSの設定"` and `"A lotta"` from
    `"png"`, `"left"` and `"SimHei, Heiti TC, sans-serif"`.
    """
    if not value or not isinstance(value, str):
        return False
    t = value.strip()
    if len(t) < 2:
        return False
    if t.lower() in _BOOLEAN_LIKE or t in _ENUM_WORDS or t.lower() in _ENUM_WORDS:
        return False
    if _ALIAS_LIST.match(t):
        return False
    if _CONFIG_NUMBER.match(t):
        return False
    if _CSS_VALUE.search(t):
        return False
    if _SCRIPT_FRAGMENT.search(t):
        return False
    if _DOTTED_IDENTIFIER.search(t) or _EXPRESSION_OP.search(t):
        return False
    if _PATHLIKE.search(t):
        return False
    if _SINGLE_TOKEN.match(t):
        return False
    if "," in t and _TOKEN_LIST.match(t):
        return False
    if not is_translatable(t):
        return False
    # Must read as prose: a phrase, a sentence, or non-Latin script.
    if _CJK_RE.search(t):
        return True
    if any(ord(ch) > 0x2000 and not _CJK_RE.match(ch) for ch in t):
        # Cyrillic, Greek, Hangul and other non-Latin scripts.
        if any(unicodedata.category(ch).startswith("L") and ord(ch) > 0x2FF for ch in t):
            return True
    return bool(re.search(r"\s", t) or re.search(r"[.!?…:;、。！？]", t))


# --------------------------------------------------------------------------- #
# Per-string source language
# --------------------------------------------------------------------------- #

_KANA = re.compile(r"[\u3040-\u30ff]")
_HAN = re.compile(r"[\u4e00-\u9fff]")
_HANGUL = re.compile(r"[\uac00-\ud7af]")
_CYRILLIC = re.compile(r"[\u0400-\u04ff]")


def detect_source_language(text: str, configured: str) -> str:
    """Pick the language to translate this particular string from.

    A game is rarely all one language: partially translated releases leave
    Japanese menus inside an otherwise English game. Asking Google to translate
    Japanese "from English" either errors or hands the text straight back
    untranslated, so each string is routed by the script it is actually written
    in and only falls back to the configured source when there is no signal.
    """
    if _KANA.search(text):
        return "ja"
    if _HANGUL.search(text):
        return "ko"
    if _CYRILLIC.search(text):
        return "ru"
    if _HAN.search(text):
        # Han characters alone are shared by Japanese and Chinese; trust the
        # configured language when it is one of them.
        return configured if configured.startswith(("ja", "zh")) else "ja"
    return configured
