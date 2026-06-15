"""
Roundtrip test: extrae → traduce → reinserta → verifica que todo lo no-texto queda intacto.
Ejecutar desde D:\1rpgtraductor con:  python _test_roundtrip.py
"""
import json
import sys
import tempfile
import shutil
from pathlib import Path

# Force UTF-8 output on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).parent))

from extractors.rmmv_mz import MvMzExtractor
from validators.text_filter import is_translatable

# ─── Datos de juego simulados ────────────────────────────────────────────────

ACTORS = [
    None,
    {
        "id": 1, "name": "Hero", "nickname": "The Brave",
        "profile": "A young hero.", "note": "<atk:50>\n<element:fire>",
        "characterName": "Actor1", "characterIndex": 0,
        "faceName": "Actor1", "faceIndex": 0,
        "battlerName": "Fighter", "classId": 1,
        "initialLevel": 1, "maxLevel": 99,
        "equips": [1, 0, 0, 0, 0], "traits": [],
    },
]

ITEMS = [
    None,
    {
        "id": 1, "name": "Potion", "description": "Restores 50 HP.",
        "note": "<item_type:consumable>",
        "iconIndex": 176, "price": 50, "consumable": True,
        "itypeId": 1, "scope": 7, "occasion": 0,
        "speed": 0, "successRate": 100, "repeats": 1,
        "tpGain": 0, "hitType": 0, "animationId": 0,
        "damage": {"critical": False, "elementId": 0, "formula": "0", "type": 0, "variance": 20},
        "effects": [], "traits": [],
    },
]

MAP001 = {
    "autoplayBgm": False, "autoplayBgs": False,
    "battleback1Name": "Grassland", "battleback2Name": "Grassland",
    "bgm": {"name": "Field1", "pan": 0, "pitch": 100, "volume": 90},
    "bgs": {"name": "", "pan": 0, "pitch": 100, "volume": 90},
    "disableDashing": False, "displayName": "Hometown",
    "encounterList": [], "encounterStep": 30,
    "height": 13, "width": 17,
    "scrollType": 0, "specifyBattleback": False,
    "tilesetId": 1, "note": "",
    "data": [1, 2, 3, 4, 5],  # simplified tile data
    "events": {
        "1": {
            "id": 1, "name": "SignPost",
            "note": "", "x": 5, "y": 3,
            "pages": [
                {
                    "conditions": {
                        "actorId": 1, "actorValid": False,
                        "itemId": 1, "itemValid": False,
                        "selfSwitchCh": "A", "selfSwitchValid": False,
                        "switch1Id": 1, "switch1Valid": False,
                        "switch2Id": 1, "switch2Valid": False,
                        "variableId": 1, "variableValid": False, "variableValue": 0,
                    },
                    "directionFix": False, "image": {
                        "characterIndex": 0, "characterName": "",
                        "direction": 2, "pattern": 1, "tileId": 0,
                    },
                    "list": [
                        # dialogue block: code 101 + 401 lines
                        {"code": 101, "indent": 0, "parameters": ["Actor1", 0, 0, 2]},
                        {"code": 401, "indent": 0, "parameters": ["Hello, traveler!"]},
                        {"code": 401, "indent": 0, "parameters": ["Welcome to \\C[2]Hometown\\C[0]."]},
                        # choice
                        {"code": 102, "indent": 0, "parameters": [["Yes", "No"], 1, 0, 2, 0]},
                        {"code": 402, "indent": 0, "parameters": [0, "Yes"]},
                        {"code": 101, "indent": 0, "parameters": ["", 0, 0, 2]},
                        {"code": 401, "indent": 0, "parameters": ["Great choice!"]},
                        {"code": 0,   "indent": 0, "parameters": []},
                        {"code": 402, "indent": 0, "parameters": [1, "No"]},
                        {"code": 101, "indent": 0, "parameters": ["", 0, 0, 2]},
                        {"code": 401, "indent": 0, "parameters": ["Maybe later then."]},
                        {"code": 0,   "indent": 0, "parameters": []},
                        # scroll text
                        {"code": 405, "indent": 0, "parameters": ["The town square."]},
                        # plugin command (should NOT be extracted)
                        {"code": 356, "indent": 0, "parameters": ["ShowShop 1 normal"]},
                        # script call (should NOT be extracted)
                        {"code": 355, "indent": 0, "parameters": ["$gameVariables.setValue(1, 5)"]},
                        # transfer player (should NOT be touched)
                        {"code": 201, "indent": 0, "parameters": [0, 2, 8, 6, 0, 0]},
                        {"code": 0,   "indent": 0, "parameters": []},
                    ],
                    "moveFrequency": 3, "moveRoute": {
                        "list": [{"code": 0, "parameters": []}],
                        "repeat": True, "skippable": False, "wait": False,
                    },
                    "moveSpeed": 3, "moveType": 0,
                    "priorityType": 0, "stepAnime": False,
                    "through": False, "trigger": 0, "walkAnime": True,
                }
            ],
        },
        "2": {
            "id": 2, "name": "Chest",
            "note": "", "x": 10, "y": 7,
            "pages": [
                {
                    "conditions": {"actorId": 1, "actorValid": False, "itemId": 1, "itemValid": False,
                                   "selfSwitchCh": "A", "selfSwitchValid": False,
                                   "switch1Id": 1, "switch1Valid": False, "switch2Id": 1,
                                   "switch2Valid": False, "variableId": 1, "variableValid": False, "variableValue": 0},
                    "directionFix": False,
                    "image": {"characterIndex": 0, "characterName": "!Chest", "direction": 2, "pattern": 1, "tileId": 0},
                    "list": [
                        {"code": 101, "indent": 0, "parameters": ["", 0, 0, 2]},
                        {"code": 401, "indent": 0, "parameters": ["You found \\V[1] gold!"]},
                        {"code": 125, "indent": 0, "parameters": [0, 0, 100]},  # change gold
                        {"code": 0,   "indent": 0, "parameters": []},
                    ],
                    "moveFrequency": 3,
                    "moveRoute": {"list": [{"code": 0, "parameters": []}], "repeat": True, "skippable": False, "wait": False},
                    "moveSpeed": 3, "moveType": 0,
                    "priorityType": 0, "stepAnime": False, "through": False, "trigger": 0, "walkAnime": True,
                }
            ],
        },
    },
}

