"""Centralized logging: file log + in-memory queue for GUI consumption."""
from __future__ import annotations
import logging
import logging.handlers
import queue
from pathlib import Path
from typing import Callable

LOG_DIR = Path.home() / ".rpg_translator" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "rpg_translator.log"

# Bounded on purpose: a 100k-text game emits a lot of log lines, and nothing
# drains this queue unless a consumer asks for it. Oldest entries are dropped
# once it fills so a long run cannot grow memory without limit.
_QUEUE_MAX = 5000
_queue: queue.Queue[dict] = queue.Queue(maxsize=_QUEUE_MAX)
_callbacks: list[Callable[[dict], None]] = []

# Rotated on purpose: translating a 100k-text game writes a lot of lines, and a
# single unbounded log file had grown past 100 MB.
_handler = logging.handlers.RotatingFileHandler(
    LOG_FILE, maxBytes=4 * 1024 * 1024, backupCount=2, encoding="utf-8"
)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[_handler],
)
_file_logger = logging.getLogger("rpg_translator")


def _emit(level: str, msg: str) -> None:
    entry = {"level": level, "msg": msg}
    while True:
        try:
            _queue.put_nowait(entry)
            break
        except queue.Full:
            try:
                _queue.get_nowait()
            except queue.Empty:
                break
    for cb in _callbacks:
        try:
            cb(entry)
        except Exception:
            pass
    getattr(_file_logger, level.lower(), _file_logger.info)(msg)


def info(msg: str) -> None:
    _emit("INFO", msg)


def warning(msg: str) -> None:
    _emit("WARNING", msg)


def error(msg: str) -> None:
    _emit("ERROR", msg)


def debug(msg: str) -> None:
    _emit("DEBUG", msg)


def success(msg: str) -> None:
    _emit("SUCCESS", msg)


def get_queue() -> queue.Queue[dict]:
    return _queue


def add_callback(cb: Callable[[dict], None]) -> None:
    _callbacks.append(cb)


def remove_callback(cb: Callable[[dict], None]) -> None:
    if cb in _callbacks:
        _callbacks.remove(cb)
