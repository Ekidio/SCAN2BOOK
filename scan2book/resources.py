"""Erőforrások (betűk, OCR-adatok, Tesseract) helye – fejlesztői futtatásnál és
becsomagolt (PyInstaller) Windows/macOS appban is."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def resource_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


ROOT = resource_root()
FONT_DIR = ROOT / "fonts"
TESSDATA_DIR = ROOT / "tessdata"

# Windowson ne villanjon fel konzolablak a Tesseract futtatásakor
NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def find_tesseract() -> str:
    exe_name = "tesseract.exe" if os.name == "nt" else "tesseract"
    bundled = ROOT / "tesseract" / exe_name
    if bundled.exists():
        return str(bundled)
    found = shutil.which("tesseract")
    if found:
        return found
    candidates = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        "/opt/homebrew/bin/tesseract", "/usr/local/bin/tesseract", "/usr/bin/tesseract",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    raise RuntimeError("A Tesseract OCR nem található. macOS: brew install tesseract; "
                       "Windows: https://github.com/UB-Mannheim/tesseract/wiki")


def cache_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "SCAN2BOOK" / "cache"
    else:
        base = Path.home() / ".cache" / "scan2book"
    # a korábbi (PDF2BOOK nevű) változat gyorsítótárának átvétele
    old = base.parent.parent / "PDF2BOOK" / "cache" if os.name == "nt" else base.parent / "pdf2book"
    if old.exists() and not base.exists():
        base.parent.mkdir(parents=True, exist_ok=True)
        try:
            old.rename(base)
        except OSError:
            pass
    base.mkdir(parents=True, exist_ok=True)
    return base
