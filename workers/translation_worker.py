"""Background thread for API-based translation of extracted texts."""
from __future__ import annotations
import queue
import threading
from typing import Optional

from core import checkpoint, config, logger
from core.models import ExtractionResult, WorkerMessage
from translators.base import BaseTranslator
from utils.text_utils import protect_game_codes, restore_game_codes


def _build_translator(name: str, src: str, tgt: str) -> BaseTranslator:
    if name == "google":
        from translators.google_translator import GoogleTranslator
        return GoogleTranslator(src, tgt)
    elif name == "deepl":
        from translators.deepl_translator import DeepLTranslator
        return DeepLTranslator(src, tgt)
    elif name == "openai":
        from translators.openai_translator import OpenAITranslator
        return OpenAITranslator(src, tgt)
    else:
        from translators.google_translator import GoogleTranslator
        return GoogleTranslator(src, tgt)


class TranslationWorker(threading.Thread):
    def __init__(
        self,
        result: ExtractionResult,
        out_queue: queue.Queue,
        translator_name: Optional[str] = None,
    ) -> None:
        super().__init__(daemon=True, name="TranslationWorker")
        self.result = result
        self.out_queue = out_queue
        self.translator_name = translator_name or config.get("translator", "google")
        self._cancel = threading.Event()
        self._pause = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def pause(self) -> None:
        self._pause.set()

    def resume(self) -> None:
        self._pause.clear()

    def _emit(self, msg: WorkerMessage) -> None:
        self.out_queue.put(msg)

    def _log(self, level: str, text: str) -> None:
        self._emit(WorkerMessage.log(level, text))

    def run(self) -> None:
        try:
            self._run()
        except Exception as exc:
            self._emit(WorkerMessage.error(f"Error de traducción: {exc}"))

    def _run(self) -> None:
        src = config.get("language_from", "en")
        tgt = config.get("language_to", "es")
        delay = config.get("delay_ms", 200)

        # Restore previous checkpoint if available
        if config.get("checkpoint_enabled") and checkpoint.exists(self.result.game_path):
            saved = checkpoint.load(self.result.game_path)
            if saved:
                saved_by_uid = {e["uid"]: e for e in saved.get("entries", [])}
                for entry in self.result.entries:
                    prev = saved_by_uid.get(entry.uid)
                    if prev and prev.get("status") == "translated" and prev.get("translation"):
                        entry.translation = prev["translation"]
                        entry.status = "translated"
                restored = sum(1 for e in self.result.entries if e.status == "translated")
                if restored:
                    self._log("INFO", f"Punto de control restaurado: {restored} textos ya traducidos, continuando desde allí.")

        self._log("INFO", f"Inicializando traductor: {self.translator_name} ({src}→{tgt})")
        try:
            translator = _build_translator(self.translator_name, src, tgt)
        except Exception as exc:
            self._emit(WorkerMessage.error(f"No se pudo inicializar el traductor: {exc}"))
            return

        pending = [e for e in self.result.entries if e.status == "pending"]
        total = len(pending)
        self._log("INFO", f"Traduciendo {total} textos...")

        for done, entry in enumerate(pending):
            # Handle pause
            while self._pause.is_set() and not self._cancel.is_set():
                import time
                time.sleep(0.2)

            if self._cancel.is_set():
                self._log("INFO", "Traducción cancelada.")
                break

            try:
                protected, saved = protect_game_codes(entry.original)
                raw = translator.translate_one(protected)
                entry.translation = restore_game_codes(raw, saved)
                entry.status = "translated"
            except Exception as exc:
                logger.warning(f"Error al traducir '{entry.uid}': {exc}")
                entry.status = "error"

            self._emit(WorkerMessage.progress(done + 1, total, entry.file))

            if (done + 1) % 25 == 0:
                if config.get("checkpoint_enabled"):
                    checkpoint.save(self.result.game_path, self.result.to_dict())

            import time
            time.sleep(delay / 1000)

        # Final checkpoint after loop ends (covers items translated since last periodic save)
        if config.get("checkpoint_enabled"):
            checkpoint.save(self.result.game_path, self.result.to_dict())

        translated = sum(1 for e in self.result.entries if e.status == "translated")
        errors = sum(1 for e in self.result.entries if e.status == "error")
        self._log(
            "SUCCESS",
            f"Traducción completa: {translated} traducidos, {errors} errores.",
        )
        self._emit(WorkerMessage.complete(self.result))
