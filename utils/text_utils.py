"""Text processing utilities: game-code protection, wrapping and chunking."""
from __future__ import annotations
import re
import unicodedata

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


# Comprehensive protection, in priority order:
#   1. notetags / inline plugin tags: <ATK:50>, <Boy>, <br>
#   2. multi-letter escape codes with arguments: \SE[5], \PX[10], \C[1], \V[10]
#   3. multi-letter escape codes without arguments: \AF, \FS
#   4. single-char escape codes: \n \. \| \! \> \< \^ \{ \} \$ \\
#   5. format specifiers used by RPG Maker terms: %1, %2
# Multi-letter codes MUST be matched before single-letter ones, otherwise `\SE[5]`
# is protected as `\S` and the translator is free to mangle the leftover `E[5]`.
_PROTECT_RE = re.compile(
    r"<[^\s<>\n][^<>\n]{0,99}>"           # notetags / inline tags
    r"|\\[A-Za-z]+\[[^\]\n]{0,40}\]"      # \C[1], \V[10], \SE[5], \N[1]
    r"|\\[A-Za-z]{2,}"                    # \FS, \AF (no argument)
    r"|\\[A-Za-z!|.><^{}$\\]"             # \n \. \| \! \> \< \^ \{ \} \$ \\
    r"|%\d+",                             # format specifiers: %1, %2
)

# Placeholders are written as {GC0}. Machine translators frequently reformat
# them — inserting spaces, changing case, or swapping ASCII braces for their
# full-width CJK equivalents — so the restore side is deliberately tolerant.
_PLACEHOLDER_RE = re.compile(
    r"[{｛\[]\s*[gGｇＧ]\s*[cCｃＣ]\s*[-_ ]?\s*(\d{1,4})\s*[}｝\]]"
)
# Any leftover that still looks like a mangled placeholder, so it never reaches
# the game as visible garbage.
_PLACEHOLDER_DEBRIS_RE = re.compile(r"[{｛\[]\s*[gGｇＧ]\s*[cCｃＣ]\s*[-_ ]?\s*\d{0,4}\s*[}｝\]]?")

# Purely decorative codes: waits, line control, colour, icon, font size and
# text offsets. Losing one of these only changes how a line looks. Everything
# else — actor/party names (\N[1], \P[1]), variable values (\V[10]), plugin
# notetags (<Boy>) and format specifiers (%1) — changes *what the line says*,
# so a translation that dropped one is not safe to ship.
_SINGLE_ESCAPE_RE = re.compile(r"^\\[A-Za-z!|.><^{}$\\]$")
_COSMETIC_BRACKET_RE = re.compile(r"^\\(?:[CI]|FS|OC|OW|PX|PY)\[[^\]]*\]$", re.IGNORECASE)


def _is_cosmetic(code: str) -> bool:
    return bool(_SINGLE_ESCAPE_RE.match(code) or _COSMETIC_BRACKET_RE.match(code))


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
    """Restore game codes saved by protect_game_codes().

    Tolerates the placeholder reformatting machine translators apply, and
    strips any placeholder debris that could not be resolved so the player
    never sees a stray ``{GC2}`` in a dialogue box.
    """
    if not saved:
        return text

    def _sub(m: re.Match) -> str:
        idx = int(m.group(1))
        return saved[idx] if 0 <= idx < len(saved) else ""

    text = _PLACEHOLDER_RE.sub(_sub, text)
    if "GC" in text or "gc" in text:
        text = _PLACEHOLDER_DEBRIS_RE.sub("", text)
    return text


def missing_codes(restored: str, saved: list[str]) -> list[str]:
    """Return the protected codes that did not survive the round trip.

    Compared by occurrence count, so a text that originally held ``\\C[1]``
    twice and came back with one of them is still reported as lossy.
    """
    from collections import Counter
    wanted = Counter(saved)
    missing: list[str] = []
    for code, count in wanted.items():
        present = restored.count(code)
        if present < count:
            missing.extend([code] * (count - present))
    return missing


def translation_is_safe(restored: str, saved: list[str]) -> bool:
    """True when every code whose loss would change the meaning survived.

    A dropped colour code only changes how a line looks; a dropped ``\\N[1]``
    or ``<Boy>`` changes *what it says*, so those force the original text to be
    kept instead of shipping a subtly wrong line.
    """
    return all(_is_cosmetic(code) for code in missing_codes(restored, saved))


def transfer_outer_spacing(original: str, translated: str) -> str:
    """Re-apply the original's leading/trailing whitespace to the translation.

    RPG Maker data is full of strings that start with a space (` Reina`,
    ` Potion`) used for in-menu alignment. Every translation backend trims
    them, which visibly shifts menu text, so they are restored here.
    """
    if not translated:
        return translated
    lead = original[: len(original) - len(original.lstrip())]
    trail = original[len(original.rstrip()):]
    return lead + translated.strip() + trail


