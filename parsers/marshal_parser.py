"""Parse Ruby Marshal files (.rxdata, .rvdata, .rvdata2) for RPG Maker XP/VX/VXAce."""
from __future__ import annotations
from pathlib import Path
from typing import Any, Optional

try:
    import rubymarshal.reader as _reader
    import rubymarshal.writer as _writer
    from rubymarshal.classes import RubyObject, RubyString, Symbol
    _RUBYMARSHAL_OK = True
except ImportError:
    _RUBYMARSHAL_OK = False
    RubyObject = None
    RubyString = None
    Symbol = None


# Encodings tried, in order, when decoding a Ruby string that carries no
# encoding marker (RPG Maker XP / RGSS1 dumps every string like this).
_BYTES_ENCODINGS = ("utf-8", "cp932", "cp1252", "latin-1")


class BinaryString(str):
    """Text decoded from a Ruby string that was stored as raw bytes.

    RPG Maker XP (Ruby 1.8) dumps strings without an encoding marker, so
    ``rubymarshal`` hands them back as ``bytes``.  Every ``isinstance(x, str)``
    check in the extractors would skip them, which is why XP games used to
    extract nothing.  Decoding into this ``str`` subclass makes them behave like
    normal text while remembering how to turn them back into the exact same
    byte format on write.
    """

    __slots__ = ("source_encoding",)

    def __new__(cls, value: str, source_encoding: str = "utf-8") -> "BinaryString":
        obj = super().__new__(cls, value)
        obj.source_encoding = source_encoding
        return obj


# RPG Maker ships a 32-bit Ruby, where Fixnum is a 31-bit signed value and
# anything larger is a Bignum. rubymarshal instead calls everything up to 40 bits
# a Fixnum, which emits a 5-byte length field — and 32-bit Ruby refuses to read
# a long wider than its own `sizeof(long)`, so the game reports the data file as
# corrupt. Sticking to Ruby's real boundary keeps such files loadable.
_FIXNUM_MAX = 2 ** 30 - 1
_FIXNUM_MIN = -(2 ** 30)


def _is_link_scalar(obj: Any) -> bool:
    """True for values Ruby stores as linkable objects but rubymarshal's writer
    forgets to register (see _LinkSafeWriter)."""
    if isinstance(obj, bool) or obj is None:
        return False
    if isinstance(obj, bytes) or isinstance(obj, float):
        return True
    if _RUBYMARSHAL_OK and isinstance(obj, RubyString):
        return False
    if isinstance(obj, str):
        return True
    # Bignums are linkable; Fixnums are not.
    return isinstance(obj, int) and not (_FIXNUM_MIN <= obj <= _FIXNUM_MAX)


