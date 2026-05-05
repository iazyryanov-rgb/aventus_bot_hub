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
USER_DATA_FILES = (
    "companies.json",
    "alerts.json",
    "db.json",
    "settings.json",
    "crm_field_types_overrides.json",
    "action_tree_overrides.json",
)


def _ensure_ico() -> Path:
    """Build app-icon.ico from app-icon.png with BMP-encoded sub-icons for
    sizes <256 (legacy-compatible) and a PNG-encoded 256x256 entry. Some
    Windows shells refuse to render PNG-only ICOs in Explorer thumbnails."""
    src = ROOT / "app-icon.png"
    dst = ROOT / "app-icon.ico"
    if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
        return dst
    try:
        from PIL import Image
    except ImportError:
        return dst if dst.exists() else src

    import io
    import struct

    base = Image.open(src).convert("RGBA")
    w, h = base.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    sq = base.crop((left, top, left + side, top + side))

    sizes = [16, 24, 32, 48, 64, 128, 256]
    entries: list[tuple[int, int]] = []
    payloads: list[bytes] = []
    for s in sizes:
        im = sq.resize((s, s), Image.LANCZOS)
        if s == 256:
            buf = io.BytesIO()
            im.save(buf, format="PNG")
            payloads.append(buf.getvalue())
        else:
            buf = io.BytesIO()
            im.save(buf, format="BMP")
            bmp = buf.getvalue()[14:]  # strip BITMAPFILEHEADER, leave DIB
            header = bytearray(bmp[:40])
            h_val = struct.unpack_from("<i", header, 8)[0]
            struct.pack_into("<i", header, 8, h_val * 2)
            and_row = ((s + 31) // 32) * 4
            and_mask = b"\x00" * (and_row * s)
            payloads.append(bytes(header) + bmp[40:] + and_mask)
        entries.append((s, len(payloads[-1])))

    out = io.BytesIO()
    out.write(struct.pack("<HHH", 0, 1, len(sizes)))
    offset = 6 + 16 * len(sizes)
    for (s, sz), _ in zip(entries, payloads):
        width = 0 if s == 256 else s
        height = 0 if s == 256 else s
        out.write(struct.pack("<BBBBHHII", width, height, 0, 0, 1, 32, sz, offset))
        offset += sz
    for data in payloads:
        out.write(data)
    dst.write_bytes(out.getvalue())
    return dst


def run_pyinstaller() -> None:
    sep = ";" if sys.platform == "win32" else ":"
    ico = _ensure_ico()
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
        "--icon",
        str(ico),
        "--add-data",
        f"app-icon.png{sep}.",
        "--add-data",
        f"app-icon.ico{sep}.",
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
    src_ico = ROOT / "app-icon.ico"
    if src_ico.exists():
        shutil.copy2(src_ico, DIST / "app-icon.ico")


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
