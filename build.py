"""
RPG Translator Pro – one-click build script.
Usage: python build.py

Steps performed:
  1. Creates the application icon (assets/icon.ico)
  2. Cleans previous build artifacts
  3. Runs PyInstaller with build.spec
  4. Reports the output location
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
DIST_DIR = ROOT / "dist"
DIST_EXE = DIST_DIR / "RPGTranslatorPro.exe"
BUILD = ROOT / "build"
ICON = ROOT / "assets" / "icon.ico"

#: Lives in dist/ but is user data, not build output — see the cleaning step.
KEEP_IN_DIST = "traducciones_ejecutadas"


def step(msg: str) -> None:
    print(f"\n{'-'*60}")
    print(f"  {msg}")
    print(f"{'-'*60}")


def run(cmd: list[str]) -> None:
    print(f"> {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        print(f"\nERROR: command failed with code {result.returncode}")
        sys.exit(result.returncode)


def main() -> None:
    print("\n" + "="*60)
    print("  RPG Translator Pro  –  Build Script")
    print("="*60)

    # 1. Generate icon
    step("Generating application icon...")
    if not ICON.exists():
        run([sys.executable, str(ROOT / "scripts" / "create_icon.py")])
        print(f"  Icon created: {ICON}")
    else:
        print(f"  Icon already exists: {ICON}")

    # 2. Clean previous builds
    #
    # `dist/` is not wiped wholesale: the checkpoint folder lives next to the
    # .exe, and an unapplied translation exists nowhere else on disk, so a
    # rebuild used to throw away hours of work. Only build output is removed.
    step("Cleaning previous build artifacts...")
    if BUILD.exists():
        shutil.rmtree(BUILD)
        print(f"  Removed: {BUILD}")

    if DIST_DIR.exists():
        for path in DIST_DIR.iterdir():
            if path.name == KEEP_IN_DIST:
                count = len(list(path.glob("*.json")))
                print(f"  Kept   : {path.name} ({count} punto(s) de control)")
                continue
            try:
                shutil.rmtree(path) if path.is_dir() else path.unlink()
                print(f"  Removed: {path}")
            except OSError as exc:
                print(f"\nERROR: no se pudo borrar {path}")
                print(f"  {exc}")
                print("  Cierra RPGTranslatorPro.exe si esta abierto y vuelve a intentarlo.")
                sys.exit(1)

    # 3. Run PyInstaller
    step("Running PyInstaller...")
    run([
        sys.executable, "-m", "PyInstaller",
        str(ROOT / "build.spec"),
        "--noconfirm",
        "--clean",
    ])

    # 4. Report result
    step("Finalizing distribution...")
    if DIST_EXE.exists():
        size_mb = DIST_EXE.stat().st_size / (1024 * 1024)
        print(f"\n{'='*60}")
        print(f"  BUILD SUCCESSFUL")
        print(f"  EXE  : {DIST_EXE}")
        print(f"  Size : {size_mb:.1f} MB")
        print(f"{'='*60}\n")
    else:
        print("\nERROR: EXE not found – PyInstaller may have failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