SYSTEM = {
    "gameTitle": "My RPG Game",
    "currencyUnit": "Gold",
    "locale": "ja_JP",
    "windowTone": [-68, -68, -68, 0],
    "battleBgm": {"name": "Battle1", "pan": 0, "pitch": 100, "volume": 90},
    "defeatMe": {"name": "Defeat1", "pan": 0, "pitch": 100, "volume": 90},
    "gameoverMe": {"name": "Gameover1", "pan": 0, "pitch": 100, "volume": 90},
    "titleBgm": {"name": "Theme1", "pan": 0, "pitch": 100, "volume": 90},
    "sounds": [{"name": "", "pan": 0, "pitch": 100, "volume": 90}] * 30,
    "terms": {
        "basic": ["Max HP", "Max MP", "HP", "MP", "Attack", "Defense", "M.Attack", "M.Defense", "Agility", "Luck", "Hit", "Evasion"],
        "commands": ["Fight", "Escape", "Attack", "Guard", "Item", "Skill", "Equip", "Status", "Formation", "Save", "Game End", "Options", "Weapon", "Armor", "Key Item", "Equip", "Remove All", "New Game", "Continue", None, "Shutdown", "To Title", "Cancel", None, "Buy", "Sell"],
        "messages": {
            "alwaysDash": "Always Dash",
            "commandRemember": "Command Remember",
            "bgmVolume": "BGM Volume",
            "bgsVolume": "BGS Volume",
            "meVolume": "ME Volume",
            "seVolume": "SE Volume",
            "possession": "Possession",
            "expTotal": "Current %1",
            "expNext": "To Next %1",
            "saveMessage": "Save to which file?",
            "loadMessage": "Load which file?",
            "file": "File",
            "partyName": "%1's Party",
            "emerge": "%1 emerged!",
            "preemptive": "%1 got the jump!",
            "surprise": "%1 was surprised!",
        },
        "params": ["Max HP", "Max MP", "Attack", "Defense", "M.Attack", "M.Defense", "Agility", "Luck"],
    },
    "skillTypes": ["", "Magic", "Special"],
    "weaponTypes": ["", "Sword", "Axe", "Bow"],
    "armorTypes": ["", "General Armor", "Magic Armor", "Light Armor", "Heavy Armor", "Small Shield", "Large Shield"],
    "equipTypes": ["", "Weapon", "Shield", "Head", "Body", "Accessory"],
    "switches": [None, "OpenedChest", "MetKing"],
    "variables": [None, "GoldFound", "BattleCount"],
    "optFollowers": True, "optDisplayTp": True, "optExtraExp": False,
    "optFloorDeath": False, "optTransparent": False,
    "startMapId": 1, "startX": 8, "startY": 6,
    "versionId": 1,
}

