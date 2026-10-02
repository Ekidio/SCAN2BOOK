# SCAN2BOOK Windows build: PyInstaller (mappa) + hordozható ZIP + Inno Setup telepítő.
# Feltétel: Python 3.12, Tesseract (C:\Program Files\Tesseract-OCR), Inno Setup 6.
param([string]$Version = "0.1.0")
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller

# --- Tesseract becsomagolása (exe + DLL-ek; a nyelvi adatok a saját tessdata mappánkból jönnek)
$tess = @("$env:ProgramFiles\Tesseract-OCR", "${env:ProgramFiles(x86)}\Tesseract-OCR") |
    Where-Object { Test-Path "$_\tesseract.exe" } | Select-Object -First 1
if (-not $tess) { throw "Tesseract nem található" }
Remove-Item -Recurse -Force build -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force build\tesseract | Out-Null
Copy-Item "$tess\*.exe", "$tess\*.dll" build\tesseract\
& "$tess\tesseract.exe" --version

# --- forráskódos próba
python tests\make_sample.py build\sample.pdf
python app.py build\sample.pdf -o build\sample_src.pdf --no-cache
if ($LASTEXITCODE -ne 0) { throw "forráskódos futás sikertelen" }
python tests\check_output.py build\sample_src.pdf
if ($LASTEXITCODE -ne 0) { throw "forráskódos kimenet hibás" }

# --- PyInstaller (mappás változat: gyors indulás, a tesseract.exe a lemezen van)
python -m PyInstaller --noconfirm --clean --windowed --name SCAN2BOOK `
    --add-data "fonts;fonts" --add-data "tessdata;tessdata" --add-data "build\tesseract;tesseract" `
    --exclude-module matplotlib --exclude-module pytest `
    app.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller hiba" }
Copy-Item LICENSE, THIRD_PARTY_NOTICES.md dist\SCAN2BOOK\

# --- az elkészült exe próbája, ékezetes útvonallal is
$dir = "build\ékezetes mappa"
New-Item -ItemType Directory -Force $dir | Out-Null
Copy-Item build\sample.pdf "$dir\minta könyv.pdf"
$p = Start-Process -FilePath "dist\SCAN2BOOK\SCAN2BOOK.exe" -Wait -PassThru `
    -ArgumentList "`"$dir\minta könyv.pdf`"", "-o", "`"$dir\kész.pdf`"", "--no-cache"
if ($p.ExitCode -ne 0) { throw "az exe hibával lépett ki ($($p.ExitCode))" }
python tests\check_output.py "$dir\kész.pdf"
if ($LASTEXITCODE -ne 0) { throw "az exe kimenete hibás" }

# --- hordozható ZIP + telepítő
Compress-Archive -Force -Path dist\SCAN2BOOK -DestinationPath "dist\SCAN2BOOK-$Version-portable.zip"
$iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $iscc)) { $iscc = "$env:ProgramFiles\Inno Setup 6\ISCC.exe" }
& $iscc "/DAppVersion=$Version" packaging\installer.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup hiba" }
Get-ChildItem dist
