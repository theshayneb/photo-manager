# Downloads the latest Windows ExifTool into vendor\exiftool\exiftool.exe
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$dest = Join-Path $root "vendor\exiftool"
$version = (Invoke-WebRequest "https://exiftool.org/ver.txt" -UseBasicParsing).Content.Trim()
$zipName = "exiftool-$($version)_64.zip"
$tmp = Join-Path ([IO.Path]::GetTempPath()) ("exiftool-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $tmp | Out-Null
try {
    Write-Host "Downloading $zipName"
    Invoke-WebRequest "https://exiftool.org/$zipName" -OutFile (Join-Path $tmp $zipName) -UseBasicParsing
    Expand-Archive (Join-Path $tmp $zipName) -DestinationPath (Join-Path $tmp "x")
    $exe = Get-ChildItem (Join-Path $tmp "x") -Recurse -Filter "exiftool(-k).exe" | Select-Object -First 1
    if (-not $exe) { throw "exiftool(-k).exe not found in $zipName" }
    if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
    New-Item -ItemType Directory -Path $dest | Out-Null
    Copy-Item (Join-Path $exe.DirectoryName "*") $dest -Recurse
    Rename-Item (Join-Path $dest "exiftool(-k).exe") "exiftool.exe"
    & (Join-Path $dest "exiftool.exe") -ver
} finally {
    Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
}
