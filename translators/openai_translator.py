"""OpenAI GPT translation with context-aware prompts for RPG text."""
from __future__ import annotations
from typing import Optional

from translators.base import BaseTranslator
from core import logger, config

try:
    from openai import OpenAI as _OpenAI
    _OPENAI_OK = True
except ImportError:
    _OPENAI_OK = False

SYSTEM_PROMPT = (
    "You are an expert translator specializing in Japanese RPG video games. "
    "Translate the given text from {source} to {target}. "
    "Rules:\n"
    "- Preserve all RPG Maker escape codes like \\C[1], \\N[1], \\V[1] exactly as-is.\n"
    "- Preserve newlines (\\n characters).\n"
    "- Keep character names, item names, and skill names consistent.\n"
    "- Use natural, game-appropriate language.\n"
    "- Return ONLY the translated text, nothing else."
)


class OpenAITranslator(BaseTranslator):
    name = "openai"

    def __init__(self, source_lang: str = "ja", target_lang: str = "es") -> None:
        super().__init__(source_lang, target_lang)
        self._client: Optional[_OpenAI] = None
        self._model = config.get("openai_model", "gpt-4o-mini")
        api_key = config.get("openai_api_key", "")
        if _OPENAI_OK and api_key:
            try:
                self._client = _OpenAI(api_key=api_key)
            except Exception as exc:
                logger.warning(f"OpenAI init failed: {exc}")

    def translate_one(self, text: str) -> str:
        if not _OPENAI_OK:
            raise ImportError("openai library not installed. Run: pip install openai")
        if not self._client:
            raise ValueError("OpenAI API key not configured")
        if not text.strip():
            return text

        lang_names = {"ja": "Japanese", "es": "Spanish", "en": "English",
                      "fr": "French", "de": "German", "pt": "Portuguese"}
        src_name = lang_names.get(self.source_lang, self.source_lang)
        tgt_name = lang_names.get(self.target_lang, self.target_lang)

        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT.format(
                        source=src_name, target=tgt_name
                    )},
                    {"role": "user", "content": text},
                ],
                max_tokens=2048,
                temperature=0.3,
            )
            return response.choices[0].message.content.strip()
        except Exception as exc:
            logger.warning(f"OpenAI error: {exc}")
            raise

    def test_connection(self) -> tuple[bool, str]:
        if not _OPENAI_OK:
            return False, "openai library not installed"
        if not self._client:
            return False, "API key not configured"
        try:
            result = self.translate_one("Hello")
            return True, f"OK – model: {self._model}, result: '{result}'"
        except Exception as exc:
            return False, str(exc)
