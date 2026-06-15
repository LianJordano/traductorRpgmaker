"""Return the correct extractor for a detected RPG Maker version."""
from __future__ import annotations
from pathlib import Path
from typing import Callable, Optional

from core.detector import DetectionResult
from core.models import ExtractionResult
from extractors.base import BaseExtractor


def get_extractor(
    detection: DetectionResult,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
    cancel_flag: Optional[Callable[[], bool]] = None,
) -> Optional[BaseExtractor]:
    version = detection.version
    data_dir = detection.data_dir or detection.game_dir
    game_dir = detection.game_dir

    kwargs = dict(
        data_dir=data_dir,
        game_dir=game_dir,
        progress_cb=progress_cb,
        cancel_flag=cancel_flag,
    )

    if version in ("MV", "MZ"):
        from extractors.rmmv_mz import MvMzExtractor
        return MvMzExtractor(**kwargs)
    elif version == "VXAce":
        from extractors.rmvxace import VXAceExtractor
        return VXAceExtractor(**kwargs)
    elif version == "VX":
        from extractors.rmvx import VXExtractor
        return VXExtractor(**kwargs)
    elif version == "XP":
        from extractors.rmxp import XPExtractor
        return XPExtractor(**kwargs)
    elif version in ("RM2000", "RM2003"):
        from extractors.rm2000 import RM2000Extractor
        return RM2000Extractor(**kwargs)

    return None
