"""Google Translate via the deep-translator library (no API key required for basic use)."""
from __future__ import annotations

from translators.base import BaseTranslator
from core import logger

try:
    from deep_translator import GoogleTranslator as _GT
    from deep_translator.exceptions import TranslationNotFound
    _DEEP_TRANSLATOR_OK = True
except ImportError:
    _DEEP_TRANSLATOR_OK = False

    class TranslationNotFound(Exception):  # type: ignore[no-redef]
        pass


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
        # "TranslationNotFound" is raised both for genuinely untranslatable
        # strings (proper nouns, interjections) and for transient hiccups, so it
        # is retried once before accepting the original text. Treating it as a
        # hard error would fail the whole entry; accepting it immediately would
        # silently leave common words untranslated.
        import time
        for attempt in (0, 1):
            try:
                result = self._translator.translate(text)
                return result if result else text
            except TranslationNotFound:
                if attempt == 0:
                    time.sleep(0.5)
                    continue
                return text
            except Exception as exc:
                logger.warning(f"Google Translate error: {exc}")
                raise
        return text

    def test_connection(self) -> tuple[bool, str]:
        if not _DEEP_TRANSLATOR_OK:
            return False, "deep-translator library not installed"
        # Probe with a word in the configured source language, so the check does
        # not fail merely because an English sample is not Japanese.
        probes = {
            "ja": "こんにちは", "zh": "你好", "ko": "안녕하세요",
            "ru": "Привет", "es": "Hola", "fr": "Bonjour",
            "de": "Hallo", "pt": "Olá", "en": "Hello",
        }
        sample = probes.get(self.source_lang, "Hello")
        try:
            result = self.translate_one(sample)
            if not result or result == sample:
                return False, f"Sin respuesta de Google para '{sample}'"
            return True, f"OK – '{sample}' → '{result}'"
        except Exception as exc:
            return False, str(exc)
