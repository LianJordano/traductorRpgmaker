"""Find the display strings inside a Ruby script, and only those.

RGSS scripts are the only place VX/VX Ace/XP games can put custom menu text, so
translating them is worthwhile — but a Ruby string literal is just as likely to
be a hash key, a filename or a value the script compares against. Getting that
wrong does not produce a visible typo, it silently changes what the script does.

Two rules keep this safe:

* A candidate must contain non-Latin script. Every identifier, filename, symbol
  and keyword in a Japanese game's scripts is ASCII, so requiring CJK removes
  that whole class of false positives at a stroke.
* The surrounding code must not use the literal as data. A string that is
  compared, used as a hash key, indexed with, or passed to `require` is refused
  even when it looks like a sentence.

Anything the scanner cannot read confidently — heredocs, `%w[]` lists, regex
literals — is skipped rather than guessed at.
"""
from __future__ import annotations
import re
from dataclasses import dataclass

from validators.text_filter import is_translatable

_CJK = re.compile(r"[぀-ヿ㐀-䶿一-鿿ｦ-ﾟ]")


@dataclass
class RubyString:
    start: int
    end: int
    quote: str
    value: str      # decoded text, as the running script would hold it
    raw: str = ""   # the literal body exactly as written in the source


# Escapes Ruby honours inside a double-quoted string. `#{...}` is not an escape
# and must survive untouched so interpolation keeps working.
_DQ_ESCAPES = {
    "n": "\n", "t": "\t", "r": "\r", "s": " ", "0": "\0",
    "e": "\x1b", "a": "\a", "b": "\b", "f": "\f", "v": "\v",
    '"': '"', "'": "'", "\\": "\\", "#": "#",
}


def decode(raw: str, quote: str) -> str:
    """Turn a literal body into the text the script actually holds."""
    if quote == "'":
        out = []
        i = 0
        while i < len(raw):
            if raw[i] == "\\" and i + 1 < len(raw) and raw[i + 1] in "\\'":
                out.append(raw[i + 1])
                i += 2
            else:
                out.append(raw[i])
                i += 1
        return "".join(out)

    out = []
    i = 0
    n = len(raw)
    while i < n:
        if raw[i] != "\\" or i + 1 >= n:
            out.append(raw[i])
            i += 1
            continue
        nxt = raw[i + 1]
        if nxt in _DQ_ESCAPES:
            out.append(_DQ_ESCAPES[nxt])
            i += 2
            continue
        if nxt == "u":
            if i + 2 < n and raw[i + 2] == "{":
                close = raw.find("}", i + 3)
                if close != -1:
                    try:
                        out.append("".join(chr(int(c, 16))
                                           for c in raw[i + 3:close].split()))
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
            m = re.match(r"[0-9A-Fa-f]{1,2}", raw[i + 2:])
            if m:
                out.append(chr(int(m.group(0), 16)))
                i += 2 + len(m.group(0))
                continue
        # Ruby drops the backslash of an unknown escape: "\G" is "G". RPG Maker
        # writes its own codes as "\\G" precisely so the string keeps one, so
        # following Ruby here reproduces what the running game actually holds.
        out.append(nxt)
        i += 2
    return "".join(out)


# Code before the literal that means the string is being used as data.
_DATA_BEFORE = re.compile(
    r"(?:==|!=|<=>|===|=~|\+=|<<)\s*$"
    r"|\b(?:when|case|require|require_relative|load|include\?|index|split"
    r"|start_with\?|end_with\?|match|match\?|sub|sub!|gsub|gsub!|scan|count"
    r"|send|public_send|method|respond_to\?|instance_variable_get"
    r"|instance_variable_set|const_get|const_set|attr_accessor|attr_reader"
    r"|attr_writer|define_method|eval|instance_eval|class_eval)\s*[(\s]\s*$"
    r"|[\[{,]\s*$"
    r"|:\s*$"
)

# Code after the literal that means the same.
_DATA_AFTER = re.compile(
    r"^\s*(?:=>|==|!=|===|=~|\]|\.include\?|\.index|\.to_sym|\.intern)"
)

# `OK:LNX09_アニメーション速度変更` — a registration key, not a sentence.
_TAGGED_KEY = re.compile(r"^[A-Za-z0-9_]{1,20}\s*:")

# Paths and resource names. A bare backslash does not count: RPG Maker display
# text is full of them (`"%s\\G 手に入れた"`, `"\\C[1]"`), and rejecting on that
# alone threw away the game's own vocabulary strings.
_PATHLIKE = re.compile(
    r"^\S*/\S*$"
    r"|\.(?:png|jpg|jpeg|bmp|gif|webp|ogg|wav|mp3|m4a|mid|midi|flac"
    r"|json|js|txt|csv|rvdata2?|rxdata|rb)$",
    re.IGNORECASE,
)


