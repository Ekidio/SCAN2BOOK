"""A teljes folyamat: fotózott PDF → OCR → elrendezés → könyvszerű PDF."""
from __future__ import annotations

import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pymupdf

from .layout import BookLayout
from .resources import cache_dir
from .model import PageOCR
from .ocr import ocr_page
from .textfix import fix_consistency, fix_folios, fix_typography
from .typeset import FontSet, compute_geometry, typeset

CACHE_VERSION = 6
Progress = Callable[[float, str], None]


@dataclass
class Options:
    lang: str = "hun"
    italics: bool = True
    font_size: float = 11.0
    pages: list[int] | None = None       # 0-alapú oldalindexek; None = mind
    workers: int = max(1, (os.cpu_count() or 4) - 1)
    use_cache: bool = True
    dewarp: bool = True
    font: str = "LibertinusSerif"


def parse_page_range(spec: str, n: int) -> list[int] | None:
    """„1-5, 8, 10-” → 0-alapú indexlista."""
    spec = (spec or "").strip()
    if not spec:
        return None
    out: list[int] = []
    for part in spec.replace(" ", "").split(","):
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            a_i = int(a) if a else 1
            b_i = int(b) if b else n
            out.extend(range(a_i - 1, min(b_i, n)))
        else:
            out.append(int(part) - 1)
    return sorted({i for i in out if 0 <= i < n})


def _cache_dir() -> Path:
    return cache_dir()


def _file_key(path: str) -> str:
    st = os.stat(path)
    h = hashlib.sha1(f"{os.path.abspath(path)}|{st.st_size}|{st.st_mtime_ns}".encode())
    return h.hexdigest()[:16]


def run_ocr(pdf: str, opts: Options, progress: Progress) -> list[PageOCR]:
    doc = pymupdf.open(pdf)
    n = doc.page_count
    doc.close()
    indices = opts.pages if opts.pages is not None else list(range(n))
    cache_file = _cache_dir() / f"{_file_key(pdf)}-{opts.lang}-{int(opts.italics)}{int(opts.dewarp)}-v{CACHE_VERSION}.json"
    cache: dict[str, dict] = {}
    if opts.use_cache and cache_file.exists():
        try:
            cache = json.loads(cache_file.read_text())
        except Exception:
            cache = {}

    results: dict[int, PageOCR] = {}
    todo = []
    for i in indices:
        if str(i) in cache:
            results[i] = PageOCR.from_dict(cache[str(i)])
        else:
            todo.append(i)
    done = len(results)
    progress(0.8 * done / max(1, len(indices)), f"OCR: {done}/{len(indices)} oldal (gyorsítótárból)")
    if todo:
        with ThreadPoolExecutor(max_workers=opts.workers) as ex:
            fig_dir = cache_file.with_suffix("")
            fig_dir.mkdir(exist_ok=True)
            futs = {ex.submit(ocr_page, pdf, i, opts.lang, opts.italics, opts.dewarp,
                              str(fig_dir / f"p{i:04d}")): i for i in todo}
            for fut in as_completed(futs):
                i = futs[fut]
                results[i] = fut.result()
                cache[str(i)] = results[i].to_dict()
                done += 1
                progress(0.8 * done / len(indices), f"OCR: {done}/{len(indices)} oldal")
        if opts.use_cache:
            cache_file.write_text(json.dumps(cache, ensure_ascii=False))
    return [results[i] for i in indices]


def convert(pdf: str, out: str, opts: Options | None = None, progress: Progress | None = None) -> str:
    opts = opts or Options()
    progress = progress or (lambda f, m: None)
    progress(0.0, "Oldalak előkészítése…")
    pages = run_ocr(pdf, opts, progress)

    progress(0.82, "Elrendezés elemzése…")
    book = BookLayout(pages)
    tpages = book.analyze()
    fix_typography(tpages)
    fix_consistency(tpages)
    fix_folios(tpages)

    progress(0.9, "Szedés…")
    fonts = FontSet.load(opts.font)
    geom = compute_geometry(book, tpages, fonts, opts.font_size)
    typeset(tpages, geom, fonts, out, title=Path(pdf).stem)
    progress(1.0, f"Kész: {out}")
    return out
