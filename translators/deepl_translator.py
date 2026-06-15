"""DeepL translation via official Python library."""
from __future__ import annotations

from translators.base import BaseTranslator
from core import logger
from core import config

try:
    import deepl as _deepl
    _DEEPL_OK = True
except ImportError:
    _DEEPL_OK = False

# DeepL language code mapping
LANG_MAP = {
    "es": "ES",
    "en": "EN-US",
    "de": "DE",
    "fr": "FR",
    "it": "IT",
    "ja": "JA",
    "ko": "KO",
    "pt": "PT-BR",
    "ru": "RU",
    "zh": "ZH",
}


class DeepLTranslator(BaseTranslator):
    name = "deepl"

    def __init__(self, source_lang: str = "ja", target_lang: str = "es") -> None:
        super().__init__(source_lang, target_lang)
        self._client = None
        api_key = config.get("deepl_api_key", "")
        if _DEEPL_OK and api_key:
            try:
                self._client = _deepl.Translator(api_key)
            except Exception as exc:
                logger.warning(f"DeepL init failed: {exc}")

    def translate_one(self, text: str) -> str:
        if not _DEEPL_OK:
            raise ImportError("deepl library not installed. Run: pip install deepl")
        if not self._client:
            raise ValueError("DeepL API key not configured")
        if not text.strip():
            return text
        src = LANG_MAP.get(self.source_lang, self.source_lang.upper())
        tgt = LANG_MAP.get(self.target_lang, self.target_lang.upper())
        try:
            result = self._client.translate_text(text, source_lang=src, target_lang=tgt)
            return str(result)
        except Exception as exc:
            logger.warning(f"DeepL error: {exc}")
            raise

    def test_connection(self) -> tuple[bool, str]:
        if not _DEEPL_OK:
            return False, "deepl library not installed"
        if not self._client:
            return False, "API key not configured (Settings → API)"
        try:
            usage = self._client.get_usage()
            chars = usage.character.count if usage.character else 0
            limit = usage.character.limit if usage.character else 0
            return True, f"Connected. Used: {chars:,}/{limit:,} chars"
        except Exception as exc:
            return False, str(exc)
