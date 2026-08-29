"""Background thread for API-based translation of extracted texts."""
from __future__ import annotations
import queue
import threading
from typing import Optional

from core import checkpoint, config, logger
from core.models import ExtractionResult, WorkerMessage
from validators.text_filter import detect_source_language
from translators.base import BaseTranslator, TranslationUnavailable
from utils.text_utils import (
    keep_trailing_conditions,
    missing_codes,
    protect_game_codes,
    restore_game_codes,
    transfer_outer_spacing,
    translation_is_safe,
)


class UnsafeTranslation(Exception):
    """Raised when a translation lost a code that changes what the text says."""

    def __init__(self, lost: list[str]) -> None:
        super().__init__("lost game codes: " + ", ".join(lost))
        self.lost = lost


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


# Substrings that identify a rate-limit / throttling response from any backend.
_RATE_LIMIT_HINTS = (
    "429", "too many requests", "rate limit", "ratelimit",
    "quota", "throttl", "temporarily", "503", "try again later",
)


def _is_rate_limit(exc: Exception) -> bool:
    """Heuristically detect rate-limiting across deep-translator/DeepL/OpenAI,
    which surface 429s as different exception types and messages."""
    name = type(exc).__name__.lower()
    if "toomanyrequests" in name or "ratelimit" in name:
        return True
    msg = str(exc).lower()
    return any(hint in msg for hint in _RATE_LIMIT_HINTS)