if _RUBYMARSHAL_OK:
    from rubymarshal.constants import TYPE_LINK as _TYPE_LINK

    class _LinkSafeWriter(_writer.Writer):
        """Marshal writer that keeps the object-link table in sync with Ruby's reader.

        Ruby's Marshal format assigns an object-reference id to every value except
        true/false/nil, Fixnums and Symbols — strings, byte buffers, floats and
        Bignums all consume a link slot. Upstream rubymarshal's ``Writer`` forgets
        to register plain ``str``/``bytes``/``float``/``bignum`` (only RubyString,
        list, dict and objects go through ``must_write``). That under-counts the
        link table, so every later back-reference (``TYPE_LINK``) points one or
        more slots too low. Real RPG Maker maps use links for shared objects (e.g.
        the ``RPG::MoveCommand`` instances in a Set-Move-Route event), so the saved
        file becomes unreadable ("invalid link destination") and RPG Maker fails to
        load the map — surfacing as missing-graphic errors and empty ``[]`` choices.

        Scalars are *not* de-duplicated by ``id()`` the way ``must_write`` does it:
        CPython shares the empty ``bytes``/``str`` singletons and interns short
        strings, so identity-keyed de-duplication emits a ``TYPE_LINK`` everywhere
        the original file had a full copy (every BGM/BGS/ME ``@name`` collapsing
        onto one shared Ruby String). Instead each scalar is written out in full,
        except that ``link_hints`` — recorded by :func:`load` from the reader's own
        object table — say how many full copies the source file contained, so a
        genuine back-reference is reproduced as a back-reference. The result is a
        byte-for-byte identical file when nothing was translated.
        """

        def __init__(self, fd, link_hints: Optional[dict] = None) -> None:
            super().__init__(fd)
            # id(obj) -> how many full copies are still owed for this value.
            self._budget: dict[int, int] = dict(link_hints) if link_hints else {}
            # id(obj) -> link slot of the most recent full copy.
            self._slots: dict[int, int] = {}

        def _write_scalar(self, obj, emit) -> None:
            oid = id(obj)
            budget = self._budget.get(oid)
            if budget is not None and budget <= 0:
                slot = self._slots.get(oid)
                if slot is not None:
                    self.fd.write(_TYPE_LINK)
                    self.write_long(slot)
                    return
            index = len(self.objects)
            # Anonymous key: reserves the slot the Ruby reader will allocate
            # without making the value eligible for identity de-duplication.
            self.objects[("\x00scalar", index)] = index
            self._slots[oid] = index
            if budget is not None:
                self._budget[oid] = budget - 1
            emit()

        def write(self, obj):
            if obj is None or obj is True or obj is False or isinstance(obj, Symbol):
                return super().write(obj)
            if isinstance(obj, bytes):
                return self._write_scalar(obj, lambda: _writer.Writer.write_bytes(self, obj))
            if isinstance(obj, str) and not isinstance(obj, RubyString):
                return self._write_scalar(obj, lambda: _writer.Writer.write_string(self, obj))
            if isinstance(obj, float):
                return self._write_scalar(obj, lambda: self.write_float(obj))
            if isinstance(obj, int) and not (_FIXNUM_MIN <= obj <= _FIXNUM_MAX):
                return self._write_scalar(obj, lambda: self._write_bignum(obj))
            return super().write(obj)

        def _write_bignum(self, obj: int) -> None:
            import math
            self.fd.write(_writer.TYPE_BIGNUM)
            self.fd.write(b"-" if obj < 0 else b"+")
            value = abs(obj)
            size = int(math.ceil(value.bit_length() / 16.0))
            self.write_long(size)
            for _ in range(size):
                self.write_short(value % 65536)
                value //= 65536

        def write_float(self, obj):
            """Emit the shortest decimal that round-trips exactly.

            Upstream uses ``%.20g``, which turns 0.05 into
            ``0.050000000000000002776`` — the same double, but longer than what
            Ruby wrote and needlessly different from the original file.
            """
            text = repr(float(obj))
            if text.endswith(".0"):
                text = text[:-2]
            elif text == "inf":
                text = "inf"
            elif text == "-inf":
                text = "-inf"
            elif text == "nan":
                text = "nan"
            encoded = text.encode("utf-8")
            self.fd.write(_writer.TYPE_FLOAT)
            self.write_long(len(encoded))
            self.fd.write(encoded)


def is_available() -> bool:
    return _RUBYMARSHAL_OK


# Remembers, per file, how many full copies of each scalar the source contained
# so :func:`save` can reproduce genuine Marshal back-references. Keyed by path and
# validated by object identity; the root object is kept alive so the recorded
# ``id()`` values can never be recycled by another object.
_LINK_HINTS: "OrderedDict[str, tuple[Any, dict]]" = None  # type: ignore[assignment]
_LINK_HINTS_MAX = 3


def _remember_hints(path: Path, root: Any, objects: list) -> None:
    global _LINK_HINTS
    from collections import OrderedDict
    if _LINK_HINTS is None:
        _LINK_HINTS = OrderedDict()
    counts: dict[int, int] = {}
    for obj in objects:
        if _is_link_scalar(obj):
            counts[id(obj)] = counts.get(id(obj), 0) + 1
    _LINK_HINTS[str(path)] = (root, counts)
    while len(_LINK_HINTS) > _LINK_HINTS_MAX:
        _LINK_HINTS.popitem(last=False)