COMMON_EVENTS = [
    None,
    {
        "id": 1, "name": "AutoSave",
        "switchId": 1, "trigger": 0,
        "list": [
            {"code": 101, "indent": 0, "parameters": ["", 0, 0, 2]},
            {"code": 401, "indent": 0, "parameters": ["Game saved automatically."]},
            {"code": 0,   "indent": 0, "parameters": []},
        ],
    },
]

TROOPS = [
    None,
    {
        "id": 1, "name": "Slimes",
        "members": [{"enemyId": 1, "x": 250, "y": 240, "hidden": False}],
        "pages": [
            {
                "conditions": {"actorHp": 50, "actorId": 1, "actorValid": False,
                                "enemyHp": 50, "enemyIndex": 0, "enemyValid": False,
                                "switch1Id": 1, "switch1Valid": False,
                                "switch2Id": 1, "switch2Valid": False, "turnA": 0,
                                "turnB": 0, "turnEnding": False, "turnValid": False},
                "list": [
                    {"code": 101, "indent": 0, "parameters": ["", 0, 0, 2]},
                    {"code": 401, "indent": 0, "parameters": ["The slimes attack!"]},
                    {"code": 0,   "indent": 0, "parameters": []},
                ],
                "span": 0,
            }
        ],
    },
]


# ─── Utilidades de test ──────────────────────────────────────────────────────

PASS = "✓"
FAIL = "✗"
failures = []

def check(label, actual, expected):
    if actual == expected:
        print(f"  {PASS} {label}")
    else:
        print(f"  {FAIL} {label}")
        print(f"      esperado : {expected!r}")
        print(f"      obtenido : {actual!r}")
        failures.append(label)


def deep_get(d, *keys):
    for k in keys:
        if isinstance(d, list):
            d = d[k]
        else:
            d = d.get(k)
        if d is None:
            return None
    return d


# ─── Setup ──────────────────────────────────────────────────────────────────

tmpdir = Path(tempfile.mkdtemp())
data_dir = tmpdir / "data"
data_dir.mkdir()

def write(name, obj):
    (data_dir / name).write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")

write("Actors.json", ACTORS)
write("Items.json",  ITEMS)
write("Map001.json", MAP001)
write("System.json", SYSTEM)
write("CommonEvents.json", COMMON_EVENTS)
write("Troops.json", TROOPS)

# ─── Extract ────────────────────────────────────────────────────────────────

extractor = MvMzExtractor(data_dir=data_dir, game_dir=tmpdir)
result = extractor.extract()

print(f"\nExtraídos: {result.total} textos")
for e in result.entries:
    print(f"  [{e.file}] {e.context}: {e.original[:60]!r}")

# ─── Simular traducción: añadir sufijo _T a cada texto ──────────────────────

PLUGIN_CMD  = "ShowShop 1 normal"
SCRIPT_CALL = "$gameVariables.setValue(1, 5)"

for entry in result.entries:
    # Asegurarse de que el plugin command y script call NO fueron extraídos
    assert entry.original != PLUGIN_CMD,  f"Plugin command extraído: {entry.uid}"
    assert entry.original != SCRIPT_CALL, f"Script call extraído: {entry.uid}"
    entry.translation = entry.original + "_T"
    entry.status = "translated"

