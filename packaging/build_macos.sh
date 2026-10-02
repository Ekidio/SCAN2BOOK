#!/bin/zsh
# SCAN2BOOK macOS build: önálló .app (Tesseract + függőségei a csomagban) + DMG.
# Feltétel: Homebrew Tesseract (brew install tesseract), projekt .venv.
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION="${1:-0.1.0}"
PY=.venv/bin/python

$PY -m pip install -q -r requirements.txt pyinstaller

TESS="$(readlink -f "$(command -v tesseract || echo /opt/homebrew/bin/tesseract)")"
[[ -x "$TESS" ]] || { echo "Tesseract nem található (brew install tesseract)"; exit 1; }

rm -rf build dist/SCAN2BOOK.app dist/SCAN2BOOK
# a tesseract binárist PyInstaller veszi fel: a dylib-függőségeit (libtesseract,
# leptonica, libarchive, képformátum-könyvtárak) begyűjti és átírja az útvonalaikat
$PY -m PyInstaller --noconfirm --clean --windowed --name SCAN2BOOK \
    --osx-bundle-identifier com.ekidio.scan2book \
    --add-data "fonts:fonts" --add-data "tessdata:tessdata" \
    --add-data "LICENSE:." --add-data "THIRD_PARTY_NOTICES.md:." \
    --add-binary "${TESS}:tesseract" \
    --exclude-module matplotlib --exclude-module pytest \
    app.py

APP=dist/SCAN2BOOK.app
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $VERSION" "$APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Add :NSHumanReadableCopyright string 'SCAN2BOOK – From bad scans to beautiful books'" \
    "$APP/Contents/Info.plist" 2>/dev/null || true
# az Info.plist módosítása érvényteleníti az aláírást: újra-aláírás (ad-hoc) + ellenőrzés
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict "$APP"

# --- ellenőrzés: a becsomagolt tesseract nem hivatkozhat Homebrew-ra
BT=$(find "$APP" -type f -name tesseract -perm -u+x | head -1)
if otool -L "$BT" | grep -q /opt/homebrew; then
    echo "HIBA: a becsomagolt tesseract még Homebrew-könyvtárakra hivatkozik"; otool -L "$BT"; exit 1
fi

# --- füstteszt az elkészült appal, Homebrew nélküli PATH-szal, ékezetes útvonalon
T="build/ékezetes mappa"; mkdir -p "$T"
$PY tests/make_sample.py "$T/minta könyv.pdf"
env -i HOME="$HOME" PATH=/usr/bin:/bin "$APP/Contents/MacOS/SCAN2BOOK" "$T/minta könyv.pdf" -o "$T/kész.pdf" --no-cache
$PY tests/check_output.py "$T/kész.pdf"

# --- DMG
rm -f "dist/SCAN2BOOK-$VERSION-macOS.dmg"
STAGE=build/dmg; rm -rf "$STAGE"; mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"; ln -s /Applications "$STAGE/Applications"
cp LICENSE "$STAGE/LICENSE.txt"; cp THIRD_PARTY_NOTICES.md "$STAGE/"
hdiutil create -quiet -volname SCAN2BOOK -srcfolder "$STAGE" -ov -format UDZO "dist/SCAN2BOOK-$VERSION-macOS.dmg"
rm -rf dist/SCAN2BOOK    # a PyInstaller köztes mappája, az .app már mindent tartalmaz
ls -lh dist
