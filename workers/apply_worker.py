"""Background thread for applying translations back into the game files.

Backup creation and reinsertion are I/O- and CPU-heavy for large games
(50k+ texts). Running them on the GUI thread freezes the window, so they
run here and report progress/results through the WorkerMessage queue.
"""
from __future__ import annotations
import queue
import threading

from core import backup, config, logger
from core.detector import detect
from core.models import ExtractionResult, WorkerMessage
from extractors.factory import get_extractor


class ApplyWorker(threading.Thread):
    """Creates a backup and reinserts translations in a daemon thread."""

    def __init__(self, game_path: str, result: ExtractionResult, out_queue: queue.Queue) -> None:
        super().__init__(daemon=True, name="ApplyWorker")
        self.game_path = game_path
        self.result = result
        self.out_queue = out_queue
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def _cancelled(self) -> bool:
        return self._cancel.is_set()

    def _emit(self, msg: WorkerMessage) -> None:
        self.out_queue.put(msg)

    def _log(self, level: str, text: str) -> None:
        self._emit(WorkerMessage.log(level, text))

    def run(self) -> None:
        try:
            self._run()
        except Exception as exc:
            self._emit(WorkerMessage.error(f"Error al aplicar traducciones: {exc}"))
            logger.error(f"ApplyWorker falló: {exc}")

    def _run(self) -> None:
        detection = detect(self.game_path)

        # Backup (file copy — slow, but now off the GUI thread)
        if config.get("backup_enabled") and detection.data_dir:
            self._log("INFO", "Creando backup antes de aplicar...")
            bk = backup.create_backup(detection.data_dir, detection.game_dir)
            if bk:
                self._log("SUCCESS", f"Backup guardado en: {bk}")
            else:
                self._log("WARNING", "No se pudo crear el backup.")

        if self._cancelled():
            self._log("INFO", "Aplicación cancelada.")
            self._emit(WorkerMessage.complete(None))
            return

        def progress_cb(current: int, total: int, file: str) -> None:
            self._emit(WorkerMessage.progress(current, total, file))

        extractor = get_extractor(detection, progress_cb, self._cancelled)
        if not extractor:
            self._emit(WorkerMessage.error(
                "No hay extractor disponible para esta versión."
            ))
            return

        self._log("INFO", "Aplicando traducciones a los archivos del juego...")
        ok = extractor.reinsert(self.result)
        if ok:
            self._log("SUCCESS", "Traducciones aplicadas correctamente.")
        else:
            self._log("WARNING", "La reinserción terminó con errores. Revisa el registro.")

        # result=None so the GUI doesn't overwrite the current extraction result;
        # the apply-specific completion handler reads self._apply_ok.
        self._emit(WorkerMessage.stats(apply_ok=ok))
        self._emit(WorkerMessage.complete(None))
