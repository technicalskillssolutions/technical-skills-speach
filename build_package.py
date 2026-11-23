#!/usr/bin/env python3
"""Build the installable NVDA add-on archive from addon/ without extra tools."""
from __future__ import annotations

import compileall
import hashlib
import os
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ADDON = ROOT / "addon"
DIST = ROOT / "dist"
ADDON_FILE = DIST / "TechnicalSkillsSpeech.nvda-addon"

REQUIRED = [
    ADDON / "manifest.ini",
    ADDON / "synthDrivers" / "technicalSkillsSpeech.py",
    ADDON / "synthDrivers" / "_tss_eloquence_backend.py",
    ADDON / "synthDrivers" / "_tss_vocalizer_backend" / "__init__.py",
    ADDON / "hii" / "speech" / "components" / "hii_neel_embedded-compact_1-0-0.dat",
]


def validate_tree() -> None:
    missing = [str(path.relative_to(ROOT)) for path in REQUIRED if not path.is_file()]
    if missing:
        raise SystemExit("Missing required add-on files:\n" + "\n".join(missing))
    # Keep py_compile output out of the distributable archive.
    ok = compileall.compile_dir(str(ADDON / "synthDrivers"), quiet=1, force=True)
    if not ok:
        raise SystemExit("Python syntax compilation failed")
    # Remove generated cache folders so .pyc files are not shipped.
    for cache in ADDON.rglob("__pycache__"):
        for item in cache.iterdir():
            item.unlink(missing_ok=True)
        cache.rmdir()


def build_addon() -> str:
    DIST.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ADDON_FILE, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(ADDON.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            archive.write(path, path.relative_to(ADDON).as_posix())
    digest = hashlib.sha256(ADDON_FILE.read_bytes()).hexdigest()
    return digest


def main() -> int:
    validate_tree()
    digest = build_addon()
    print(f"Created: {ADDON_FILE}")
    print(f"Size: {ADDON_FILE.stat().st_size:,} bytes")
    print(f"SHA256: {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
