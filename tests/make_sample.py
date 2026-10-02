"""Teszt- és demóbemenet: „rosszul lefotózott” könyvoldalt utánzó PDF.

A szöveg saját (szabadon felhasználható) írás. A `--heavy` mód erősebb torzítást ad
(lapgörbület, ferdeség, gerincárnyék, sárgás papír, zaj) – ebből készülnek a
letöltőoldal előtte/utána képei.
"""
import argparse
from pathlib import Path

import cv2
import numpy as np
import pymupdf

ROOT = Path(__file__).resolve().parent.parent

# (behúzás?, utolsó sor a bekezdésben?, szöveg)
TEXT = [
    (True, False, "Az öreg könyvkötő műhelyében mindig papír- és enyvillat ter-"),
    (False, False, "jengett. Márton bácsi a hosszú asztal fölé hajolt, és óvatosan"),
    (False, False, "kisimította a megsárgult lapokat, mintha egy alvó madár szár-"),
    (False, True, "nyát simogatná."),
    (True, False, "– Ezt a könyvet a nagyapám hozta Kolozsvárról – mondta a lány,"),
    (False, True, "és letette a kopott kötetet az asztalra. – Félek, hogy szétesik."),
    (True, False, "– Semmi sem esik szét, ha türelemmel bánnak vele – felelte"),
    (False, True, "az öreg, és megigazította a szemüvegét."),
    (True, False, "Kinyitotta a könyvet. A betűk itt-ott elmosódtak, a margón"),
    (False, False, "valaki ceruzával jegyzeteket írt, egy helyen pedig egy préselt"),
    (False, False, "lóherelevél pihent, olyan vékonyra száradva, hogy átsütött rajta"),
    (False, True, "a lámpa fénye."),
    (True, True, "– Ugye meg tudja menteni? – kérdezte a lány halkan."),
    (True, False, "Márton bácsi elmosolyodott. Évtizedek óta hallotta ezt a kér-"),
    (False, True, "dést, és mindig ugyanazt válaszolta rá."),
    (True, True, "– Nem a papírt mentjük meg, kislányom. A történetet."),
    (True, False, "Az ablakon túl lassan esteledett. Az utcai lámpák egymás után"),
    (False, False, "gyúltak ki, a műhelyben pedig csak a ragasztóecset halk sur-"),
    (False, True, "rogása hallatszott, meg az óra ketyegése a falon."),
]


PAGE_W = 400


def _typeset(page: pymupdf.Page, font: pymupdf.Font, italic: pymupdf.Font, folio: int):
    fs, lead, left, indent = 11.0, 15.0, 40.0, 14.0
    sp = font.text_length(" ", fs)
    # a szedési szélesség: a leghosszabb sor természetes hossza (így minden sor kifér)
    width = max(font.text_length(t, fs) + (indent if ind else 0) - sp * 0.15 * (len(t.split()) - 1)
                for ind, _, t in TEXT)
    tw = pymupdf.TextWriter(page.rect)
    head = "Első fejezet"
    hw = italic.text_length(head, 17)
    tw.append((left + (width - hw) / 2, 78), head, font=italic, fontsize=17)
    y = 120.0
    for ind, last, line in TEXT:
        x0 = left + (indent if ind else 0)
        words = line.split()
        wl = [font.text_length(w, fs) for w in words]
        space = font.text_length(" ", fs)
        gap = space if last or len(words) < 2 else (left + width - x0 - sum(wl)) / (len(words) - 1)
        x = x0
        for w, l in zip(words, wl):
            tw.append((x, y), w, font=font, fontsize=fs)
            x += l + gap
        y += lead
    f = f"~ {folio} ~"
    tw.append((left + (width - font.text_length(f, fs)) / 2, 520), f, font=font, fontsize=fs)
    tw.write_text(page)


def _photo(gray: np.ndarray, heavy: bool, rng: np.random.Generator) -> np.ndarray:
    h, w = gray.shape
    img = gray.astype(np.float32)
    if heavy:
        # lapgörbület: a gerinc (bal oldal) felé erősödő függőleges hullámzás
        xs = np.arange(w, dtype=np.float32)
        ys = np.arange(h, dtype=np.float32)
        mx, my = np.meshgrid(xs, ys)
        bend = 14 * (1 - mx / w) ** 3 * np.sin(np.pi * my / h) + 6 * np.sin(mx / w * np.pi)
        img = cv2.remap(img, mx, my - bend.astype(np.float32), cv2.INTER_LINEAR, borderValue=255)
    m = cv2.getRotationMatrix2D((w / 2, h / 2), 2.2 if heavy else 0.8, 1.0)
    img = cv2.warpAffine(img, m, (w, h), borderValue=255)
    if heavy:
        img = cv2.GaussianBlur(img, (0, 0), 0.85)
    # gerincárnyék + egyenetlen megvilágítás
    shade = np.linspace(0.55 if heavy else 0.8, 1.0, w)[None, :] ** (0.6 if heavy else 1)
    vign = 1 - 0.18 * ((np.arange(h)[:, None] / h - 0.4) ** 2) if heavy else 1
    img = img * shade * vign * 0.95 + rng.normal(0, 7 if heavy else 6, img.shape)
    img = np.clip(img, 0, 255).astype(np.uint8)
    if not heavy:
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    # sárgás papír, kékes árnyék, asztal a lap körül
    col = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR).astype(np.float32)
    col *= np.array([0.80, 0.92, 1.0], np.float32)   # BGR: meleg tónus
    pad = 40
    table = np.full((h + 2 * pad, w + 2 * pad, 3), (70, 88, 104), np.float32)
    table += rng.normal(0, 6, table.shape)
    table[pad:pad + h, pad:pad + w] = col
    return np.clip(table, 0, 255).astype(np.uint8)


def make(out: str, pages: int = 2, heavy: bool = False, seed: int = 7):
    font = pymupdf.Font(fontfile=str(ROOT / "fonts" / "LibertinusSerif-Regular.otf"))
    italic = pymupdf.Font(fontfile=str(ROOT / "fonts" / "LibertinusSerif-Italic.otf"))
    rng = np.random.default_rng(seed)
    doc = pymupdf.open()
    for n in range(pages):
        src = pymupdf.open()
        pg = src.new_page(width=PAGE_W, height=560)
        _typeset(pg, font, italic, 11 + n)
        pix = pg.get_pixmap(dpi=150 if not heavy else 140, colorspace=pymupdf.csGRAY)
        gray = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width)
        img = _photo(gray, heavy, rng)
        ok, jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 70 if heavy else 80])
        hh, ww = img.shape[:2]
        page = doc.new_page(width=PAGE_W * ww / gray.shape[1], height=560 * hh / gray.shape[0])
        page.insert_image(page.rect, stream=jpg.tobytes())
    doc.save(out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?", default="sample.pdf")
    ap.add_argument("--heavy", action="store_true")
    ap.add_argument("--pages", type=int, default=2)
    a = ap.parse_args()
    make(a.out, a.pages, a.heavy)
