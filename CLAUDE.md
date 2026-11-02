# Photo Manager — notes for agents

Windows 11 desktop app, Python 3.12 + PySide6, metadata via ExifTool (`-stay_open`).

- `photo_manager/core/` has no Qt imports and holds all logic: `templates.py` (filename → date),
  `dates.py` (typed dates, shifts, rename patterns), `metadata.py` (what to read, ExifTool write args),
  `exiftool.py` (process wrapper), `fileops.py`, `thumbs.py`, `settings.py`.
- `photo_manager/ui/` is the Qt layer. ExifTool and file operations run on `MainWindow.bg`
  (a single-thread pool) and report back on the UI thread via `ui/workers.py`.
- Tests: `python -m pytest`. GUI tests run offscreen against `tests/fake_exiftool.py`;
  `tests/test_real_exiftool.py` runs only where ExifTool is installed (always in CI on Windows).
- The user's own time zone is US Eastern; Pixel `PXL_` filenames are UTC.
- Keep it simple: the user explicitly wants a small, reliable tool, not a kitchen sink.
