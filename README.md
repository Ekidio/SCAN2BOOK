# SCAN2BOOK – From bad scans to beautiful books

**Letöltés (Windows, macOS): <https://ekidio.github.io/SCAN2BOOK/>**

Lefotózott / szkennelt könyvoldalakból álló PDF-ből valódi, kereshető szövegű,
könyvszerűen szedett PDF-et készít, az eredeti tördelés megtartásával:

- **sortörések és elválasztások** pontosan az eredeti szerint, sorkizárt szedéssel;
- **bekezdés-behúzások, középre zárt címek, nagyobb fejezetcímek, dőlt szavak**;
- **függőleges térközök** (fejezetkezdés, alcímek) egységes sorrácsra igazítva;
- **oldaltörések**: minden eredeti oldalból egy oldal lesz (az üres oldalak is megmaradnak);
- **oldalszámok** egységes helyen, a félreolvasott számok a sorozatból javítva;
- **illusztrációk** (rajzok, díszek) kivágva, tisztítva, az eredeti helyükön;
- **lapgörbület- és ferdeség-kiegyenesítés** az OCR előtt.

## Indítás

Grafikus felület (macOS-en dupla kattintás is működik a `SCAN2BOOK.command` fájlon):

```bash
.venv/bin/python app.py
```

Parancssor:

```bash
.venv/bin/python app.py bemenet.pdf -o kimenet.pdf
```

Opciók: `-p 1-10,15` (oldaltartomány), `-l hun+eng` (OCR nyelv),
`--font EBGaramond` (betűtípus), `--font-size 11`, `--no-dewarp`, `--no-italics`, `--no-cache`.

## Telepítés másik gépen

```bash
brew install tesseract
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

A magyar OCR-modell (`tessdata/hun.traineddata`, tessdata_best) és a betűtípusok
(`fonts/`, SIL Open Font License) a projektben vannak.

## Felépítés

| modul | feladat |
|---|---|
| `scan2book/ocr.py` | oldalkép, háttér-kiegyenlítés, kiegyenesítés, Tesseract OCR, dőlt betű- és ábrafelismerés |
| `scan2book/layout.py` | szövegtükör, sorrács, igazítás, behúzás, címméretek, oldalszám |
| `scan2book/textfix.py` | gondolatjelek, könyvszintű ékezetjavítás, oldalszám-sorozat |
| `scan2book/typeset.py` | oldalméret és szedés (PyMuPDF), sorkizárás |
| `scan2book/pipeline.py` | párhuzamos feldolgozás, OCR-gyorsítótár (`~/.cache/scan2book`) |
| `scan2book/gui.py`, `cli.py` | felületek |

## Windows-app

A GitHub Actions minden `main`-re küldött módosítás után Windows-gépen elkészíti:
- `SCAN2BOOK-<verzió>-setup.exe` – telepítő (Start menü, asztali ikon),
- `SCAN2BOOK-<verzió>-portable.zip` – telepítés nélkül futtatható mappa.

A Tesseract benne van a csomagban, a felhasználónak semmit nem kell külön telepítenie.
Letöltés: a tároló **Actions** fülén a legutóbbi futás → *Artifacts*. Verziócímkénél
(`git tag v1.0.0 && git push --tags`) a fájlok a **Releases** oldalra is felkerülnek.

Kézi build Windowson: `powershell -File packaging\build_windows.ps1`



## macOS-app

```bash
./packaging/build_macos.sh 0.1.4
```

Eredmény: `dist/SCAN2BOOK.app` és `dist/SCAN2BOOK-<verzió>-macOS.dmg`. A Tesseract és a
függőségei az app belsejébe kerülnek, így Homebrew nélküli Macen is fut. A build
Homebrew-mentes környezetben, ékezetes útvonalon le is teszteli az appot.

- Csak Apple Silicon (M1–M4) gépekre készül (arm64).
- Az app nincs Apple-fejlesztői tanúsítvánnyal aláírva: első indításnál
  jobb klikk → **Megnyitás**, vagy Rendszerbeállítások → Adatvédelem és biztonság → **Megnyitás mégis**.

## Licenc

Copyright © 2026 Ekidio. A SCAN2BOOK szabad szoftver: [GNU AGPL-3.0](LICENSE). A felhasznált összetevők és
licenceik: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
