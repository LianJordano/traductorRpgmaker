"""Parse Ruby Marshal files (.rxdata, .rvdata, .rvdata2) for RPG Maker XP/VX/VXAce."""
from __future__ import annotations
from pathlib import Path
from typing import Any, Optional

try:
    import rubymarshal.reader as _reader
    import rubymarshal.writer as _writer
    from rubymarshal.classes import RubyObject
    _RUBYMARSHAL_OK = True
except ImportError:
    _RUBYMARSHAL_OK = False
    RubyObject = None


def is_available() -> bool:
    return _RUBYMARSHAL_OK


def load(path: Path) -> Any:
    """Load a Ruby Marshal file and return the parsed Python object."""
    if not _RUBYMARSHAL_OK:
        raise ImportError("rubymarshal is not installed. Run: pip install rubymarshal")
    with path.open("rb") as f:
        return _reader.load(f)


def save(path: Path, data: Any) -> None:
    """Write a Ruby object back to a Marshal file."""
    if not _RUBYMARSHAL_OK:
        raise ImportError("rubymarshal is not installed. Run: pip install rubymarshal")
    with path.open("wb") as f:
        _writer.dump(data, f)


def get_ivar(obj: Any, name: str, default: Any = None) -> Any:
    """Safely get an instance variable from a RubyObject."""
    if not _RUBYMARSHAL_OK or obj is None:
        return default
    if hasattr(obj, "ruby_class_name"):
        return obj.attributes.get(name, default)
    return default


def set_ivar(obj: Any, name: str, value: Any) -> None:
    """Set an instance variable on a RubyObject."""
    if not _RUBYMARSHAL_OK or obj is None:
        return
    if hasattr(obj, "ruby_class_name"):
        obj.attributes[name] = value


def walk_strings(obj: Any, callback, path: str = "") -> None:
    """Recursively walk a Ruby Marshal structure and call callback(path, value) for strings."""
    if isinstance(obj, str):
        callback(path, obj)
    elif isinstance(obj, bytes):
        try:
            s = obj.decode("utf-8")
        except Exception:
            try:
                s = obj.decode("cp932")
            except Exception:
                return
        callback(path, s)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            walk_strings(item, callback, f"{path}[{i}]")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            walk_strings(v, callback, f"{path}.{k}")
    elif _RUBYMARSHAL_OK and hasattr(obj, "ruby_class_name"):
        for k, v in obj.attributes.items():
            walk_strings(v, callback, f"{path}.{k}")
