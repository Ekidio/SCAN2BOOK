"""A kimeneti PDF ellenőrzése: van-e benne kereshető, helyes magyar szöveg."""
import sys

import pymupdf

doc = pymupdf.open(sys.argv[1])
text = " ".join(p.get_text() for p in doc)
need = ["Márton", "könyvkötő", "lóherelevél", "türelemmel"]
missing = [w for w in need if w not in text]
print(f"{doc.page_count} oldal, {len(text)} karakter")
if doc.page_count != 2 or missing:
    print("HIBA – hiányzó szavak:", missing)
    sys.exit(1)
print("OK")
