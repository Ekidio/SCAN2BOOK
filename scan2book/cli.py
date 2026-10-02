"""Parancssori felület: python -m scan2book bemenet.pdf [-o kimenet.pdf]"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pymupdf

from .pipeline import Options, convert, parse_page_range


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="scan2book",
        description="Lefotózott könyvoldalakból álló PDF átalakítása könyvszerűen szedett, szöveges PDF-fé.",
    )
    ap.add_argument("input", help="bemeneti (fotózott/szkennelt) PDF")
    ap.add_argument("-o", "--output", help="kimeneti PDF (alapértelmezés: <bemenet>_konyv.pdf)")
    ap.add_argument("-l", "--lang", default="hun", help="OCR nyelv(ek), pl. hun vagy hun+eng (alap: hun)")
    ap.add_argument("-p", "--pages", default="", help="oldaltartomány, pl. 1-10,15")
    ap.add_argument("--font-size", type=float, default=11.0, help="kenyérszöveg betűmérete pt-ban (alap: 11)")
    ap.add_argument("--font", default="LibertinusSerif", choices=["LibertinusSerif", "EBGaramond"],
                    help="betűcsalád (alap: LibertinusSerif)")
    ap.add_argument("--no-dewarp", action="store_true", help="lapgörbület-kiegyenesítés kikapcsolása")
    ap.add_argument("--no-italics", action="store_true", help="dőlt betűk felismerésének kikapcsolása")
    ap.add_argument("--no-cache", action="store_true", help="OCR gyorsítótár mellőzése")
    a = ap.parse_args(argv)

    out = a.output or str(Path(a.input).with_name(Path(a.input).stem + "_konyv.pdf"))
    with pymupdf.open(a.input) as d:
        pages = parse_page_range(a.pages, d.page_count)
    opts = Options(lang=a.lang, italics=not a.no_italics, font_size=a.font_size, pages=pages,
                   use_cache=not a.no_cache, dewarp=not a.no_dewarp, font=a.font)

    # ablakos (konzol nélküli) Windows-appban nincs stdout/stderr
    err = sys.stderr

    def prog(f: float, msg: str):
        if err is None:
            return
        bar = "█" * int(f * 30)
        err.write(f"\r[{bar:<30}] {f * 100:5.1f}%  {msg[:60]:<60}")
        err.flush()

    convert(a.input, out, opts, prog)
    if err is not None:
        err.write("\n")
    if sys.stdout is not None:
        print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
