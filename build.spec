# PyInstaller spec – RPG Translator Pro
# Usage: pyinstaller build.spec

import os
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None
ROOT = Path(SPECPATH)  # = D:\1rpgtraductor

# ── Collect customtkinter assets (themes, fonts, images) ──────────────────
ctk_datas = collect_data_files("customtkinter", includes=["**/*"])

# ── Collect Pillow image plugins ──────────────────────────────────────────
pil_datas = collect_data_files("PIL")

# ── Our assets ────────────────────────────────────────────────────────────
app_datas = [
    (str(ROOT / "assets"), "assets"),
]

all_datas = ctk_datas + pil_datas + app_datas

# ── Hidden imports needed for dynamic loading ──────────────────────────────
hidden = [
    "customtkinter",
    "PIL",
    "PIL._tkinter_finder",
    "PIL.Image",
    "PIL.ImageDraw",
    "deep_translator",
    "deep_translator.google",
    "rubymarshal",
    "rubymarshal.reader",
    "rubymarshal.writer",
    "rubymarshal.classes",
    "chardet",
    "openpyxl",
    "openpyxl.styles",
    "openpyxl.utils",
    "tkinter",
    "tkinter.filedialog",
    "tkinter.messagebox",
    # Optional translators (loaded dynamically, may not be installed)
    "openai",
    "deepl",
]

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=all_datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "numpy", "scipy", "pytest", "test"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    exclude_binaries=False,
    name="RPGTranslatorPro",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "assets" / "icon.ico"),
    version_file=None,
    runtime_tmpdir=None,
    onefile=True,
)
