"""A letöltőoldal előtte/utána képeinek előállítása (docs/img/)."""
import subprocess
import sys
import tempfile
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
import make_sample  # noqa: E402

out = ROOT / "docs" / "img"
out.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory() as td:
    scan, book = Path(td) / "scan.pdf", Path(td) / "book.pdf"
    make_sample.make(str(scan), pages=1, heavy=True)
    subprocess.run([sys.executable, str(ROOT / "app.py"), str(scan), "-o", str(book), "--no-cache"],
                   check=True, capture_output=True)
    s, b = pymupdf.open(scan)[0], pymupdf.open(book)[0]
    H = 1100
    s.get_pixmap(matrix=pymupdf.Matrix(H / s.rect.height, H / s.rect.height)).save(out / "before.jpg", jpg_quality=82)
    b.get_pixmap(matrix=pymupdf.Matrix(H / b.rect.height, H / b.rect.height)).save(out / "after.png")
    print(pymupdf.open(book)[0].get_text())
print("kész:", *sorted(p.name for p in out.iterdir()))
