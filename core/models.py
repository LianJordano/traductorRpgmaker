"""Shared data models used across all modules."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TextEntry:
    """A single translatable text item extracted from a game file."""
    uid: str                          # Unique ID for reinsertion: "file::context::index"
    file: str                         # Relative file path within data_dir
    context: str                      # Human-readable context (e.g. "Actor[1].name")
    original: str                     # Original text
    translation: str = ""             # Translated text (empty = not yet translated)
    status: str = "pending"           # pending | translated | ignored | error
    metadata: dict = field(default_factory=dict)  # Extra data needed for reinsertion

    def to_dict(self) -> dict:
        return {
            "uid": self.uid,
            "file": self.file,
            "context": self.context,
            "original": self.original,
            "translation": self.translation,
            "status": self.status,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TextEntry":
        return cls(
            uid=d["uid"],
            file=d["file"],
            context=d["context"],
            original=d["original"],
            translation=d.get("translation", ""),
            status=d.get("status", "pending"),
            metadata=d.get("metadata", {}),
        )


@dataclass
class ExtractionResult:
    """Complete extraction result for a game."""
    game_path: str
    version: str
    entries: list[TextEntry] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.entries)

    @property
    def pending(self) -> int:
        return sum(1 for e in self.entries if e.status == "pending")

    @property
    def translated(self) -> int:
        return sum(1 for e in self.entries if e.status == "translated")

    def to_dict(self) -> dict:
        return {
            "game_path": self.game_path,
            "version": self.version,
            "entries": [e.to_dict() for e in self.entries],
            "errors": self.errors,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ExtractionResult":
        result = cls(
            game_path=d["game_path"],
            version=d["version"],
            errors=d.get("errors", []),
        )
        result.entries = [TextEntry.from_dict(e) for e in d.get("entries", [])]
        return result


@dataclass
class WorkerMessage:
    """Message sent from background workers to the GUI queue."""
    type: str   # 'progress' | 'log' | 'complete' | 'error' | 'stats' | 'file'
    data: dict = field(default_factory=dict)

    @classmethod
    def progress(cls, current: int, total: int, file: str = "") -> "WorkerMessage":
        return cls("progress", {"current": current, "total": total, "file": file})

    @classmethod
    def log(cls, level: str, msg: str) -> "WorkerMessage":
        return cls("log", {"level": level, "msg": msg})

    @classmethod
    def complete(cls, result: Optional[ExtractionResult] = None) -> "WorkerMessage":
        return cls("complete", {"result": result})

    @classmethod
    def error(cls, msg: str) -> "WorkerMessage":
        return cls("error", {"msg": msg})

    @classmethod
    def stats(cls, **kwargs) -> "WorkerMessage":
        return cls("stats", kwargs)

    @classmethod
    def file_found(cls, filename: str, count: int) -> "WorkerMessage":
        return cls("file", {"filename": filename, "count": count})