# ---------------------------------------------------------------------------
# Message-window layout
# ---------------------------------------------------------------------------

# Width of a message window in half-width character units, and how many lines
# fit before RPG Maker starts a new page.
WINDOW_WIDTH = {"MV/MZ": 55, "VXAce": 50, "VX": 50, "XP": 46}
WINDOW_LINES = 4

# Escape codes that take up no space on screen.
_ZERO_WIDTH_RE = re.compile(r"\\[A-Za-z]+\[[^\]\n]*\]|\\[A-Za-z!|.><^{}$\\]")


def display_width(text: str) -> int:
    """Width of a string in half-width units, ignoring invisible escape codes."""
    visible = _ZERO_WIDTH_RE.sub("", text)
    width = 0
    for ch in visible:
        width += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return width


def wrap_line(line: str, max_width: int) -> list[str]:
    """Wrap one line to max_width half-width units, breaking on spaces.

    Escape codes never count toward the width and stay glued to the word that
    follows them, so a ``\\C[1]`` colour change cannot end up stranded at the
    end of the previous line.
    """
    if max_width <= 0 or display_width(line) <= max_width:
        return [line]

    out: list[str] = []
    current = ""
    for tok, breakable in _tokenize(line):
        if not current:
            current = "" if tok.isspace() else tok
            continue
        if display_width(current + tok) <= max_width:
            current += tok
        elif tok.isspace():
            out.append(current)
            current = ""
        elif breakable:
            out.append(current.rstrip())
            current = tok
        else:
            # No break point here — the text would be cut inside a word.
            # Overflowing slightly beats mangling the sentence.
            current += tok
    if current.strip():
        out.append(current.rstrip())
    return out or [line]


def _tokenize(line: str) -> list[tuple[str, bool]]:
    """Break a line into (atom, may_break_before_it) pairs.

    An atom is a whitespace run, a single CJK character, or a word with any
    escape codes that immediately precede it attached to its front. A word may
    only start a new line when a space or a CJK character came before it —
    otherwise wrapping would split something like ``girl—\\N[2]—alone`` in the
    middle.
    """
    parts: list[tuple[str, bool]] = []
    pos = 0
    for m in _ZERO_WIDTH_RE.finditer(line):
        if m.start() > pos:
            parts.append((line[pos:m.start()], False))
        parts.append((m.group(0), True))
        pos = m.end()
    if pos < len(line):
        parts.append((line[pos:], False))

    atoms: list[tuple[str, bool]] = []
    pending = ""
    prev_allows_break = True

    def push(text: str, is_cjk: bool) -> None:
        nonlocal prev_allows_break
        atoms.append((text, prev_allows_break))
        prev_allows_break = is_cjk

    for chunk, is_code in parts:
        if is_code:
            pending += chunk
            continue
        for tok, is_cjk in _split_words(chunk):
            if tok.isspace():
                if pending:
                    push(pending, False)
                    pending = ""
                atoms.append((tok, True))
                prev_allows_break = True
            else:
                push(pending + tok, is_cjk)
                pending = ""
    if pending:
        push(pending, False)
    return atoms


# Scripts written without spaces, where any character is a valid break point.
_CJK_RUN = re.compile(
    r"[\u3000-\u303f\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff66-\uff9f]+"
)


def _split_words(chunk: str) -> list[tuple[str, bool]]:
    """Split text into (token, is_cjk) pairs, keeping the separating spaces.

    A line can mix scripts ("\u767d\u82b1\u306e\u871c (una traducci\u00f3n\u2026)"). Splitting the whole
    chunk per character just because it contains one kana would break the Latin
    words in half, so each run is tokenised according to its own script.
    """
    if not chunk:
        return []
    out: list[tuple[str, bool]] = []

    def latin(text: str) -> None:
        out.extend((tok, False) for tok in re.findall(r"\s+|\S+", text))

    pos = 0
    for m in _CJK_RUN.finditer(chunk):
        if m.start() > pos:
            latin(chunk[pos:m.start()])
        out.extend((ch, True) for ch in m.group(0))
        pos = m.end()
    if pos < len(chunk):
        latin(chunk[pos:])
    return out


def layout_message(text: str, version: str = "MV/MZ", max_lines: int = WINDOW_LINES) -> list[list[str]]:
    """Lay a translated message block out into pages of at most max_lines lines.

    Returns a list of pages, each a list of display lines. Translations are
    consistently longer than the Japanese original, so without this the extra
    text either runs off the right edge of the window or is dropped entirely.
    """
    width = WINDOW_WIDTH.get(version, 55)
    lines: list[str] = []
    for raw in text.split("\n"):
        if not raw.strip():
            lines.append("")
            continue
        lines.extend(wrap_line(raw, width))
    if not lines:
        lines = [""]
    if max_lines <= 0:
        return [lines]
    return [lines[i:i + max_lines] for i in range(0, len(lines), max_lines)]


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
