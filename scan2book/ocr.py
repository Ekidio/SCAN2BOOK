"""Oldalképek előállítása, előfeldolgozása és OCR (Tesseract) + dőlt betű felismerés."""
from __future__ import annotations

import csv
import io
import os
import subprocess
from pathlib import Path

import cv2
import numpy as np
import pymupdf

from .model import Figure, Line, PageOCR, Word
from .resources import NO_WINDOW, TESSDATA_DIR, find_tesseract

LOCAL_TESSDATA = TESSDATA_DIR

# A cél-felbontás: a szöveg x-magassága kb. 20-30 px legyen az OCR-hez.
TARGET_LONG_SIDE = 2900


def render_page(doc: pymupdf.Document, index: int) -> np.ndarray:
    """Az oldalt szürkeárnyalatos képként adja vissza, OCR-hez megfelelő felbontásban."""
    page = doc[index]
    long_side = max(page.rect.width, page.rect.height)
    zoom = TARGET_LONG_SIDE / long_side
    # ha egyetlen beágyazott fotó van az oldalon, ne nagyítsunk feleslegesen túl a 2x-esen
    imgs = page.get_images()
    if len(imgs) == 1:
        native = max(imgs[0][2], imgs[0][3])
        zoom = min(zoom, 2.2 * native / long_side) if native else zoom
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csGRAY, alpha=False)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
    return img.copy()


