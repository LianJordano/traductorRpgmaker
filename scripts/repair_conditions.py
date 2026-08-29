"""Repair plugin conditions that a translator mangled inside choice text.

Some plugins read a condition out of the visible text of a choice
(`Yes en(v[18]>=3)`). Older builds sent that straight to the translator, which
happily rendered `if(` as `si (` and `en(` as `es(`. The plugin then no longer
recognises its own condition, so it neither hides the choice nor strips the
text — the player sees `si (v[41]>=10)` on screen and the gating stops working.

Translating again is not needed to fix it: the condition *body* survived
untouched, so the correct keyword can be recovered from the game's own backup
and the condition put back together in place.

    python scripts/repair_conditions.py "D:\\rhgames\\MiJuego"
    python scripts/repair_conditions.py "D:\\rhgames\\MiJuego" --apply
"""
from __future__ import annotations
import argparse
import json
import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import backup as bk          # noqa: E402
from core.detector import detect       # noqa: E402

#: A condition as it appears in text, however the translator reformatted it.
LOOSE = re.compile(
    r"\b([A-Za-z_]{1,10})\s*\(\s*([^()]{0,120}?)\s*\)",
)
#: Signals that the parenthesised part really is a condition.
SIGNAL = re.compile(r"[vs]\s*\[\s*\d+\s*\]|[<>=!]\s*=|&&|\|\|")


def _bodies(text: str) -> list[tuple[str, str, str]]:
    """Return (whole match, keyword, normalised body) for each condition."""
    out = []
    for m in LOOSE.finditer(text):
        body = m.group(2)
        if SIGNAL.search(body):
            out.append((m.group(0), m.group(1), re.sub(r"\s+", "", body)))
    return out


def _choices(data):
    """Yield (container, index) for every choice string, so it can be written."""
    found = []

    def walk(o):
        if isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, dict):
            code, params = o.get("code"), o.get("parameters")
            if code == 102 and isinstance(params, list) and params \
                    and isinstance(params[0], list):
                for i in range(len(params[0])):
                    if isinstance(params[0][i], str):
                        found.append((params[0], i))
            elif code == 402 and isinstance(params, list) and len(params) > 1 \
                    and isinstance(params[1], str):
                found.append((params, 1))
            for v in o.values():
                walk(v)
    walk(data)
    return found


def learn_from_backup(game_dir: Path) -> dict[str, set[str]]:
    """Map a normalised condition body to every original spelling of it.

    A body can legitimately appear under more than one keyword — the same game
    has both `en(s[154])` and `if(!s[154])` — so the mapping keeps all of them
    and repair only happens when there is exactly one candidate.
    """
    table: dict[str, set[str]] = {}
    originals = [b for b in bk.list_backups(game_dir) if bk.is_original(b)]
    if not originals:
        originals = bk.list_backups(game_dir)
    for backup in originals:
        if backup.is_file() and backup.suffix == ".zip":
            with zipfile.ZipFile(backup) as z:
                for name in z.namelist():
                    if not name.endswith(".json"):
                        continue
                    try:
                        data = json.loads(z.read(name).decode("utf-8-sig"))
                    except Exception:
                        continue
                    for holder, index in _choices(data):
                        for whole, _kw, body in _bodies(holder[index]):
                            table.setdefault(body, set()).add(whole)
    return table


AMBIGUOUS = 0


def repair_text(text: str, table: dict[str, set[str]]) -> str | None:
    """Return the repaired string, or None when nothing needed fixing."""
    global AMBIGUOUS
    conditions = _bodies(text)
    if not conditions:
        return None

    replacements: list[tuple[str, str]] = []
    for whole, _keyword, body in conditions:
        candidates = table.get(body)
        if not candidates:
            continue
        if whole in candidates:
            continue                      # already exactly as the original
        if len(candidates) != 1:
            AMBIGUOUS += 1                # same body, several keywords: hands off
            continue
        replacements.append((whole, next(iter(candidates))))

    if not replacements:
        return None

    repaired = text
    for wrong, right in replacements:
        repaired = repaired.replace(wrong, right, 1)
    # Conditions belong at the end; the translator may have moved one.
    parts = _bodies(repaired)
    body_text = repaired
    for whole, _kw, _body in parts:
        body_text = body_text.replace(whole, "", 1)
    return body_text.strip() + " " + "".join(w for w, _k, _b in parts)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("game", type=Path)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    detection = detect(str(args.game))
    data_dir = detection.data_dir
    if data_dir is None or not data_dir.is_dir():
        print(f"No se encontró la carpeta de datos en {args.game}")
        return 1
    print(f"Juego: {detection.version}   datos: {data_dir}")

    table = learn_from_backup(detection.game_dir)
    if not table:
        print("No hay backup del que aprender las condiciones originales.")
        return 1
    print(f"Condiciones conocidas del original: {len(table)}\n")

    total = 0
    for path in sorted(data_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        fixed = 0
        for holder, index in _choices(data):
            new = repair_text(holder[index], table)
            if new is not None and new != holder[index]:
                if total + fixed < 10:
                    print(f"  [{path.name}]")
                    print(f"     antes: {holder[index]!r}")
                    print(f"     ahora: {new!r}")
                holder[index] = new
                fixed += 1
        if fixed and args.apply:
            tmp = path.with_suffix(".json.rpgt_tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False,
                                      separators=(",", ":")), encoding="utf-8")
            tmp.replace(path)
        total += fixed

    print(f"\nopciones reparadas: {total}")
    if not args.apply:
        print("Ejecución en seco. Añade --apply para escribir los cambios.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
