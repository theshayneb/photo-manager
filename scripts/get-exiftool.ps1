# Downloads the latest Windows ExifTool into vendor\exiftool\exiftool.exe
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$dest = Join-Path $root "vendor\exiftool"
$version = (Invoke-WebRequest "https://exiftool.org/ver.txt" -UseBasicParsing).Content.Trim()
$zipName = "exiftool-$($version)_64.zip"

# Prefer the exact Windows zip linked from the home page; fall back to known locations.
$candidates = @()
try {
    $home_page = (Invoke-WebRequest "https://exiftool.org/" -UseBasicParsing).Content
    foreach ($m in [regex]::Matches($home_page, 'href="([^"]*exiftool-[\d.]+_64\.zip)"')) {
        $href = $m.Groups[1].Value
        if ($href -notmatch '^https?://') { $href = "https://exiftool.org/" + $href.TrimStart("/") }
        $candidates += $href
    }
} catch { Write-Host "Couldn't read the ExifTool home page: $_" }
$candidates += "https://exiftool.org/$zipName"
$candidates += "https://sourceforge.net/projects/exiftool/files/$zipName/download"
$tmp = Join-Path ([IO.Path]::GetTempPath()) ("exiftool-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $tmp | Out-Null
try {
    $ok = $false
    foreach ($url in ($candidates | Select-Object -Unique)) {
        try {
            Write-Host "Downloading $url"
            Invoke-WebRequest $url -OutFile (Join-Path $tmp $zipName) -UseBasicParsing -UserAgent "curl/8"
            $ok = $true
            break
        } catch { Write-Host "  failed: $($_.Exception.Message)" }
    }
    if (-not $ok) { throw "Couldn't download ExifTool. Get the Windows zip from https://exiftool.org and put exiftool.exe in vendor\exiftool." }
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
