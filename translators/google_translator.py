"""Google Translate via the deep-translator library (no API key required for basic use)."""
from __future__ import annotations

from translators.base import BaseTranslator
from core import logger

try:
    from deep_translator import GoogleTranslator as _GT
    _DEEP_TRANSLATOR_OK = True
except ImportError:
    _DEEP_TRANSLATOR_OK = False


class GoogleTranslator(BaseTranslator):
    name = "google"

    def __init__(self, source_lang: str = "ja", target_lang: str = "es") -> None:
        super().__init__(source_lang, target_lang)
        self._translator = None
        if _DEEP_TRANSLATOR_OK:
            self._translator = _GT(source=source_lang, target=target_lang)

    def translate_one(self, text: str) -> str:
        if not _DEEP_TRANSLATOR_OK:
            raise ImportError("deep-translator not installed. Run: pip install deep-translator")
        if not text.strip():
            return text
        try:
            result = self._translator.translate(text)
            return result or text
        except Exception as exc:
            logger.warning(f"Google Translate error: {exc}")
            raise

    def test_connection(self) -> tuple[bool, str]:
        if not _DEEP_TRANSLATOR_OK:
            return False, "deep-translator library not installed"
        try:
            result = self.translate_one("Hello")
            return bool(result), f"OK – test result: '{result}'"
        except Exception as exc:
            return False, str(exc)