# ─── Reinsert ───────────────────────────────────────────────────────────────

ok = extractor.reinsert(result)
assert ok, "reinsert() devolvió False"

# ─── Leer archivos modificados ───────────────────────────────────────────────

def load(name):
    return json.loads((data_dir / name).read_text(encoding="utf-8"))

actors  = load("Actors.json")
items   = load("Items.json")
map001  = load("Map001.json")
system  = load("System.json")
cevents = load("CommonEvents.json")
troops  = load("Troops.json")


# ════════════════════════════════════════════════════════════════════════════
print("\n── Actors.json ─────────────────────────────────────────────────────")

a = actors[1]
check("name traducido",           a["name"],          "Hero_T")
check("nickname traducido",       a["nickname"],      "The Brave_T")
check("profile traducido",        a["profile"],       "A young hero._T")
check("characterName sin tocar",  a["characterName"], "Actor1")
check("characterIndex sin tocar", a["characterIndex"], 0)
check("faceName sin tocar",       a["faceName"],      "Actor1")
check("faceIndex sin tocar",      a["faceIndex"],     0)
check("battlerName sin tocar",    a["battlerName"],   "Fighter")
check("classId sin tocar",        a["classId"],       1)
check("equips sin tocar",         a["equips"],        [1, 0, 0, 0, 0])
check("initialLevel sin tocar",   a["initialLevel"],  1)
check("maxLevel sin tocar",       a["maxLevel"],      99)
# note: notetags protegidos, solo descripción traducida
note_out = a["note"]
check("note conserva <atk:50>",        "<atk:50>"       in note_out, True)
check("note conserva <element:fire>",  "<element:fire>" in note_out, True)

# ════════════════════════════════════════════════════════════════════════════
print("\n── Items.json ──────────────────────────────────────────────────────")

it = items[1]
check("name traducido",            it["name"],        "Potion_T")
check("description traducido",     it["description"], "Restores 50 HP._T")
check("iconIndex sin tocar",       it["iconIndex"],   176)
check("price sin tocar",           it["price"],       50)
check("consumable sin tocar",      it["consumable"],  True)
check("itypeId sin tocar",         it["itypeId"],     1)
check("damage.formula sin tocar",  it["damage"]["formula"], "0")
check("damage.type sin tocar",     it["damage"]["type"],    0)
check("effects sin tocar",         it["effects"],           [])
note_it = it["note"]
check("note conserva <item_type:consumable>", "<item_type:consumable>" in note_it, True)

# ════════════════════════════════════════════════════════════════════════════
print("\n── Map001.json — metadatos ─────────────────────────────────────────")

check("displayName traducido",         map001["displayName"],      "Hometown_T")
check("battleback1Name sin tocar",     map001["battleback1Name"],  "Grassland")
check("battleback2Name sin tocar",     map001["battleback2Name"],  "Grassland")
check("bgm.name sin tocar",            map001["bgm"]["name"],      "Field1")
check("bgm.volume sin tocar",          map001["bgm"]["volume"],    90)
check("width sin tocar",               map001["width"],            17)
check("height sin tocar",              map001["height"],           13)
check("tilesetId sin tocar",           map001["tilesetId"],        1)
check("data (tiles) sin tocar",        map001["data"],             [1, 2, 3, 4, 5])
check("encounterStep sin tocar",       map001["encounterStep"],    30)

# ════════════════════════════════════════════════════════════════════════════
print("\n── Map001.json — evento 1 (SignPost) ───────────────────────────────")

ev1 = map001["events"]["1"]
check("event.name sin tocar",          ev1["name"],  "SignPost")
check("event.x sin tocar",             ev1["x"],     5)
check("event.y sin tocar",             ev1["y"],     3)

pg = ev1["pages"][0]
check("page.trigger sin tocar",        pg["trigger"],       0)
check("page.moveType sin tocar",       pg["moveType"],      0)
check("page.moveSpeed sin tocar",      pg["moveSpeed"],     3)
check("page.priorityType sin tocar",   pg["priorityType"],  0)
check("page.image.characterName",      pg["image"]["characterName"], "")
check("page.image.tileId sin tocar",   pg["image"]["tileId"], 0)