def scan(source: str) -> list[RubyString]:
    """Return every plain single- or double-quoted literal in the source.

    Comments, heredocs, percent literals and regexes are skipped, so a literal
    inside one of them is never reported.
    """
    out: list[RubyString] = []
    i = 0
    n = len(source)
    line_start = True

    while i < n:
        ch = source[i]

        # `=begin` / `=end` block comments must start a line.
        if line_start and source.startswith("=begin", i):
            end = source.find("\n=end", i)
            i = n if end == -1 else end + 5
            line_start = False
            continue

        if ch == "\n":
            line_start = True
            i += 1
            continue
        if ch in " \t":
            i += 1
            continue
        line_start = False

        if ch == "#":
            nl = source.find("\n", i)
            i = n if nl == -1 else nl
            continue

        # Percent literals and heredocs: opaque, skip to a safe point.
        if ch == "%" and i + 1 < n and source[i + 1] in "wWiIqQ({[<|!":
            i = _skip_percent(source, i)
            continue
        if source.startswith("<<~", i) or source.startswith("<<-", i) or (
            source.startswith("<<", i) and i + 2 < n and (source[i + 2].isupper() or source[i + 2] in "'\"")
        ):
            i = _skip_heredoc(source, i)
            continue

        # A regex literal can contain quotes; skip it whole.
        if ch == "/" and _regex_position(source, i):
            i = _skip_regex(source, i)
            continue

        if ch in "\"'":
            quote = ch
            j = i + 1
            while j < n:
                if source[j] == "\\":
                    j += 2
                    continue
                if source[j] == quote:
                    break
                if source[j] == "\n" and quote == "'":
                    break
                j += 1
            if j >= n:
                break
            raw = source[i + 1:j]
            out.append(RubyString(i, j + 1, quote, decode(raw, quote), raw))
            i = j + 1
            continue

        i += 1

    return out


def _skip_percent(source: str, i: int) -> int:
    openers = {"(": ")", "[": "]", "{": "}", "<": ">"}
    k = i + 1
    while k < len(source) and source[k].isalpha():
        k += 1
    if k >= len(source):
        return len(source)
    opener = source[k]
    closer = openers.get(opener, opener)
    depth = 1
    k += 1
    while k < len(source):
        if source[k] == "\\":
            k += 2
            continue
        if source[k] == opener and closer != opener:
            depth += 1
        elif source[k] == closer:
            depth -= 1
            if depth == 0:
                return k + 1
        k += 1
    return len(source)


def _skip_heredoc(source: str, i: int) -> int:
    m = re.match(r"<<[~-]?['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?", source[i:])
    if not m:
        return i + 2
    tag = m.group(1)
    end = re.search(r"^\s*" + re.escape(tag) + r"\s*$", source[i:], re.MULTILINE)
    return len(source) if not end else i + end.end()


def _regex_position(source: str, i: int) -> bool:
    """Heuristic: is this `/` starting a regex rather than a division?"""
    k = i - 1
    while k >= 0 and source[k] in " \t":
        k -= 1
    if k < 0:
        return True
    prev = source[k]
    if prev.isalnum() or prev in ")]_":
        return False           # `a / b`, `foo() / 2`
    return True


def _skip_regex(source: str, i: int) -> int:
    k = i + 1
    n = len(source)
    while k < n:
        if source[k] == "\\":
            k += 2
            continue
        if source[k] == "\n":
            return i + 1       # not a regex after all
        if source[k] == "/":
            k += 1
            while k < n and source[k].isalpha():
                k += 1
            return k
        k += 1
    return n


def is_display_text(source: str, item: RubyString) -> bool:
    """True if this literal is text a player sees rather than script data."""
    value = item.value
    if not value or not _CJK.search(value):
        return False
    if _TAGGED_KEY.match(value):
        return False
    if _PATHLIKE.search(value):
        return False
    if not is_translatable(value):
        return False

    before = source[max(0, item.start - 80):item.start]
    after = source[item.end:item.end + 40]

    # A symbol written as :"..." is an identifier.
    if before.rstrip().endswith(":") and not before.rstrip().endswith("::"):
        return False
    if _DATA_BEFORE.search(before):
        return False
    if _DATA_AFTER.match(after):
        return False
    # `hash["キー"]` — an index, not a message.
    if before.rstrip().endswith("[") and after.lstrip().startswith("]"):
        return False
    return True


def replace(source: str, edits: list[tuple[int, int, str]]) -> str:
    """Apply (start, end, replacement) edits from right to left."""
    out = source
    for start, end, replacement in sorted(edits, key=lambda e: -e[0]):
        out = out[:start] + replacement + out[end:]
    return out


def encode(value: str, quote: str) -> str:
    """Re-encode text as a Ruby literal of the same quoting style."""
    if quote == "'":
        # Single quotes only honour \' and \\.
        body = value.replace("\\", "\\\\").replace("'", "\\'")
        return "'" + body + "'"
    # `#{...}` is left alone on purpose: escaping it would turn a working
    # interpolation into the literal characters, so a name or number the script
    # substitutes at runtime would stop appearing.
    body = (value.replace("\\", "\\\\")
                 .replace('"', '\\"')
                 .replace("\n", "\\n")
                 .replace("\t", "\\t"))
    return '"' + body + '"'
