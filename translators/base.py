"""Abstract base translator and batch-translation utilities."""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Optional
import time

from core import logger
from core.models import TextEntry
from utils.text_utils import (
    keep_trailing_conditions,
    protect_game_codes,
    restore_game_codes,
    transfer_outer_spacing,
    translation_is_safe,
)


class TranslationUnavailable(Exception):
    """The backend returned no translation for this text.

    Google reports this both for genuinely untranslatable strings and, crucially,
    while it is throttling. Treating it as success and keeping the original would
    silently leave text untranslated in a run that reports no errors, so it is
    raised and left to the worker to retry with backoff.
    """


class BaseTranslator(ABC):
    name: str = "base"

    def __init__(self, source_lang: str = "ja", target_lang: str = "es") -> None:
        self.source_lang = source_lang
        self.target_lang = target_lang

    @abstractmethod
    def translate_one(self, text: str) -> str:
        """Translate a single string. Raises on unrecoverable errors."""
        ...

    def translate_protected(self, text: str) -> str:
        """Translate one string with game codes shielded and spacing restored.

        Raises ValueError if a code whose loss would change the meaning did not
        survive, so callers can keep the original rather than ship wrong text.
        """
        protected, saved = protect_game_codes(text)
        raw = self.translate_one(protected)
        out = restore_game_codes(raw, saved)
        if not translation_is_safe(out, saved):
            raise ValueError(f"translation dropped game codes: {text!r}")
        return transfer_outer_spacing(text, keep_trailing_conditions(text, out))

    def translate_batch(
        self,
        texts: list[str],
        delay_ms: int = 200,
        progress_cb=None,
    ) -> list[str]:
        """Translate a list of strings, one by one with optional delay."""
        results = []
        for i, text in enumerate(texts):
            try:
                results.append(self.translate_protected(text))
            except Exception as exc:
                logger.error(f"Translation error on text {i}: {exc}")
                results.append(text)  # keep original on error
            if delay_ms > 0:
                time.sleep(delay_ms / 1000)
            if progress_cb:
                progress_cb(i + 1, len(texts))
        return results

    def translate_entries(
        self,
        entries: list[TextEntry],
        batch_size: int = 50,
        delay_ms: int = 200,
        progress_cb=None,
        cancel_flag=None,
    ) -> list[TextEntry]:
        """Translate pending TextEntry objects in place. Returns all entries."""
        pending = [e for e in entries if e.status == "pending"]
        total = len(pending)
        done = 0
        for entry in pending:
            if cancel_flag and cancel_flag():
                break
            try:
                entry.translation = self.translate_protected(entry.original)
                entry.status = "translated"
            except Exception as exc:
                logger.error(f"Failed to translate '{entry.uid}': {exc}")
                entry.status = "error"
            done += 1
            if delay_ms > 0:
                time.sleep(delay_ms / 1000)
            if progress_cb:
                progress_cb(done, total)
        return entries

    @abstractmethod
    def test_connection(self) -> tuple[bool, str]:
        """Return (ok, message) to verify the translator is configured."""
        ...