cmds = pg["list"]

# code 101 header parameters (face image info) intactos
check("cmd101.parameters sin tocar",   cmds[0]["parameters"], ["Actor1", 0, 0, 2])

# code 401 — bloque de 2 líneas: _T queda al final del bloque (en la última línea)
check("diálogo[0] intacto (línea 1)",  cmds[1]["parameters"][0], "Hello, traveler!")

# código de escape en diálogo — debe estar intacto después de traducción
# (protect_game_codes protege \C[2] y \C[0])
translated_line2 = cmds[2]["parameters"][0]
check("\\C[2] conservado en diálogo",  "\\C[2]" in translated_line2, True)
check("\\C[0] conservado en diálogo",  "\\C[0]" in translated_line2, True)
check("texto traducido en diálogo",    "Hometown" in translated_line2, True)

# code 102 — choices traducidas
check("choice Yes traducida",          cmds[3]["parameters"][0][0], "Yes_T")
check("choice No traducida",           cmds[3]["parameters"][0][1], "No_T")
check("choice cancel_type sin tocar",  cmds[3]["parameters"][1], 1)
check("choice default sin tocar",      cmds[3]["parameters"][2], 0)

# code 402 branches intactas (parámetros no tocados)
check("code402 branch[0] sin tocar",   cmds[4]["code"],               402)
check("code402 branch[0] params",      cmds[4]["parameters"],         [0, "Yes"])
check("code402 branch[1] sin tocar",   cmds[8]["code"],               402)
check("code402 branch[1] params",      cmds[8]["parameters"],         [1, "No"])

# segundo bloque de diálogo (after Yes)
check("diálogo Yes traducido",         cmds[6]["parameters"][0], "Great choice!_T")

# tercer bloque de diálogo (after No)
check("diálogo No traducido",          cmds[10]["parameters"][0], "Maybe later then._T")

# code 405 scroll text traducido
check("scroll text traducido",         cmds[12]["parameters"][0], "The town square._T")

# plugin command sin tocar
check("plugin cmd code sin tocar",     cmds[13]["code"],             356)
check("plugin cmd params sin tocar",   cmds[13]["parameters"][0],    "ShowShop 1 normal")

# script call sin tocar
check("script call code sin tocar",    cmds[14]["code"],             355)
check("script call params sin tocar",  cmds[14]["parameters"][0],    "$gameVariables.setValue(1, 5)")

# transfer player sin tocar
check("transfer code sin tocar",       cmds[15]["code"],             201)
check("transfer params sin tocar",     cmds[15]["parameters"],       [0, 2, 8, 6, 0, 0])

# ════════════════════════════════════════════════════════════════════════════
print("\n── Map001.json — evento 2 (Chest) ──────────────────────────────────")

ev2 = map001["events"]["2"]
check("event2.name sin tocar",         ev2["name"],  "Chest")
check("event2.x sin tocar",            ev2["x"],     10)
check("event2.y sin tocar",            ev2["y"],     7)

cmds2 = ev2["pages"][0]["list"]
check("image.characterName !Chest",    ev2["pages"][0]["image"]["characterName"], "!Chest")

# \\V[1] debe sobrevivir la traducción gracias a protect_game_codes
translated_chest = cmds2[1]["parameters"][0]
check("\\V[1] conservado",             "\\V[1]" in translated_chest, True)
check("texto traducido",               "gold" in translated_chest, True)

# code 125 (change gold) sin tocar
check("code125 sin tocar",             cmds2[2]["code"],        125)
check("code125 params sin tocar",      cmds2[2]["parameters"],  [0, 0, 100])

# ════════════════════════════════════════════════════════════════════════════
print("\n── System.json ─────────────────────────────────────────────────────")