class AdaptiveLimiter:
    """Gates concurrent API calls with a limit that can shrink under rate
    limiting and slowly recover. Acts as a resizable semaphore so the worker
    can back off without tearing down the thread pool."""

    def __init__(self, initial: int, minimum: int = 1) -> None:
        self._cond = threading.Condition()
        self._limit = max(minimum, initial)
        self._min = minimum
        self._in_use = 0
        self._ok_streak = 0

    @property
    def limit(self) -> int:
        return self._limit

    def acquire(self) -> None:
        with self._cond:
            while self._in_use >= self._limit:
                self._cond.wait()
            self._in_use += 1

    def release(self) -> None:
        with self._cond:
            self._in_use -= 1
            self._cond.notify()

    def decrease(self) -> Optional[int]:
        """Halve the allowed concurrency. Returns the new limit if it changed."""
        with self._cond:
            self._ok_streak = 0
            new = max(self._min, self._limit // 2)
            if new != self._limit:
                self._limit = new
                return new
            return None

    def on_success(self, cap: int) -> Optional[int]:
        """Count a success; after a healthy streak, raise the limit by one
        toward `cap`. Returns the new limit if it changed."""
        with self._cond:
            self._ok_streak += 1
            if self._ok_streak >= 25 and self._limit < cap:
                self._ok_streak = 0
                self._limit += 1
                self._cond.notify()
                return self._limit
            return None


_MAX_RETRIES = 6  # retries per text on rate-limit before giving up


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

        max_workers = max(1, int(config.get("max_workers", 8)))

        # Entries that errored on a previous run are retried: a run is normally
        # relaunched precisely because something failed (network, rate limit).
        pending = [e for e in self.result.entries if e.status in ("pending", "error")]
        for e in pending:
            e.status = "pending"
        total = len(pending)

        # Deduplicate by original text. RPG games repeat names, menu terms and
        # whole dialogue lines heavily, so translating only the unique strings
        # (and copying the result to every entry that shares it) often removes
        # a large fraction of the API calls for free.
        groups: dict[str, list] = {}
        for e in pending:
            groups.setdefault(e.original, []).append(e)
        unique_texts = list(groups.keys())
        self._log(
            "INFO",
            f"Traduciendo {total} textos ({len(unique_texts)} únicos tras deduplicar) "
            f"con {max_workers} hilos en paralelo...",
        )

        import time
        from concurrent.futures import ThreadPoolExecutor, as_completed

        # deep-translator's client is not guaranteed thread-safe, so each worker
        # thread builds and reuses its own translator instance.
        tls = threading.local()

        def get_translator(lang: str) -> BaseTranslator:
            cache = getattr(tls, "by_lang", None)
            if cache is None:
                cache = {}
                tls.by_lang = cache
            tr = cache.get(lang)
            if tr is None:
                tr = _build_translator(self.translator_name, lang, tgt)
                cache[lang] = tr
            return tr

        # A partially translated game mixes languages: asking Google for
        # Japanese "from English" either errors or hands the text back
        # untranslated, so each string is routed by the script it is written in.
        routed: dict[str, int] = {}
        routed_lock = threading.Lock()

        limiter = AdaptiveLimiter(max_workers)
        log_lock = threading.Lock()

        def _wait(seconds: float) -> None:
            """Sleep in small slices so cancel stays responsive."""
            slept = 0.0
            while slept < seconds and not self._cancel.is_set():
                time.sleep(min(0.2, seconds - slept))
                slept += 0.2

        def work(text: str):
            """Translate one unique text with adaptive concurrency + backoff on
            rate limiting. Returns the translation, None if cancelled, or raises
            after exhausting retries (so the caller marks it as an error)."""
            backoff = 1.0
            unsafe_retries_left = 1
            # Decided once per text, not per attempt, so a retried string is
            # not counted twice in the summary.
            lang = detect_source_language(text, src)
            if lang != src:
                with routed_lock:
                    routed[lang] = routed.get(lang, 0) + 1
            for attempt in range(_MAX_RETRIES + 1):
                while self._pause.is_set() and not self._cancel.is_set():
                    time.sleep(0.2)
                if self._cancel.is_set():
                    return None

                limiter.acquire()
                try:
                    protected, saved = protect_game_codes(text)
                    raw = get_translator(lang).translate_one(protected)
                    out = restore_game_codes(raw, saved)
                    # A translator that mangled a \N[1] or a <notetag> produces
                    # text that reads plausibly but says the wrong thing, so it
                    # must never be written into the game.
                    if not translation_is_safe(out, saved):
                        raise UnsafeTranslation(missing_codes(out, saved))
                    out = keep_trailing_conditions(text, out)
                    out = transfer_outer_spacing(text, out)
                    if delay > 0:
                        time.sleep(delay / 1000)
                    raised = limiter.on_success(cap=max_workers)
                    if raised is not None:
                        with log_lock:
                            self._log("INFO", f"Conexión estable: subiendo a {raised} hilos.")
                    return out
                except UnsafeTranslation as exc:
                    if unsafe_retries_left > 0:
                        unsafe_retries_left -= 1
                        continue
                    raise
                except Exception as exc:
                    retryable = _is_rate_limit(exc) or isinstance(exc, TranslationUnavailable)
                    if not retryable or attempt >= _MAX_RETRIES:
                        raise
                    lowered = limiter.decrease()
                    if lowered is not None:
                        with log_lock:
                            self._log("WARNING",
                                      f"Límite de peticiones detectado — reduciendo a {lowered} "
                                      f"hilos y reintentando.")
                finally:
                    limiter.release()

                # Backoff happens outside the limiter slot so we free capacity
                # for other threads while this one waits.
                _wait(backoff)
                backoff = min(backoff * 2, 30.0)
            return None

        # Throttle checkpoint writes by elapsed time instead of every N items.
        # Dumping the full result (50k+ entries) every few texts is O(n²) and
        # makes large jobs crawl; once every ~20s keeps the cost negligible.
        checkpoint_interval_s = 20.0
        last_checkpoint = time.monotonic()
        completed_entries = 0

        pool = ThreadPoolExecutor(max_workers=max_workers)
        try:
            futures = {pool.submit(work, text): text for text in unique_texts}
            for fut in as_completed(futures):
                text = futures[fut]
                grp = groups[text]
                try:
                    translated = fut.result()
                    if translated is not None:
                        for e in grp:
                            e.translation = translated
                            e.status = "translated"
                except UnsafeTranslation as exc:
                    # Leaving the original text keeps the game correct; the
                    # entry stays visible as an error so it can be fixed by hand.
                    with log_lock:
                        self._log(
                            "WARNING",
                            f"Traducción descartada en '{grp[0].context}': el traductor "
                            f"eliminó {', '.join(exc.lost)}. Se conserva el texto original.",
                        )
                    for e in grp:
                        e.status = "error"
                except Exception as exc:
                    logger.warning(f"Error al traducir '{grp[0].uid}': {exc}")
                    for e in grp:
                        e.status = "error"

                completed_entries += len(grp)
                self._emit(WorkerMessage.progress(completed_entries, total, grp[0].file))

                now = time.monotonic()
                if config.get("checkpoint_enabled") and now - last_checkpoint >= checkpoint_interval_s:
                    checkpoint.save(self.result.game_path, self.result.to_dict())
                    last_checkpoint = now

                if self._cancel.is_set():
                    self._log("INFO", "Traducción cancelada.")
                    break
        finally:
            # cancel_futures stops queued-but-not-started tasks immediately
            pool.shutdown(wait=False, cancel_futures=True)

        # Final checkpoint after loop ends (covers items translated since last periodic save)
        if config.get("checkpoint_enabled"):
            checkpoint.save(self.result.game_path, self.result.to_dict())

        if routed:
            detail = ", ".join(f"{n} en {lang}" for lang, n in sorted(routed.items()))
            self._log("INFO", f"Textos detectados en otro idioma y traducidos como tal: {detail}")

        locked = sum(1 for e in self.result.entries if e.status == "locked")
        if locked:
            self._log("INFO",
                      f"{locked} textos no se han traducido porque un script del juego "
                      f"los consulta por su valor (estado 'locked' en la exportación).")

        translated = sum(1 for e in self.result.entries if e.status == "translated")
        errors = sum(1 for e in self.result.entries if e.status == "error")
        self._log(
            "SUCCESS",
            f"Traducción completa: {translated} traducidos, {errors} errores.",
        )
        self._emit(WorkerMessage.complete(self.result))
