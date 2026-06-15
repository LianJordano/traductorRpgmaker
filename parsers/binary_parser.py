"""Parse RPG Maker 2000/2003 binary files (LMU, LDB, LMT).

Format reference: EasyRPG project LCF specification.
Each file starts with a magic header, followed by chunks.
Each chunk: BER-encoded ID + BER-encoded size + data bytes.
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional

# Signatures expected at the start of each file type
SIGNATURES = {
    "ldb": b"\x0b\x00LcfDataBase",
    "lmu": b"\x0a\x00LcfMapUnit",
    "lmt": b"\x0b\x00LcfMapTree",
}


class BinaryReader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def remaining(self) -> int:
        return len(self.data) - self.pos

    def read_byte(self) -> int:
        b = self.data[self.pos]
        self.pos += 1
        return b

    def read_bytes(self, n: int) -> bytes:
        chunk = self.data[self.pos : self.pos + n]
        self.pos += n
        return chunk

    def read_ber(self) -> int:
        """Read a BER (Base-128 Variable Length) encoded integer."""
        result = 0
        while self.pos < len(self.data):
            b = self.read_byte()
            result = (result << 7) | (b & 0x7F)
            if not (b & 0x80):
                break
        return result

    def read_string(self) -> str:
        length = self.read_ber()
        raw = self.read_bytes(length)
        for enc in ("utf-8", "cp932", "shift_jis", "latin-1"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return raw.decode("latin-1", errors="replace")

    def read_chunk(self) -> Optional[tuple[int, bytes]]:
        """Read one chunk: (chunk_id, chunk_data). Returns None at end marker."""
        if self.remaining() < 1:
            return None
        chunk_id = self.read_ber()
        if chunk_id == 0:
            return None  # end of section
        size = self.read_ber()
        data = self.read_bytes(size)
        return chunk_id, data

    def skip_header(self, file_type: str) -> bool:
        """Skip the LCF file signature. Returns True if valid."""
        sig = SIGNATURES.get(file_type.lower())
        if sig is None:
            return False
        if self.data[: len(sig)] == sig:
            self.pos = len(sig)
            return True
        return False


class Chunk:
    def __init__(self, chunk_id: int, data: bytes) -> None:
        self.chunk_id = chunk_id
        self.data = data
        self._reader = BinaryReader(data)

    def as_string(self) -> str:
        r = BinaryReader(self.data)
        return r.read_string()

    def as_int(self) -> int:
        r = BinaryReader(self.data)
        return r.read_ber()

    def as_bool(self) -> bool:
        return bool(self.data[0]) if self.data else False

    def sub_reader(self) -> BinaryReader:
        return BinaryReader(self.data)


def read_chunks(reader: BinaryReader) -> list[Chunk]:
    """Read all chunks until the end-of-section marker (ID=0)."""
    chunks = []
    while True:
        result = reader.read_chunk()
        if result is None:
            break
        chunk_id, data = result
        chunks.append(Chunk(chunk_id, data))
    return chunks


def load_file(path: Path) -> Optional[BinaryReader]:
    """Load a binary RPG Maker file and return a positioned reader."""
    ext = path.suffix.lower().lstrip(".")
    try:
        data = path.read_bytes()
        reader = BinaryReader(data)
        reader.skip_header(ext)
        return reader
    except Exception:
        return None
