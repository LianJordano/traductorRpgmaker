"""Abstract base class for all version-specific extractors."""
from __future__ import annotations
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable, Optional

from core.models import ExtractionResult, TextEntry
from validators.text_filter import is_translatable


class BaseExtractor(ABC):
    """Extract translatable texts from a game's data directory."""

    def __init__(
        self,
        data_dir: Path,
        game_dir: Path,
        progress_cb: Optional[Callable[[int, int, str], None]] = None,
        cancel_flag: Optional[Callable[[], bool]] = None,
    ) -> None:
        self.data_dir = data_dir
        self.game_dir = game_dir
        self._progress_cb = progress_cb or (lambda c, t, f: None)
        self._cancel_flag = cancel_flag or (lambda: False)
        self._result: Optional[ExtractionResult] = None

    @property
    @abstractmethod
    def version(self) -> str: ...

    @abstractmethod
    def extract(self) -> ExtractionResult: ...

    @abstractmethod
    def reinsert(self, result: ExtractionResult) -> bool: ...

    def _progress(self, current: int, total: int, file: str = "") -> None:
        self._progress_cb(current, total, file)

    def _cancelled(self) -> bool:
        return self._cancel_flag()

    def _make_entry(
        self,
        file: str,
        context: str,
        text: str,
        index: int,
        metadata: Optional[dict] = None,
    ) -> Optional[TextEntry]:
        if not is_translatable(text):
            return None
        uid = f"{file}::{context}::{index}"
        entry = TextEntry(
            uid=uid,
            file=file,
            context=context,
            original=text,
            metadata=metadata or {},
        )
        # A string the game's own scripts look up by value cannot be renamed
        # without detaching whatever refers to it. Such entries are still
        # extracted and exported — marked `locked`, so they are visible and can
        # be translated by hand — but never sent to the translator.
        guard = getattr(self, "_guard", None)
        if guard is not None and guard.is_referenced(text):
            entry.status = "locked"
            entry.metadata["locked_reason"] = "un script del juego lo consulta por su valor"
            self._locked = getattr(self, "_locked", 0) + 1
        return entry
