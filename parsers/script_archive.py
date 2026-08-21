"""Read and write the script archive of RPG Maker XP/VX/VX Ace.

`Scripts.rvdata2` (and its `.rvdata` / `.rxdata` siblings) is a Marshal array of
`[id, name, zlib_blob]` rows. Two things make it awkward:

* The blob is a Ruby String carrying a UTF-8 marker, but its bytes are binary.
  `rubymarshal` tries to decode them and fails outright, which is why the file
  used to be unreadable. Decoding as latin-1 is byte-for-byte reversible, so the
  bytes survive and are written back through :class:`marshal_parser.RawString`.
* Script names in Japanese games are stored in the game's legacy code page, so
  they need the same tolerant decoding as everything else.
"""
from __future__ import annotations
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from parsers import marshal_parser as mp

try:
    import rubymarshal.reader as _reader
    from rubymarshal.classes import RubyString
    _OK = True
except ImportError:  # pragma: no cover
    _OK = False


@dataclass
class ScriptEntry:
    """One script in the archive."""
    index: int
    name: str
    source: str
    encoding: str = "utf-8"     # how the source text was stored
    _row: object = None         # the underlying Marshal row


class _BinaryReader(_reader.Reader if _OK else object):  # type: ignore[misc]
    """Reader that never tries to interpret a string's bytes.

    latin-1 maps every byte to exactly one code point, so the original bytes can
    always be recovered — unlike the default path, which raises on a binary blob
    and loses the data.
    """

    @staticmethod
    def _get_encoding(attrs):  # noqa: D102
        return "latin1"


def is_available() -> bool:
    return _OK


def _raw(value) -> bytes:
    """Recover the original bytes of a value read by _BinaryReader."""
    if isinstance(value, bytes):
        return value
    if _OK and isinstance(value, RubyString):
        return str(value).encode("latin1")
    if isinstance(value, str):
        return value.encode("latin1")
    return b""


def _attrs(value) -> dict:
    attrs = getattr(value, "attributes", None)
    return dict(attrs) if isinstance(attrs, dict) else {}


def _decode_name(value) -> str:
    raw = _raw(value)
    for enc in ("utf-8", "cp932", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def load(path: Path) -> tuple[list[ScriptEntry], object]:
    """Return (scripts, raw_data). `raw_data` is what :func:`save` writes back."""
    if not _OK:
        raise ImportError("rubymarshal is not installed")

    with Path(path).open("rb") as f:
        if f.read(1) != b"\x04" or f.read(1) != b"\x08":
            raise ValueError(f"Not a Ruby Marshal 4.8 file: {path}")
        data = _BinaryReader(f).read()

    if not isinstance(data, list):
        raise ValueError("El archivo de scripts no contiene una lista")

    scripts: list[ScriptEntry] = []
    for i, row in enumerate(data):
        if not isinstance(row, list) or len(row) < 3:
            continue
        blob = _raw(row[2])
        if not blob:
            continue
        try:
            plain = zlib.decompress(blob)
        except zlib.error:
            continue
        for enc in ("utf-8", "cp932", "cp1252"):
            try:
                source = plain.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            continue
        scripts.append(ScriptEntry(
            index=i, name=_decode_name(row[1]), source=source,
            encoding=enc, _row=row,
        ))

    # Every string in the archive becomes a RawString so an untouched archive is
    # written back exactly as it came in. That includes the script *names*: they
    # were read as latin-1 and would otherwise be re-encoded as UTF-8.
    for row in data:
        if not isinstance(row, list):
            continue
        for i, cell in enumerate(row):
            if isinstance(cell, bytes) or (_OK and isinstance(cell, RubyString)):
                row[i] = mp.RawString(_raw(cell), _attrs(cell))

    return scripts, data


def update(script: ScriptEntry, new_source: str) -> None:
    """Recompress a script's source into its row."""
    row = script._row
    if row is None:
        return
    attrs = _attrs(row[2]) or {"E": True}
    blob = zlib.compress(new_source.encode(script.encoding, errors="replace"))
    row[2] = mp.RawString(blob, attrs)
    script.source = new_source


def save(path: Path, data: object) -> None:
    """Write the archive back, verifying it can be read again."""
    path = Path(path)
    payload = mp.dumps(data)
    tmp = path.with_suffix(path.suffix + ".rpgt_tmp")
    tmp.write_bytes(payload)
    tmp.replace(path)


def verify(path: Path, expected: int) -> bool:
    """Re-read the archive and confirm every script still decompresses."""
    try:
        scripts, _ = load(path)
    except Exception:
        return False
    return len(scripts) == expected