def _hints_for(path: Path, data: Any) -> Optional[dict]:
    if not _LINK_HINTS:
        return None
    cached = _LINK_HINTS.get(str(path))
    # Identity check: hints are only valid for the exact object graph they were
    # recorded from.
    if cached is not None and cached[0] is data:
        return cached[1]
    return None


def load(path: Path) -> Any:
    """Load a Ruby Marshal file and return the parsed Python object."""
    if not _RUBYMARSHAL_OK:
        raise ImportError("rubymarshal is not installed. Run: pip install rubymarshal")
    with path.open("rb") as f:
        if f.read(1) != b"\x04" or f.read(1) != b"\x08":
            raise ValueError(f"Not a Ruby Marshal 4.8 file: {path}")
        reader = _reader.Reader(f)
        data = reader.read()
        _remember_hints(path, data, reader.objects)
        return data


def loads(data: bytes) -> Any:
    """Parse Marshal data already held in memory."""
    if not _RUBYMARSHAL_OK:
        raise ImportError("rubymarshal is not installed. Run: pip install rubymarshal")
    return _reader.loads(data)


def dumps(data: Any, link_hints: Optional[dict] = None) -> bytes:
    """Serialize a Ruby object to Marshal bytes (see _LinkSafeWriter)."""
    if not _RUBYMARSHAL_OK:
        raise ImportError("rubymarshal is not installed. Run: pip install rubymarshal")
    import io
    buf = io.BytesIO()
    buf.write(b"\x04\x08")
    _LinkSafeWriter(buf, link_hints).write(data)
    return buf.getvalue()


def save(path: Path, data: Any) -> None:
    """Write a Ruby object back to a Marshal file.

    Serializes to memory first and writes via a temporary file, so an error
    part-way through can never leave the game with a truncated data file.
    """
    payload = dumps(data, _hints_for(path, data))
    tmp = path.with_suffix(path.suffix + ".rpgt_tmp")
    tmp.write_bytes(payload)
    tmp.replace(path)


def decode_bytes(raw: bytes) -> BinaryString:
    """Decode a raw Ruby byte string, remembering which encoding worked."""
    for enc in _BYTES_ENCODINGS:
        try:
            return BinaryString(raw.decode(enc), enc)
        except UnicodeDecodeError:
            continue
    # latin-1 never fails, so this is unreachable; kept for safety.
    return BinaryString(raw.decode("latin-1", errors="replace"), "latin-1")


def to_str(value: Any) -> Any:
    """Normalize a Ruby string value to a plain Python str.

    rubymarshal returns RubyString (not a str subclass) for Ruby strings with an
    encoding marker, and plain ``bytes`` for strings without one (all of RPG
    Maker XP). Both are converted here; anything else is returned unchanged.
    """
    if isinstance(value, str):
        return value
    if RubyString is not None and isinstance(value, RubyString):
        return str(value)
    if isinstance(value, bytes):
        return decode_bytes(value)
    return value


def _encode_like(text: str, encoding: str) -> bytes:
    """Encode text back to bytes, degrading gracefully if the target charset
    cannot represent the translation (e.g. Spanish accents in cp932)."""
    for enc in (encoding, "cp1252", "utf-8"):
        try:
            return text.encode(enc)
        except (UnicodeEncodeError, LookupError):
            continue
    return text.encode("utf-8", errors="replace")


