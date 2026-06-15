"""Detect and validate file encodings."""
from __future__ import annotations
from pathlib import Path
from typing import Optional

try:
    import chardet
    _CHARDET = True
except ImportError:
    _CHARDET = False

JAPANESE_ENCODINGS = ["shift_jis", "shift-jis", "cp932", "euc-jp", "iso-2022-jp"]
UTF_ENCODINGS = ["utf-8", "utf-8-sig", "utf-16", "utf-16-le", "utf-16-be"]


def detect_encoding(path: Path) -> str:
    """Best-effort encoding detection for a file."""
    raw = path.read_bytes()
    # BOM checks first
    if raw.startswith(b"\xff\xfe\x00\x00"):
        return "utf-32-le"
    if raw.startswith(b"\x00\x00\xfe\xff"):
        return "utf-32-be"
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if raw.startswith(b"\xff\xfe"):
        return "utf-16-le"
    if raw.startswith(b"\xfe\xff"):
        return "utf-16-be"

    if _CHARDET:
        result = chardet.detect(raw[:8192])
        if result and result.get("confidence", 0) > 0.7:
            enc = result["encoding"] or "utf-8"
            return enc.lower()

    # Try UTF-8, then CP932 (Japanese Windows)
    for enc in ("utf-8", "cp932", "latin-1"):
        try:
            raw.decode(enc)
            return enc
        except (UnicodeDecodeError, LookupError):
            continue

    return "latin-1"


def read_text_safe(path: Path, encoding: Optional[str] = None) -> str:
    """Read a text file, falling back through encodings."""
    if encoding:
        try:
            return path.read_text(encoding=encoding, errors="replace")
        except Exception:
            pass

    detected = detect_encoding(path)
    try:
        return path.read_text(encoding=detected, errors="replace")
    except Exception:
        return path.read_text(encoding="latin-1", errors="replace")


def is_binary(path: Path) -> bool:
    """Quick check if a file looks binary."""
    try:
        chunk = path.read_bytes()[:1024]
        return b"\x00" in chunk[:512] and not path.suffix.lower() in (
            ".rxdata", ".rvdata", ".rvdata2", ".lmu", ".ldb", ".lmt"
        )
    except Exception:
        return False