check("gameTitle traducido",           system["gameTitle"],         "My RPG Game_T")
check("currencyUnit traducido",        system["currencyUnit"],      "Gold_T")
check("locale sin tocar",              system["locale"],            "ja_JP")
check("battleBgm.name sin tocar",      system["battleBgm"]["name"], "Battle1")
check("windowTone sin tocar",          system["windowTone"],        [-68, -68, -68, 0])
check("startMapId sin tocar",          system["startMapId"],        1)
check("startX sin tocar",              system["startX"],            8)
check("versionId sin tocar",           system["versionId"],         1)
check("terms.basic[0] traducido",      system["terms"]["basic"][0], "Max HP_T")
check("terms.basic[2] traducido",      system["terms"]["basic"][2], "HP_T")
check("terms.commands[0] traducido",   system["terms"]["commands"][0], "Fight_T")
check("terms.messages.alwaysDash",     system["terms"]["messages"].get("alwaysDash"), "Always Dash_T")
# %1 en expTotal debe sobrevivir (protect_game_codes)
check("%1 en expTotal conservado",     "%1" in system["terms"]["messages"]["expTotal"], True)
check("%1 en partyName conservado",    "%1" in system["terms"]["messages"]["partyName"], True)
check("skillTypes[1] traducido",       system["skillTypes"][1], "Magic_T")
check("weaponTypes[1] traducido",      system["weaponTypes"][1], "Sword_T")
# switches/variables (IDs, no texto de juego)
check("switches sin tocar",            system["switches"][1], "OpenedChest")
check("variables sin tocar",           system["variables"][1], "GoldFound")

# ════════════════════════════════════════════════════════════════════════════
print("\n── CommonEvents.json ───────────────────────────────────────────────")

ce = cevents[1]
check("trigger sin tocar",     ce["trigger"],   0)
check("switchId sin tocar",    ce["switchId"],  1)
ce_cmds = ce["list"]
check("diálogo auto-save traducido", ce_cmds[1]["parameters"][0], "Game saved automatically._T")
check("code 0 sin tocar",      ce_cmds[2]["code"], 0)

# ════════════════════════════════════════════════════════════════════════════
print("\n── Troops.json ─────────────────────────────────────────────────────")

tr = troops[1]
check("name traducido",        tr["name"], "Slimes_T")
check("members sin tocar",     tr["members"][0]["enemyId"], 1)
check("members x sin tocar",   tr["members"][0]["x"], 250)
check("members y sin tocar",   tr["members"][0]["y"], 240)
tr_cmds = tr["pages"][0]["list"]
check("troop diálogo traducido", tr_cmds[1]["parameters"][0], "The slimes attack!_T")
check("troop span sin tocar",    tr["pages"][0]["span"], 0)

# ════════════════════════════════════════════════════════════════════════════
print("\n── protect_game_codes: casos directos ──────────────────────────────")

from utils.text_utils import protect_game_codes, restore_game_codes

cases = [
    ("\\V[1] reference",   "You have \\V[1] gold",       "\\V[1]"),
    ("\\N[1] reference",   "I am \\N[1]!",               "\\N[1]"),
    ("\\C[2] color",       "\\C[2]Red\\C[0] text",       "\\C[2]"),
    ("\\. pause",          "Wait\\.a sec",               "\\."),
    ("%1 format",          "Current %1",                 "%1"),
    ("%2 format",          "%1 and %2",                  "%2"),
    ("<ATK:50> notetag",   "Weapon\n<ATK:50>",           "<ATK:50>"),
    ("<br> html tag",      "Line1<br>Line2",             "<br>"),
    ("<element:fire>",     "Desc\n<element:fire>",        "<element:fire>"),
]

for name, text, code in cases:
    protected, saved = protect_game_codes(text)
    assert code not in protected, f"El código {code!r} no fue protegido"
    restored = restore_game_codes(protected, saved)
    if restored == text:
        print(f"  {PASS} {name}")
    else:
        print(f"  {FAIL} {name}: restaurado={restored!r}, original={text!r}")
        failures.append(name)

# ─── Resultado final ─────────────────────────────────────────────────────────

shutil.rmtree(tmpdir)

print(f"\n{'═'*60}")
if failures:
    print(f"FALLARON {len(failures)} checks:")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print(f"TODOS LOS CHECKS PASARON")
    sys.exit(0)
