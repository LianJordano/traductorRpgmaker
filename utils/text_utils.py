"""Text processing utilities."""
from __future__ import annotations
import re

# RPG Maker escape codes: \C[n], \V[n], \N[n], \n, \., \!, etc.
RPG_CODE = re.compile(r"\\[A-Za-z](?:\[\d+\])?")


def extract_rpg_codes(text: str) -> tuple[str, list[tuple[int, str]]]:
    """Replace RPG codes with placeholders; return (clean_text, [(pos, code)])."""
    codes: list[tuple[int, str]] = []
    result = []
    last = 0
    for m in RPG_CODE.finditer(text):
        result.append(text[last:m.start()])
        placeholder = f"{{RPG{len(codes)}}}"
        codes.append((len("".join(result)), m.group()))
        result.append(placeholder)
        last = m.end()
    result.append(text[last:])
    return "".join(result), codes


def restore_rpg_codes(text: str, codes: list[tuple[int, str]]) -> str:
    """Restore RPG codes from placeholders."""
    for i, (_, code) in enumerate(codes):
        text = text.replace(f"{{RPG{i}}}", code)
    return text


# Comprehensive protection: notetags <element:fire>, RPG codes \C[1]\V[10],
# simple codes \n \. \!, and format specifiers %1 %2
_PROTECT_RE = re.compile(
    r"<[^\s<>\n][^<>\n]{0,99}>"         # notetags / inline tags: <ATK:50>, <br>
    r"|\\[A-Za-z]\[[\d,]+\]"             # RPG codes with args: \C[1], \V[10], \SE[5]
    r"|\\[A-Za-z!|.><^{}$\\]"            # all single-char RPG codes: \n \. \| \! \> \< \^ \{ \} \$
    r"|%\d+",                             # format specifiers: %1, %2
    re.IGNORECASE,
)


def protect_game_codes(text: str) -> tuple[str, list[str]]:
    """Replace game-specific codes with stable placeholders before translation.

    Protects RPG Maker escape codes, plugin notetags, and format specifiers so
    translators cannot mangle them.  Returns (protected_text, saved_codes).
    Call restore_game_codes() with the same saved_codes to put them back.
    """
    saved: list[str] = []

    def _sub(m: re.Match) -> str:
        saved.append(m.group(0))
        return f"{{GC{len(saved) - 1}}}"

    return _PROTECT_RE.sub(_sub, text), saved


def restore_game_codes(text: str, saved: list[str]) -> str:
    """Restore game codes saved by protect_game_codes()."""
    for i, code in enumerate(saved):
        text = text.replace(f"{{GC{i}}}", code)
    return text


def split_into_chunks(texts: list[str], max_chars: int = 4000) -> list[list[str]]:
    """Split a list of texts into batches not exceeding max_chars total."""
    batches: list[list[str]] = []
    current: list[str] = []
    current_len = 0
    for text in texts:
        tl = len(text)
        if current_len + tl > max_chars and current:
            batches.append(current)
            current = []
            current_len = 0
        current.append(text)
        current_len += tl
    if current:
        batches.append(current)
    return batches


def sanitize_filename(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', "_", name)