def normalize(gray: np.ndarray) -> np.ndarray:
    """Háttér-kiegyenlítés: eltünteti az árnyékokat, papírszín-különbségeket."""
    k = max(15, (gray.shape[1] // 60) | 1)
    bg = cv2.dilate(gray, cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))
    bg = cv2.medianBlur(bg, k if k % 2 else k + 1)
    norm = cv2.divide(gray, bg, scale=255)
    # enyhe kontrasztnövelés
    norm = cv2.normalize(norm, None, 0, 255, cv2.NORM_MINMAX)
    return norm


def run_tesseract(img: np.ndarray, lang: str, psm: int = 3) -> list[dict]:
    exe = find_tesseract()
    tessdata = LOCAL_TESSDATA if LOCAL_TESSDATA.exists() else None
    ok, png = cv2.imencode(".png", img)
    # a kép a szabványos bemeneten megy át: nincs ideiglenes fájl, nincs gond ékezetes útvonallal
    cmd = [exe, "stdin", "stdout", "-l", lang, "--psm", str(psm), "--dpi", "300"]
    if tessdata:
        cmd += ["--tessdata-dir", str(tessdata)]
    cmd += ["-c", "tessedit_create_tsv=1", "-c", "tessedit_create_txt=0"]
    env = dict(os.environ, OMP_THREAD_LIMIT="1")
    res = subprocess.run(cmd, input=png.tobytes(), capture_output=True, env=env, **NO_WINDOW)
    if res.returncode != 0:
        raise RuntimeError(f"Tesseract hiba: {res.stderr.decode('utf-8', 'replace').strip()}")
    stdout = res.stdout.decode("utf-8", "replace")
    rows = list(csv.DictReader(io.StringIO(stdout), delimiter="\t", quoting=csv.QUOTE_NONE))
    return rows


def tsv_to_lines(rows: list[dict]) -> list[Line]:
    groups: dict[tuple, list[Word]] = {}
    order: list[tuple] = []
    for r in rows:
        if r.get("level") != "5":
            continue
        text = (r.get("text") or "").strip()
        if not text:
            continue
        conf = float(r["conf"])
        x, y, w, h = (int(r[k]) for k in ("left", "top", "width", "height"))
        key = (r["block_num"], r["par_num"], r["line_num"])
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(Word(text, x, y, x + w, y + h, conf))
    return [Line(groups[k]) for k in order]


def clean_lines(lines: list[Line], width: int, height: int) -> list[Line]:
    if not lines:
        return []
    body_h = float(np.median([ln.word_h for ln in lines if len(ln.words) >= 3] or [ln.word_h for ln in lines]))

    def is_noise(ln: Line) -> bool:
        txt = ln.text
        alnum = sum(c.isalnum() for c in txt)
        mean_conf = float(np.mean([w.conf for w in ln.words]))
        if alnum == 0:
            return True
        if mean_conf < 35 and len(ln.words) <= 3:
            return True
        # a lapszélen lévő árnyékból / szomszéd oldalból adódó töredékek
        if (ln.x1 < width * 0.08 or ln.x0 > width * 0.92) and len(ln.words) <= 2:
            return True
        if ln.word_h > body_h * 4:
            return True
        # a fotó legszéle (szomszéd lap, asztal, ujjak)
        if ln.cy > 0.975 * height or ln.cy < 0.015 * height:
            return True
        if mean_conf < 45 and len(ln.words) >= 2 and alnum < 0.6 * len(txt.replace(" ", "")):
            return True
        return False

    lines = [ln for ln in lines if not is_noise(ln)]
    # szavanként: nagyon rossz konfidenciájú, nagyon kicsi vagy óriási „szavak” eldobása
    for ln in lines:
        ln.words = [w for w in ln.words if not (w.conf < 10 and not any(c.isalnum() for c in w.text))]
    lines = [ln for ln in lines if ln.words]

    # függőlegesen átfedő, vízszintesen diszjunkt sorok összevonása (görbült lapok)
    lines.sort(key=lambda l: l.cy)
    merged: list[Line] = []
    for ln in lines:
        if merged:
            prev = merged[-1]
            ov = min(prev.y1, ln.y1) - max(prev.y0, ln.y0)
            if ov > 0.5 * min(prev.y1 - prev.y0, ln.y1 - ln.y0) and abs(prev.cy - ln.cy) < 0.5 * body_h and (
                ln.x0 >= prev.x1 - 2 or ln.x1 <= prev.x0 + 2
            ):
                prev.words = sorted(prev.words + ln.words, key=lambda w: w.x0)
                continue
        merged.append(ln)
    for ln in merged:
        ln.words.sort(key=lambda w: w.x0)
    return merged


# --- dőlt betű felismerés -------------------------------------------------------

_SHEARS = np.linspace(-0.12, 0.42, 19)


def word_slant(binimg: np.ndarray, w: Word) -> float:
    """A szó domináns dőlésszöge (nyírás): ~0 álló, ~0.2-0.3 dőlt betű."""
    x0, y0, x1, y1 = int(w.x0), int(w.y0), int(w.x1), int(w.y1)
    hgt = y1 - y0
    pad = int(hgt * 0.5) + 2
    crop = binimg[max(0, y0):y1, max(0, x0 - pad):x1 + pad]
    if crop.size == 0 or crop.sum() == 0:
        return 0.0
    crop = crop.astype(np.float32)
    hh, ww = crop.shape
    yc = hh / 2
    best_s, best_v = 0.0, -1.0
    for s in _SHEARS:
        m = np.float32([[1, s, -s * yc], [0, 1, 0]])
        sh = cv2.warpAffine(crop, m, (ww, hh), flags=cv2.INTER_LINEAR, borderValue=0)
        prof = sh.sum(axis=0)
        v = float((prof * prof).sum())
        if v > best_v:
            best_v, best_s = v, float(s)
    return best_s


def detect_italics(norm: np.ndarray, lines: list[Line]) -> None:
    _, binimg = cv2.threshold(norm, 0, 1, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    slants: list[tuple[Word, float]] = []
    for ln in lines:
        for w in ln.words:
            letters = sum(c.isalpha() for c in w.text)
            if letters >= 2:
                slants.append((w, word_slant(binimg, w)))
    if not slants:
        return
    # az oldal álló betűinek alap-dőlése (fotó torzulás) – medián
    base = float(np.median([s for _, s in slants]))
    raw: dict[int, bool] = {}
    for w, s in slants:
        letters = sum(c.isalpha() for c in w.text)
        raw[id(w)] = (s - base) >= (0.14 if letters >= 4 else 0.2)
    # rövid szavak (kevés függőleges szár → bizonytalan mérés) és írásjelek:
    # csak dőlt szomszéd mellett lehetnek dőltek
    for ln in lines:
        ws = ln.words
        letters = [sum(c.isalpha() for c in w.text) for w in ws]
        for i, w in enumerate(ws):
            if letters[i] >= 4:
                w.italic = raw.get(id(w), False)
        for i, w in enumerate(ws):
            if letters[i] >= 4:
                continue
            left = ws[i - 1] if i > 0 else None
            right = ws[i + 1] if i + 1 < len(ws) else None
            li = bool(left and left.italic)
            ri = bool(right and right.italic)
            if letters[i] >= 1:
                long_nb = (li and letters[i - 1] >= 4) or (ri and letters[i + 1] >= 4)
                w.italic = (raw.get(id(w), False) and long_nb) or (li and ri)
            else:
                w.italic = li and (right is None or ri)


# --- lapgörbület-kiegyenesítés (dewarp) -------------------------------------------

def dewarp(norm: np.ndarray) -> np.ndarray:
    """A szövegsorok középvonalai alapján függőleges eltolásmezőt becsül és
    kiegyenesíti a hajlott / ferde sorokat. Ha nincs elég megbízható sor, változatlanul hagyja."""
    H, W = norm.shape
    _, bw = cv2.threshold(norm, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    bw = cv2.morphologyEx(bw, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    # betűk → sorfoltok
    kw = max(15, W // 45)
    smear = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (kw, 1)))
    smear = cv2.morphologyEx(smear, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (kw, 3)))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(smear, 8)
    if n < 4:
        return norm
    hs = stats[1:, cv2.CC_STAT_HEIGHT]
    ws = stats[1:, cv2.CC_STAT_WIDTH]
    cand = [i + 1 for i in range(n - 1) if ws[i] > 0.3 * W]
    if len(cand) < 4:
        return norm
    med_h = float(np.median(hs[[c - 1 for c in cand]]))

    step = max(8, W // 120)
    xs_grid = np.arange(0, W, step)
    samples: list[list[tuple[float, float]]] = [[] for _ in xs_grid]
    for c in cand:
        x, y, w, h = stats[c, :4]
        if h > 3.0 * med_h:
            continue
        sub = (lab[y:y + h, x:x + w] == c) & (bw[y:y + h, x:x + w] > 0)
        cols, ys_, = [], []
        for cx in range(0, w, step):
            col = sub[:, cx:cx + step]
            yy, _ = np.nonzero(col)
            if len(yy) >= 3:
                cols.append(x + cx + step / 2)
                ys_.append(y + float(np.median(yy)))
        if len(cols) < 6:
            continue
        cols_a, ys_a = np.array(cols), np.array(ys_)
        deg = 3 if w > 0.6 * W else 2
        coef = np.polyfit(cols_a, ys_a, deg)
        res = ys_a - np.polyval(coef, cols_a)
        ok = np.abs(res) < 0.35 * med_h
        if ok.sum() < 6:
            continue
        coef = np.polyfit(cols_a[ok], ys_a[ok], deg)
        ref_y = float(np.polyval(coef, x + w / 2))
        x_lo, x_hi = x, x + w
        for gi, gx in enumerate(xs_grid):
            # rövid kinyúlás engedett a sor két végén túl (lineárisan)
            if gx < x_lo - 0.1 * W or gx > x_hi + 0.1 * W:
                continue
            gxc = min(max(gx, x_lo), x_hi)
            yv = float(np.polyval(coef, gxc))
            if gx != gxc:
                slope = float(np.polyval(np.polyder(coef), gxc))
                yv += slope * (gx - gxc)
            samples[gi].append((yv, yv - ref_y))
    good_cols = [i for i, s in enumerate(samples) if len(s) >= 3]
    if len(good_cols) < len(xs_grid) * 0.3:
        return norm

    ys_full = np.arange(0, H, step)
    disp = np.full((len(ys_full), len(xs_grid)), np.nan, np.float32)
    for gi in good_cols:
        pts = sorted(samples[gi])
        py = np.array([p[0] for p in pts])
        pd = np.array([p[1] for p in pts])
        disp[:, gi] = np.interp(ys_full, py, pd)
    # hiányzó oszlopok: vízszintes interpoláció soronként
    gc = np.array(good_cols)
    for r in range(disp.shape[0]):
        disp[r] = np.interp(np.arange(len(xs_grid)), gc, disp[r, gc])
    if np.nanmax(np.abs(disp)) < 1.0:
        return norm
    disp = cv2.GaussianBlur(disp, (0, 0), 1.5)
    full = cv2.resize(disp, (W, H), interpolation=cv2.INTER_LINEAR)
    map_x, map_y = np.meshgrid(np.arange(W, dtype=np.float32), np.arange(H, dtype=np.float32))
    map_y = map_y + full
    return cv2.remap(norm, map_x, map_y, cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT, borderValue=255)


# --- kimaradt (pl. ábra melletti, kis betűs) sorok utólagos felismerése ---------------

def recover_missed_lines(norm: np.ndarray, lines: list[Line], lang: str) -> list[Line]:
    H, W = norm.shape
    words = [w for ln in lines for w in ln.words]
    body_h = float(np.median([w.h for w in words])) if words else H / 60
    _, bw = cv2.threshold(norm, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    for w in words:
        p = int(0.3 * w.h) + 2
        bw[max(0, int(w.y0) - p):int(w.y1) + p, max(0, int(w.x0) - p):int(w.x1) + p] = 0
    bw = cv2.morphologyEx(bw, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    kw = max(9, int(body_h * 0.9))
    smear = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (kw, 1)))
    n, _, stats, _ = cv2.connectedComponentsWithStats(smear, 8)
    mx, my = int(0.03 * W), int(0.02 * H)
    out: list[Line] = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if not (0.35 * body_h <= h <= 2.6 * body_h and w >= 1.2 * body_h and w >= 2.0 * h):
            continue
        if x <= mx or y <= my or x + w >= W - mx or y + h >= H - my:
            continue
        if area < 0.25 * w * h:
            continue
        pad = int(0.4 * h) + 4
        x0, y0 = max(0, x - pad), max(0, y - pad)
        crop = norm[y0:min(H, y + h + pad), x0:min(W, x + w + pad)]
        crop = cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        crop = cv2.copyMakeBorder(crop, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
        got = []
        for wd in (ww for ln in tsv_to_lines(run_tesseract(crop, lang, psm=7)) for ww in ln.words):
            alnum = sum(c.isalnum() for c in wd.text)
            if wd.conf < 55 or alnum == 0 or alnum < 0.5 * len(wd.text):
                continue
            got.append(Word(wd.text, x0 + (wd.x0 - 20) / 2, y0 + (wd.y0 - 20) / 2,
                            x0 + (wd.x1 - 20) / 2, y0 + (wd.y1 - 20) / 2, wd.conf))
        if got:
            out.append(Line(got))
    return out


# --- illusztrációk ------------------------------------------------------------------

def detect_figures(norm: np.ndarray, lines: list[Line], out_prefix: str | None) -> list[Figure]:
    """Nem szöveges, nagyobb festékfoltok (rajzok, díszek, ábrák) kivágása."""
    if out_prefix is None:
        return []
    H, W = norm.shape
    _, bw = cv2.threshold(norm, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    body_h = float(np.median([ln.word_h for ln in lines])) if lines else H / 60
    for ln in lines:
        for w in ln.words:
            p = int(0.35 * w.h) + 2
            bw[max(0, int(w.y0) - p):int(w.y1) + p, max(0, int(w.x0) - p):int(w.x1) + p] = 0
    bw = cv2.morphologyEx(bw, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    k = max(5, int(body_h * 1.2))
    blob = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(blob, 8)
    mx, my = int(0.03 * W), int(0.025 * H)
    figs = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if w < 3 * body_h or h < 3 * body_h:
            continue
        if x <= mx or y <= my or x + w >= W - mx or y + h >= H - my:
            continue   # lapszél: ujj, árnyék, szomszéd oldal
        # ábrán belül nem lehet felismert szöveg (különben pl. a lap körüli asztal
        # sötét kerete az egész oldalt „ábrává” tenné)
        inside = sum(1 for ln in lines for wd in ln.words
                     if x <= (wd.x0 + wd.x1) / 2 <= x + w and y <= (wd.y0 + wd.y1) / 2 <= y + h)
        if inside >= 3:
            continue
        ink = int((bw[y:y + h, x:x + w] > 0).sum())
        if ink < 0.015 * w * h or ink < 40 * body_h:
            continue
        pad = int(body_h * 0.3)
        x0, y0 = max(0, x - pad), max(0, y - pad)
        x1, y1 = min(W, x + w + pad), min(H, y + h + pad)
        crop = norm[y0:y1, x0:x1].astype(np.float32)
        # papírszín → tiszta fehér, tinta → mély fekete
        crop = np.clip((crop - 40) * 255.0 / (215 - 40), 0, 255).astype(np.uint8)
        path = f"{out_prefix}-fig{len(figs)}.png"
        Path(path).write_bytes(cv2.imencode(".png", crop)[1].tobytes())
        figs.append(Figure(float(x0), float(y0), float(x1), float(y1), path))
    return figs


def ocr_page(pdf_path: str, index: int, lang: str = "hun", italics: bool = True,
             do_dewarp: bool = True, fig_prefix: str | None = None) -> PageOCR:
    doc = pymupdf.open(pdf_path)
    try:
        gray = render_page(doc, index)
    finally:
        doc.close()
    norm = normalize(gray)
    if do_dewarp:
        norm = dewarp(norm)
    rows = run_tesseract(norm, lang)
    raw_lines = tsv_to_lines(rows)
    raw_lines += recover_missed_lines(norm, raw_lines, lang)
    lines = clean_lines(raw_lines, norm.shape[1], norm.shape[0])
    if italics:
        detect_italics(norm, lines)
    figs = detect_figures(norm, lines, fig_prefix)
    return PageOCR(index, norm.shape[1], norm.shape[0], lines, figs)