def make_string(text: Any, template: Any = None) -> Any:
    """Build a Marshal value for ``text`` that matches ``template``'s format.

    CRITICAL: rubymarshal's writer registers RubyString objects in the Marshal
    object-link table but does NOT register plain Python ``str``. Ruby's reader
    counts every string as a linkable object, so inserting a plain ``str``
    translation shifts every later link index by one and produces a file whose
    back-references are invalid ("invalid link destination"). RPG Maker then
    fails to load the map (missing-graphic / load errors) and choices resolve to
    the wrong object (showing empty ``[]``).

    ``template`` is the value being replaced. When it was raw ``bytes`` (RPG
    Maker XP), the replacement is written back as bytes in the same encoding so
    the file keeps the exact shape RGSS1 expects; otherwise a UTF-8 RubyString
    is produced, mirroring what VX/VX Ace store.
    """
    if not isinstance(text, str):
        return text
    if not _RUBYMARSHAL_OK or RubyString is None:
        return text

    # XP-style raw byte string -> write bytes back in the original encoding.
    if isinstance(template, bytes):
        return _encode_like(text, decode_bytes(template).source_encoding)
    if isinstance(text, BinaryString) and template is None:
        return _encode_like(text, text.source_encoding)
    if isinstance(template, BinaryString):
        return _encode_like(text, template.source_encoding)

    rs = RubyString(str(text))
    if template is not None and isinstance(template, RubyString) and template.attributes:
        # Copy (never share) the original marker so the writer cannot mutate the
        # source object's attribute dict.
        attrs = dict(template.attributes)
        if "encoding" in attrs:
            # A legacy charset (e.g. Shift_JIS) usually cannot represent the
            # translation; UTF-8 is what VX Ace reads natively.
            try:
                str(text).encode(attrs["encoding"].decode())
            except Exception:
                attrs = {"E": True}
        rs.attributes = attrs
    else:
        # Mark as UTF-8 (E: True) — the standard, lossless encoding for
        # translated Unicode text; matches what RPG Maker VX Ace/XP accept.
        rs.attributes = {"E": True}
    return rs


def _ivar_key(attrs: dict, name: str) -> Optional[str]:
    """Return the actual attribute key, accounting for Ruby's '@' prefix."""
    if ("@" + name) in attrs:
        return "@" + name
    if name in attrs:
        return name
    return None


def get_ivar(obj: Any, name: str, default: Any = None) -> Any:
    """Safely get an instance variable from a RubyObject.

    Ruby instance variables are stored with a leading '@' (e.g. '@name').
    """
    if not _RUBYMARSHAL_OK or obj is None:
        return default
    attrs = getattr(obj, "attributes", None)
    if isinstance(attrs, dict):
        key = _ivar_key(attrs, name)
        if key is not None:
            return attrs[key]
    return default


def set_ivar(obj: Any, name: str, value: Any) -> None:
    """Set an instance variable on a RubyObject (writes to the '@'-prefixed key).

    Plain ``str`` values are converted with ``make_string`` using the current
    value as the template, so the replacement keeps the original's byte format
    and the Marshal object-link table stays consistent.
    """
    if not _RUBYMARSHAL_OK or obj is None:
        return
    attrs = getattr(obj, "attributes", None)
    if isinstance(attrs, dict):
        key = _ivar_key(attrs, name) or ("@" + name)
        if isinstance(value, str):
            attrs[key] = make_string(value, attrs.get(key))
        else:
            attrs[key] = value


def clone_command(template: Any, code: int, parameters: list) -> Any:
    """Create a new RPG::EventCommand modelled on an existing one.

    Used when a translation needs more text lines than the original had command
    slots: rather than truncating the text, extra ``401`` commands are appended
    with the same indent as the block they belong to.
    """
    if not _RUBYMARSHAL_OK or template is None:
        return None
    cls = type(template)
    attrs = getattr(template, "attributes", {}) or {}
    indent = attrs.get("@indent", attrs.get("indent", 0))
    try:
        new = cls(getattr(template, "ruby_class_name", "RPG::EventCommand"))
    except TypeError:  # pragma: no cover - defensive
        new = RubyObject(getattr(template, "ruby_class_name", "RPG::EventCommand"))
    new.attributes = {"@code": code, "@indent": indent, "@parameters": parameters}
    return new


def walk_strings(obj: Any, callback, path: str = "") -> None:
    """Recursively walk a Ruby Marshal structure and call callback(path, value) for strings."""
    if isinstance(obj, str):
        callback(path, obj)
    elif isinstance(obj, bytes):
        callback(path, decode_bytes(obj))
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            walk_strings(item, callback, f"{path}[{i}]")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            walk_strings(v, callback, f"{path}.{k}")
    elif _RUBYMARSHAL_OK and hasattr(obj, "ruby_class_name"):
        for k, v in obj.attributes.items():
            walk_strings(v, callback, f"{path}.{k}")
