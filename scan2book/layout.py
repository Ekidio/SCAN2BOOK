"""Elrendezés-elemzés: az OCR sorokból könyvszedési utasításokat (TPage/TLine) készít.

Minden pozíciót a szövegtükörhöz és a sorközhöz (sorrács) viszonyítva fejezünk ki,
így a kimenet független a fotó felbontásától, vágásától és enyhe torzulásaitól.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .model import Line, PageOCR, Run, TFigure, TLine, TPage

ASC = set("bdfhklt0123456789ÁÉÍÓÖŐÚÜŰáéíóöőúüűäëïÿ!?()[]{}/\\|'\"%&$#@ß")
DESC = set("gjpqyQ(),;[]{}|")


def _word_class(text: str) -> tuple[bool, bool]:
    asc = any(c in ASC or c.isupper() for c in text)
    desc = any(c in DESC for c in text)
    return asc, desc


@dataclass
class PageStats:
    page: PageOCR
    pitch: float | None = None
    body_h: float | None = None
    sizes: list[float] | None = None
    fitL: tuple[float, float] | None = None   # x = a + b*y
    fitR: tuple[float, float] | None = None
    folio_idx: int | None = None
    sizes_px: list[float] | None = None
    local: bool = False                       # elég szöveg a soronkénti szélbecsléshez


def _robust_fit(ys, xs, side: str, tol: float):
    ys = np.asarray(ys, float)
    xs = np.asarray(xs, float)
    keep = np.ones(len(xs), bool)
    a, b = float(np.median(xs)), 0.0
    for _ in range(4):
        if keep.sum() < 3:
            break
        if np.ptp(ys[keep]) > 0:
            b, a = np.polyfit(ys[keep], xs[keep], 1)
        else:
            a, b = float(np.median(xs[keep])), 0.0
        res = xs - (a + b * ys)
        # bal szélnél a behúzott sorok jobbra, jobb szélnél a rövid sorok balra lógnak ki
        new = (res < tol) if side == "L" else (res > -tol)
        new &= np.abs(res) < 6 * tol
        if (new == keep).all():
            break
        keep = new
    if abs(b) > 0.08:   # irreális dőlés – inkább függőleges
        a, b = float(np.median(xs[keep] if keep.any() else xs)), 0.0
    return float(a), float(b)


class BookLayout:
    def __init__(self, pages: list[PageOCR]):
        self.pages = sorted(pages, key=lambda p: p.index)
        self.stats = [PageStats(p) for p in self.pages]
        self._class_h: dict[tuple[bool, bool], float] = {}

    # --- 1. betűméret-kalibráció a szóosztályok (felső/alsó nyúlvány) szerint ---------
    def _calibrate_sizes(self):
        buckets: dict[tuple[bool, bool], list[float]] = {}
        for st in self.stats:
            for ln in st.page.lines:
                if len(ln.words) < 4:
                    continue
                for w in ln.words:
                    if sum(c.isalpha() for c in w.text) < 2:
                        continue
                    buckets.setdefault(_word_class(w.text), []).append(w.h)
        for k, v in buckets.items():
            if len(v) >= 5:
                self._class_h[k] = float(np.median(v))
        if (True, False) not in self._class_h:
            allh = [h for v in buckets.values() for h in v] or [40.0]
            self._class_h[(True, False)] = float(np.median(allh))
        ref = self._class_h[(True, False)]
        defaults = {(False, False): 0.72, (True, False): 1.0, (False, True): 1.0, (True, True): 1.28}
        for k, f in defaults.items():
            self._class_h.setdefault(k, ref * f)

    def _line_size_px(self, ln: Line) -> float:
        """A sor betűméretének becslése (a „felső nyúlványos” szómagasság egységében)."""
        ref = self._class_h[(True, False)]
        vals = []
        for w in ln.words:
            if not any(c.isalpha() for c in w.text):
                continue
            k = _word_class(w.text)
            vals.append(w.h / self._class_h[k] * ref)
        if not vals:
            vals = [ln.word_h]
        return float(np.median(vals))

    # --- 2. oldalankénti geometria ---------------------------------------------------
    def _page_geometry(self, st: PageStats):
        lines = st.page.lines
        if not lines:
            st.sizes = []
            return
        sizes_px = [self._line_size_px(ln) for ln in lines]
        st.sizes_px = sizes_px
        body = [s for s, ln in zip(sizes_px, lines) if len(ln.words) >= 4]
        if len(body) < 2:
            body = [s for s, ln in zip(sizes_px, lines) if len(ln.words) >= 3] or sizes_px
        st.body_h = float(np.median(body))
        st.sizes = [s / st.body_h for s in sizes_px]

        dys = [
            lines[i + 1].cy - lines[i].cy
            for i in range(len(lines) - 1)
            if st.sizes[i] < 1.15 and st.sizes[i + 1] < 1.15
        ]
        if dys:
            med = float(np.median(dys))
            close = [d for d in dys if 0.7 * med < d < 1.3 * med]
            st.pitch = float(np.median(close)) if close else med

        tol = 0.6 * st.body_h
        widths = np.array([ln.x1 - ln.x0 for ln in lines])
        long_ = [i for i, ln in enumerate(lines) if widths[i] >= 0.75 * widths.max() and st.sizes[i] < 1.15]
        if len(long_) >= 3:
            ys = [lines[i].cy for i in long_]
            st.fitL = _robust_fit(ys, [lines[i].x0 for i in long_], "L", tol)
            st.fitR = _robust_fit(ys, [lines[i].x1 for i in long_], "R", tol)

        # oldalszám (élőfej/élőláb): utolsó rövid sor számjeggyel, nagyobb térközzel
        if len(lines) >= 2 and st.pitch:
            for j in (len(lines) - 1, len(lines) - 2):
                if j < 1:
                    continue
                cand = lines[j]
                gap = cand.cy - lines[j - 1].cy
                if any(c.isdigit() for c in cand.text) and len(cand.words) <= 5 and gap > 1.4 * st.pitch:
                    st.folio_idx = j
                    # az oldalszám alatti „sorok” a fotó széléről származó zajok
                    del lines[j + 1:]
                    del st.sizes[j + 1:]
                    del st.sizes_px[j + 1:]
                    break
        elif len(lines) == 1 and any(c.isdigit() for c in lines[0].text) and len(lines[0].words) <= 3:
            st.folio_idx = 0

    # --- 3. könyvszintű értékek -------------------------------------------------------
    def analyze(self) -> list[TPage]:
        self._calibrate_sizes()
        for st in self.stats:
            self._page_geometry(st)

        def n_body(st):
            return sum(1 for ln in st.page.lines if len(ln.words) >= 3)

        good = [st for st in self.stats if st.pitch and st.fitL and st.fitR and n_body(st) >= 6]
        if not good:
            good = [st for st in self.stats if st.pitch]
        if not good:
            raise RuntimeError("Nem sikerült szöveget felismerni a dokumentumban.")

        def tw(st):
            ym = st.page.height / 2
            return (st.fitR[0] + st.fitR[1] * ym) - (st.fitL[0] + st.fitL[1] * ym)

        fitted = [st for st in good if st.fitL and st.fitR]
        self.tw_ratio = float(np.median([tw(st) / st.pitch for st in fitted])) if fitted else 25.0
        book_pitch = float(np.median([st.pitch for st in good]))
        book_body_h = float(np.median([st.body_h for st in good]))
        if fitted:
            book_L = float(np.median([st.fitL[0] + st.fitL[1] * st.page.height / 2 for st in fitted]))
            book_R = float(np.median([st.fitR[0] + st.fitR[1] * st.page.height / 2 for st in fitted]))
        for st in self.stats:
            if not st.page.lines:
                st.pitch = st.pitch or book_pitch
                st.body_h = book_body_h
                continue
            # kevés kenyérszöveg (címoldal, fejezetnyitó, lista): a könyv átlagos mértékei
            if sum(1 for ln in st.page.lines if len(ln.words) >= 4) < 2:
                st.body_h = book_body_h
                st.sizes = [s / book_body_h for s in st.sizes_px]
                st.pitch = book_pitch
            elif not st.pitch:
                st.pitch = book_pitch * st.body_h / book_body_h
            long_lines = sum(1 for ln in st.page.lines if len(ln.words) >= 3)
            st.local = bool(st.fitL and st.fitR) and long_lines >= 6
            if st.local:
                continue   # a szövegtükör széleit soronként, a környező sorokból becsüljük
            ok_fit = st.fitL and st.fitR and abs(tw(st) / st.pitch - self.tw_ratio) < 0.08 * self.tw_ratio
            if not ok_fit and fitted:
                k = st.pitch / book_pitch
                cx = st.page.width / 2 + ((book_L + book_R) / 2 - float(np.median([s.page.width / 2 for s in fitted])))
                st.fitL = (cx - (book_R - book_L) * k / 2, 0.0)
                st.fitR = (cx + (book_R - book_L) * k / 2, 0.0)
        self.page_h_ratio = float(np.median([st.page.height / st.pitch for st in good]))
        self.page_w_ratio = float(np.median([st.page.width / st.pitch for st in good]))

        def first_body(st):
            return next((i for i in range(len(st.page.lines)) if i != st.folio_idx), None)

        tops = []
        for st in good:
            i = first_body(st)
            if i is not None:
                tops.append(st.page.lines[i].cy / st.pitch)
        tops_arr = np.array(tops)
        # a fejezetkezdő (lejjebb kezdődő) oldalak nélkül
        self.top_ratio = float(np.percentile(tops_arr, 35)) if len(tops_arr) else 4.0
        folios = [st.page.lines[st.folio_idx].cy / st.pitch for st in good if st.folio_idx is not None]
        self.folio_ratio = float(np.median(folios)) if folios else None
        self.has_folio = len(folios) >= max(1, 0.3 * len(good))

        # hány sor fér egy oldalra (a leghosszabb oldal alapján)
        self.max_grid = 0.0

        tpages = [self._page_to_tpage(st) for st in self.stats]
        self._snap_indents(tpages)
        extents = [self.page_extent(tp) for tp in tpages if tp.lines or tp.figures]
        # a tipikus (nem kilógó) oldalhossz; a hosszabb oldalakat a szedő sűríti
        self.max_grid = float(np.percentile(extents, 90)) if extents else 30.0
        return tpages

    @staticmethod
    def page_extent(tp: TPage) -> float:
        e = 0.0
        for tl in tp.lines:
            e = max(e, tl.grid + (tl.size - 1) * 0.5)
        for f in tp.figures:
            e = max(e, f.grid + f.h - 0.5)
        return e

    def _local_edges(self, st: PageStats, y: float) -> tuple[float, float]:
        """A szövegtükör bal/jobb széle az y magasságban, a környező sorok alapján.
        A bal szél a sorkezdetek alsó burkolója (a behúzott és középre zárt sorok
        jobbra esnek), a jobb szél a sorvégek felső burkolója. Így követi a fotó
        hajlását, ferdeségét, sőt a lépcsős elcsúszást is."""
        tol = 0.6 * st.body_h
        lines = [ln for i, ln in enumerate(st.page.lines) if i != st.folio_idx and st.sizes[i] < 1.15]
        widths = [ln.x1 - ln.x0 for ln in lines]
        wmax = max(widths) if widths else 1.0
        for win in (8, 14, 25, 1e9):
            near = [ln for ln in lines if abs(ln.cy - y) <= win * st.pitch]
            longs = [ln for ln in near if ln.x1 - ln.x0 >= 0.75 * wmax]
            if len(near) >= 5 and len(longs) >= 2:
                break

        def envelope(vals: list[float], low: bool) -> float:
            vals = sorted(vals, reverse=not low)
            base = vals[1] if len(vals) >= 5 else vals[0]   # egy kilógó zaj ne vigye el
            sel = [v for v in vals if abs(v - base) <= tol]
            return float(np.median(sel))

        L = envelope([ln.x0 for ln in near], True)
        R = envelope([ln.x1 for ln in longs], False)
        return L, R

    def _edges(self, st: PageStats, y: float) -> tuple[float, float]:
        if st.local:
            return self._local_edges(st, y)
        if st.fitL and st.fitR:
            return st.fitL[0] + st.fitL[1] * y, st.fitR[0] + st.fitR[1] * y
        lines = [ln for i, ln in enumerate(st.page.lines) if i != st.folio_idx]
        xs = sorted(ln.x0 for ln in lines) or [0.0]
        L = xs[max(0, len(xs) // 4 - 1)] if len(xs) > 3 else xs[0]
        W = self.tw_ratio * st.pitch
        # ha a sorok többsége középre zárt, a szövegtükröt a lap közepére tesszük
        cx = np.median([(ln.x0 + ln.x1) / 2 for ln in lines]) if lines else st.page.width / 2
        if lines and all(abs((ln.x0 + ln.x1) / 2 - cx) < 0.05 * W for ln in lines) and len(lines) > 1:
            L = cx - W / 2
        return L, L + W

    def _smooth_sizes(self, st: PageStats) -> list[float]:
        """Az egymást követő, nem sorkizárt (középre zárt címek, listák) sorok
        méretbecslése zajos: csoportonként mediánnal egységesítjük."""
        lines = st.page.lines
        sizes = list(st.sizes)
        groups: list[list[int]] = []
        for i, ln in enumerate(lines):
            centered = self._is_centered(st, ln)
            if centered and groups and groups[-1][-1] == i - 1 \
                    and abs(sizes[i] - float(np.median([sizes[j] for j in groups[-1]]))) < 0.22 \
                    and ln.cy - lines[i - 1].cy < 2.2 * st.pitch:
                groups[-1].append(i)
            elif centered:
                groups.append([i])
        for g in groups:
            if len(g) >= 2:
                med = float(np.median([sizes[i] for i in g]))
                for i in g:
                    sizes[i] = med
        return sizes

    @staticmethod
    def _isolated(st: PageStats, i: int, p: float) -> bool:
        """Térköz van-e a sor fölött és alatt (a címek így állnak a szövegben)."""
        if i == st.folio_idx:
            return True
        lines = [j for j in range(len(st.page.lines)) if j != st.folio_idx]
        k = lines.index(i)
        cy = st.page.lines[i].cy
        before = (cy - st.page.lines[lines[k - 1]].cy) / p if k > 0 else 99.0
        after = (st.page.lines[lines[k + 1]].cy - cy) / p if k + 1 < len(lines) else 99.0
        return before >= 1.6 and after >= 1.6

    def _is_centered(self, st: PageStats, ln: Line) -> bool:
        L, R = self._edges(st, ln.cy)
        em = st.body_h
        dl, dr = ln.x0 - L, R - ln.x1
        return dl > 1.4 * em and abs(dl - dr) < max(1.2 * em, 0.06 * (R - L))

    def _page_to_tpage(self, st: PageStats) -> TPage:
        lines = st.page.lines
        tp = TPage(st.page.index, [])
        if not lines and not st.page.figures:
            return tp
        p = st.pitch or (self.page_h_ratio and st.page.height / self.page_h_ratio)
        anchors: list[tuple[float, float]] = []
        em = st.body_h
        grid = None
        prev_cy = None
        prev_size = 1.0
        first = True
        sizes = self._smooth_sizes(st)
        for i, ln in enumerate(lines):
            size = sizes[i]
            size_q = 1.0 if size < 1.18 else round(size * 4) / 4
            L, R = self._edges(st, ln.cy)
            W = max(R - L, 1.0)
            dl = ln.x0 - L
            dr = R - ln.x1
            if dr < 0.7 * em and dl < 0.5 * W:
                align = "justify"
            elif dl > 1.4 * em and abs(dl - dr) < max(1.2 * em, 0.06 * W):
                align = "center"
            elif dr < 0.7 * em and dl >= 0.5 * W:
                align = "right"
            else:
                align = "left"
            indent = max(0.0, dl / W) if align in ("justify", "left") else 0.0
            if indent < 0.3 * em / W:
                indent = 0.0
            if size_q > 1.0 and align != "center" and not self._isolated(st, i, p):
                # nem középre zárt és a kenyérszöveg ritmusában álló sor nem cím: a
                # nagyobb méretbecslés csak zaj (kevés szó, torzult/életlen fotórészlet)
                size_q = 1.0

            runs = [Run(w.text, w.italic) for w in ln.words]
            if i == st.folio_idx:
                # oldalszám: csak akkor szélre zárt, ha tényleg a margónál áll
                fal = "left" if dl < 1.0 * em else "right" if dr < 1.0 * em else "center"
                tp.folio = TLine(runs, fal, 0.0, 0.0, 1.0, "folio")
                continue

            if first:
                k = ln.cy / p - self.top_ratio
                grid = float(round(k)) if k >= 1.5 else 0.0
                first = False
            else:
                step = (ln.cy - prev_cy) / p
                if size_q > 1.0 or prev_size > 1.0:
                    # címek, listák: a valódi ritmust tartjuk (nem a kenyérszöveg rácsát)
                    step = max(0.8, round(step * 10) / 10)
                else:
                    step = max(1.0, float(round(step)))
                grid += step
            prev_cy = ln.cy
            prev_size = size_q
            anchors.append((ln.cy, grid))
            role = "heading" if size_q > 1.0 else "body"
            tp.lines.append(TLine(runs, align, indent, grid, size_q, role))

        for f in st.page.figures:
            prev = [a for a in anchors if a[0] <= f.y0]
            if prev:
                g = prev[-1][1] + (f.y0 - prev[-1][0]) / p
            elif anchors:
                g = anchors[0][1] - (anchors[0][0] - f.y0) / p
            else:
                g = f.y0 / p - self.top_ratio
            cy = (f.y0 + f.y1) / 2
            L, R = self._edges(st, cy) if lines else (
                st.page.width / 2 - self.tw_ratio * p / 2, st.page.width / 2 + self.tw_ratio * p / 2)
            W = max(R - L, 1.0)
            tp.figures.append(TFigure(f.path, (f.x0 - L) / W, (f.x1 - f.x0) / W, g, (f.y1 - f.y0) / p))
        return tp

    def _snap_indents(self, tpages: list[TPage]):
        inds = [tl.indent for tp in tpages for tl in tp.lines if tl.indent > 0 and tl.role == "body"]
        if not inds:
            self.par_indent = 0.0
            return
        med = float(np.median(inds))
        self.par_indent = med
        for tp in tpages:
            for tl in tp.lines:
                if tl.indent > 0 and 0.45 * med < tl.indent < 1.7 * med:
                    tl.indent = med
                elif 0 < tl.indent <= 0.45 * med:
                    tl.indent = 0.0   # a fotó torzulásából eredő hamis mini-behúzás
