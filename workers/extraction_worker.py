"""Background thread for game text extraction."""
from __future__ import annotations
import queue
import threading
from pathlib import Path
from typing import Optional

from core import backup, checkpoint, config, logger
from core.detector import detect, DetectionResult
from core.models import ExtractionResult, WorkerMessage
from extractors.factory import get_extractor


class ExtractionWorker(threading.Thread):
    """Runs extraction in a daemon thread and sends WorkerMessages to out_queue."""

    def __init__(self, game_path: str, out_queue: queue.Queue) -> None:
        super().__init__(daemon=True, name="ExtractionWorker")
        self.game_path = game_path
        self.out_queue = out_queue
        self._cancel = threading.Event()
        self.result: Optional[ExtractionResult] = None
        self.detection: Optional[DetectionResult] = None

    def cancel(self) -> None:
        self._cancel.set()

    def _cancelled(self) -> bool:
        return self._cancel.is_set()

    def _emit(self, msg: WorkerMessage) -> None:
        self.out_queue.put(msg)

    def _log(self, level: str, text: str) -> None:
        self._emit(WorkerMessage.log(level, text))
        getattr(logger, level.lower(), logger.info)(text)

    def run(self) -> None:
        try:
            self._run()
        except Exception as exc:
            self._emit(WorkerMessage.error(f"Error inesperado: {exc}"))
            logger.error(f"ExtractionWorker falló: {exc}")

    def _run(self) -> None:
        self._log("INFO", f"Escaneando carpeta del juego: {self.game_path}")

        # Detection
        detection = detect(self.game_path)
        self.detection = detection
        if not detection.supported:
            self._emit(WorkerMessage.error(
                "No se pudo detectar la versión de RPG Maker. "
                "Asegúrate de haber seleccionado la carpeta correcta del juego."
            ))
            return

        self._log("SUCCESS", f"Detectado: {detection.display_name} "
                              f"(confianza {detection.confidence}%)")
        self._emit(WorkerMessage.stats(
            version=detection.display_name,
            data_dir=str(detection.data_dir),
        ))

        # Load existing checkpoint translations to restore after fresh extraction
        saved_by_uid: dict = {}
        if config.get("checkpoint_enabled") and checkpoint.exists(self.game_path):
            saved = checkpoint.load(self.game_path)
            if saved:
                saved_by_uid = {e["uid"]: e for e in saved.get("entries", [])}
                self._log("INFO", f"Punto de control encontrado con {len(saved_by_uid)} entradas previas.")

        # Backup
        if config.get("backup_enabled") and detection.data_dir:
            self._log("INFO", "Creando backup...")
            bk = backup.create_backup(detection.data_dir, detection.game_dir)
            if bk:
                self._log("SUCCESS", f"Backup guardado en: {bk}")
            else:
                self._log("WARNING", "No se pudo crear el backup.")

        # Build extractor
        def progress_cb(current: int, total: int, file: str) -> None:
            self._emit(WorkerMessage.progress(current, total, file))

        extractor = get_extractor(detection, progress_cb, self._cancelled)
        if not extractor:
            self._emit(WorkerMessage.error(
                f"No hay extractor disponible para la versión: {detection.display_name}"
            ))
            return

        self._log("INFO", "Iniciando extracción de textos...")
        result = extractor.extract()
        self.result = result

        # Restore previous translations into freshly extracted entries
        if saved_by_uid:
            restored = 0
            for entry in result.entries:
                prev = saved_by_uid.get(entry.uid)
                if prev and prev.get("status") == "translated" and prev.get("translation"):
                    entry.translation = prev["translation"]
                    entry.status = "translated"
                    restored += 1
            if restored:
                self._log("INFO", f"Se restauraron {restored} traducciones del punto de control.")

        # Save checkpoint
        if config.get("checkpoint_enabled"):
            checkpoint.save(self.game_path, result.to_dict())
            self._log("INFO", "Punto de control guardado.")

        self._emit(WorkerMessage.stats(
            total=result.total,
            errors=len(result.errors),
        ))
        self._log(
            "SUCCESS",
            f"Extracción completa: {result.total} textos encontrados, "
            f"{len(result.errors)} errores.",
        )
        self._emit(WorkerMessage.complete(result))
