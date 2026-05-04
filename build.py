"""Build AventusBotHub.exe via PyInstaller.

Usage:
    python build.py

Outputs:
    dist/AventusBotHub.exe + dist/data/ + dist/app-icon.png
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
BUILD = ROOT / "build"
NAME = "AventusBotHub"

# Files in data/ that the user edits via the running exe — never overwrite
# these during rebuild; preserve whatever sits in dist/data/.
USER_DATA_FILES = ("companies.json", "alerts.json", "db.json")


def run_pyinstaller() -> None:
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name",
        NAME,
        "--add-data",
        f"app-icon.png{';' if sys.platform == 'win32' else ':'}.",
        "run.py",
    ]
    subprocess.check_call(cmd, cwd=ROOT)


def stage_runtime() -> None:
    src_data = ROOT / "data"
    dst_data = DIST / "data"
    dst_data.mkdir(parents=True, exist_ok=True)

    # Overlay source onto dist:
    #   - copy files/dirs from source into dist
    #   - never delete anything else in dist (preserves runtime caches like
    #     conversations_cache/, db files, etc.)
    #   - if a file is in USER_DATA_FILES and already exists in dist, keep dist version
    for entry in sorted(src_data.rglob("*")):
        rel = entry.relative_to(src_data)
        rel_str = "/".join(rel.parts)
        target = dst_data / rel
        if entry.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        if rel_str in USER_DATA_FILES and target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(entry, target)

    src_icon = ROOT / "app-icon.png"
    if src_icon.exists():
        shutil.copy2(src_icon, DIST / "app-icon.png")


def main() -> None:
    if BUILD.exists():
        shutil.rmtree(BUILD)
    spec = ROOT / f"{NAME}.spec"
    if spec.exists():
        spec.unlink()
    run_pyinstaller()
    stage_runtime()
    print(f"\nDone. {DIST / (NAME + '.exe')}")


if __name__ == "__main__":
    main()
