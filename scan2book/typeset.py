"""Könyvszerű szedés PyMuPDF-fel: egységes sorrács, sorkizárás, valódi (kereshető) szöveg."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pymupdf

from .layout import BookLayout
from .model import TLine, TPage
from .resources import FONT_DIR



@dataclass
class FontSet:
    regular: pymupdf.Font
    italic: pymupdf.Font

    @staticmethod
    def load(family: str = "LibertinusSerif") -> "FontSet":
        def f(style: str, fallback: str) -> pymupdf.Font:
            p = FONT_DIR / f"{family}-{style}.otf"
            if not p.exists():
                p = FONT_DIR / f"{family}-{style}.ttf"
            if p.exists():
                return pymupdf.Font(fontfile=str(p))
            return pymupdf.Font(fallback)   # beépített Times (nincs ő/ű!) – csak vészmegoldás
        return FontSet(f("Regular", "tiro"), f("Italic", "tiit"))

    def get(self, italic: bool) -> pymupdf.Font:
        return self.italic if italic else self.regular


@dataclass
class Geometry:
    fs: float          # kenyérszöveg betűmérete (pt)
    lead: float        # sorköz (pt)
    tw: float          # szövegtükör szélessége (pt)
    page_w: float
    page_h: float
    left: float
    top: float         # a 0. sor középvonala (pt)
    folio_y: float | None


def _natural(tl: TLine, fonts: FontSet, fs: float) -> tuple[list[float], float]:
    widths = [fonts.get(r.italic).text_length(r.text, fs) for r in tl.words]
    return widths, fonts.regular.text_length(" ", fs)


def compute_geometry(book: BookLayout, tpages: list[TPage], fonts: FontSet, fs: float = 11.0) -> Geometry:
    # a szövegtükör szélessége: a sorkizárt sorok természetes hosszának mediánja
    ratios = []
    for tp in tpages:
        for tl in tp.lines:
            if tl.align != "justify" or tl.role != "body" or len(tl.words) < 4:
                continue
            ws, sp = _natural(tl, fonts, 1.0)
            nat = sum(ws) + sp * (len(ws) - 1)
            ratios.append(nat / max(0.5, 1.0 - tl.indent))
    k = float(np.median(ratios)) if ratios else 60.0
    tw = fs * k * 1.01
    lead = tw / book.tw_ratio
    # keskeny betűnél ne legyen túl szoros a sorköz: inkább kicsit kisebb betű
    if lead < 1.13 * fs:
        fs = lead / 1.13
    page_w = book.page_w_ratio * lead
    page_h = book.page_h_ratio * lead
    top = book.top_ratio * lead
    folio_y = book.folio_ratio * lead if book.has_folio and book.folio_ratio else None
    # ne lógjon ki semmi a lapról
    bottom_needed = top + (book.max_grid + 1.0) * lead
    if folio_y is not None:
        folio_y = max(folio_y, bottom_needed + 0.5 * lead)
        page_h = max(page_h, folio_y + 2.5 * lead)
    else:
        page_h = max(page_h, bottom_needed + 2.5 * lead)
    page_w = max(page_w, tw + 4 * fs)
    return Geometry(fs, lead, tw, page_w, page_h, (page_w - tw) / 2, top, folio_y)


def _set_line(page: pymupdf.Page, tl: TLine, g: Geometry, fonts: FontSet, y_center: float, last_in_par: bool):
    fs = g.fs * tl.size
    widths, sp = _natural(tl, fonts, fs)
    n = len(widths)
    if n == 0:
        return
    avail = g.tw * (1.0 - tl.indent)
    x0 = g.left + g.tw * tl.indent
    gap = sp
    sx = 1.0
    align = tl.align
    if align == "justify" and n > 1:
        gap = (avail - sum(widths)) / (n - 1)
        # extrém ritkítás helyett inkább balra zárás (pl. hibás felismerés)
        if gap > 3.5 * sp:
            gap = sp
            align = "left"
    if gap < 0.7 * sp:      # túl hosszú sor: minimális szóköz + enyhe vízszintes tömörítés
        gap = 0.7 * sp
    total = sum(widths) + gap * (n - 1)
    if total > avail:
        sx = max(0.8, avail / total)
    if align == "center":
        x0 = g.left + (g.tw - total * sx) / 2
    elif align == "right":
        x0 = g.left + g.tw - total * sx

    baseline = y_center + 0.27 * fs
    writer = pymupdf.TextWriter(page.rect)
    x = x0
    for i, (r, w) in enumerate(zip(tl.words, widths)):
        txt = r.text + (" " if i < n - 1 else "")
        writer.append((x, baseline), txt, font=fonts.get(r.italic), fontsize=fs)
        x += w + gap
    morph = (pymupdf.Point(x0, baseline), pymupdf.Matrix(sx, 1)) if sx < 0.999 else None
    writer.write_text(page, morph=morph)


def typeset(tpages: list[TPage], g: Geometry, fonts: FontSet, out_path: str, title: str = "") -> None:
    doc = pymupdf.open()
    limit = (g.folio_y - 1.5 * g.lead) if g.folio_y is not None else g.page_h - 2.5 * g.lead
    for tp in tpages:
        page = doc.new_page(width=g.page_w, height=g.page_h)
        # túl hosszú oldal (pl. hibás sorbecslés): a sorközt arányosan sűrítjük
        ext = BookLayout.page_extent(tp)
        lead = g.lead
        if ext > 0 and g.top + ext * lead > limit:
            lead = max(0.8 * g.lead, (limit - g.top) / ext)
        for tl in tp.lines:
            yc = g.top + tl.grid * lead
            _set_line(page, tl, g, fonts, yc, False)
        for f in tp.figures:
            r = pymupdf.Rect(g.left + f.x * g.tw, g.top + f.grid * lead,
                             g.left + (f.x + f.w) * g.tw, g.top + (f.grid + f.h) * lead)
            if Path(f.path).exists():
                page.insert_image(r, filename=f.path, keep_proportion=True)
        if tp.folio and tp.folio.words:
            yc = g.folio_y if g.folio_y is not None else g.page_h - 2 * g.lead
            al = tp.folio.align if tp.folio.align in ("left", "right") else "center"
            f = TLine(tp.folio.words, al, 0.0, 0.0, 1.0, "folio")
            _set_line(page, f, g, fonts, yc, False)
    doc.set_metadata({"title": title, "producer": "SCAN2BOOK", "creator": "SCAN2BOOK"})
    doc.save(out_path, garbage=3, deflate=True)
    doc.close()
