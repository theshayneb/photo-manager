# Builds dist\PhotoManager\PhotoManager.exe (with ExifTool bundled).
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
if (-not (Test-Path "vendor\exiftool\exiftool.exe")) { & "$PSScriptRoot\get-exiftool.ps1" }
python -m PyInstaller --noconfirm --clean --windowed --name PhotoManager `
    --collect-all pillow_heif `
    --add-data "vendor\exiftool;exiftool" `
    photo_manager\__main__.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
