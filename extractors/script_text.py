"""Translate the display strings inside RGSS scripts (VX Ace / VX / XP).

Custom menus, item descriptions and battle messages in these engines live in
`Scripts.rvdata2`, so leaving it alone means a chunk of the game stays in the
original language. See :mod:`parsers.ruby_source` for the rules that separate a
message from script data; this module only wires them to the extractor and
guarantees the archive is written back safely.
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional

from core import logger
from core.models import TextEntry
from parsers import ruby_source as rb
from parsers import script_archive as sa


def scripts_path(data_dir: Path, ext: str) -> Optional[Path]:
    path = Path(data_dir) / f"Scripts{ext}"
    return path if path.is_file() else None


def _script_label(script: sa.ScriptEntry) -> str:
    name = script.name.strip() or f"script{script.index}"
    return name.replace("::", "_")


def extract(data_dir: Path, ext: str, make_entry) -> list[TextEntry]:
    """Extract translatable display strings from every script in the archive."""
    path = scripts_path(data_dir, ext)
    if path is None or not sa.is_available():
        return []

    try:
        scripts, _ = sa.load(path)
    except Exception as exc:
        logger.warning(f"No se pudo leer {path.name}: {exc}")
        return []

    entries: list[TextEntry] = []
    for script in scripts:
        label = _script_label(script)
        for pos, item in enumerate(rb.scan(script.source)):
            if not rb.is_display_text(script.source, item):
                continue
            entry = make_entry(
                path.name,
                f"script[{label}].text[{pos}]",
                item.value,
                len(entries),
                {"type": "script_string", "script_index": script.index,
                 "literal_index": pos, "quote": item.quote},
            )
            if entry:
                entries.append(entry)

    if entries:
        logger.info(f"  → {len(entries)} textos de scripts en {path.name}")
    return entries


def reinsert(data_dir: Path, ext: str, entries: list[TextEntry]) -> bool:
    """Write translated script strings back into the archive.

    Each literal is re-located by scanning the current source and is only
    rewritten when both its position *and* its exact original text still match,
    so a script edited in the meantime is skipped rather than corrupted. The
    rewritten source must scan to the same number of literals, otherwise the
    change is discarded — that check is what catches a misread heredoc or regex.
    """
    path = scripts_path(data_dir, ext)
    if path is None:
        logger.warning(f"No se encontró Scripts{ext}; se omiten los scripts.")
        return True
    if not sa.is_available():
        return True

    original_bytes = path.read_bytes()
    try:
        scripts, data = sa.load(path)
    except Exception as exc:
        logger.error(f"No se pudo leer {path.name}: {exc}")
        return False

    by_index = {s.index: s for s in scripts}
    grouped: dict[int, list[TextEntry]] = {}
    for entry in entries:
        idx = entry.metadata.get("script_index")
        if idx is not None:
            grouped.setdefault(idx, []).append(entry)

    applied = skipped = 0
    touched: list[str] = []

    for script_index, group in grouped.items():
        script = by_index.get(script_index)
        if script is None:
            skipped += len(group)
            continue

        literals = rb.scan(script.source)
        edits: list[tuple[int, int, str]] = []
        for entry in group:
            pos = entry.metadata.get("literal_index")
            if not isinstance(pos, int) or not 0 <= pos < len(literals):
                skipped += 1
                continue
            item = literals[pos]
            if item.value != entry.original:
                skipped += 1
                continue
            edits.append((item.start, item.end,
                          rb.encode(entry.translation, item.quote)))

        if not edits:
            continue

        new_source = rb.replace(script.source, edits)
        if len(rb.scan(new_source)) != len(literals):
            logger.error(
                f"{path.name}: '{script.name}' quedaría mal formado; se omite."
            )
            skipped += len(edits)
            continue

        sa.update(script, new_source)
        applied += len(edits)
        touched.append(script.name)

    if not applied:
        if skipped:
            logger.warning(f"{path.name}: no se aplicó nada ({skipped} omitidos).")
        return True

    try:
        sa.save(path, data)
        if not sa.verify(path, len(scripts)):
            raise ValueError("el archivo reescrito no se puede volver a leer")
        logger.success(
            f"{path.name}: {applied} textos en {len(touched)} scripts"
            + (f", {skipped} omitidos" if skipped else "")
        )
        return True
    except Exception as exc:
        logger.error(f"{path.name}: fallo al escribir ({exc}); se restaura el original.")
        try:
            path.write_bytes(original_bytes)
        except Exception as restore_exc:
            logger.error(f"No se pudo restaurar {path.name}: {restore_exc}")
        return False
