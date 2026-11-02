@echo off
rem Run Photo Manager from source (needs Python 3.11+ from python.org).
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    py -3 -m venv .venv || python -m venv .venv
    .venv\Scripts\python -m pip install --upgrade pip
    .venv\Scripts\python -m pip install -r requirements.txt
)
if not exist vendor\exiftool\exiftool.exe (
    powershell -ExecutionPolicy Bypass -File scripts\get-exiftool.ps1
)
start "" .venv\Scripts\pythonw -m photo_manager
