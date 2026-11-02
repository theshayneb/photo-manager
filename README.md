# Photo Manager

A simple Windows 11 photo browser that does a few things well:

- **Browse** folders on any drive, with fast thumbnails (JPEG, PNG, GIF, WEBP, HEIC, AVIF, TIFF and videos).
- **Delete** to the Recycle Bin, **move** to a folder (with recent folders), **rename by date taken**.
- **Fix "date taken"** by typing a date, shifting by hours/days, or **reading it from the filename** with templates.
- **Keyword buttons**: one click adds or removes a keyword on every selected photo.
- **Color labels** (red, yellow, green, blue, purple) as quick temporary tags.

Everything is written **into the files** with [ExifTool](https://exiftool.org) (XMP, plus IPTC for JPEG/TIFF), so
Windows Explorer, XnView, Lightroom and Bridge all see the same keywords, labels and dates.

## Install

1. Open the repository's **Releases** page (or **Actions → latest Build → Artifacts**) and download `PhotoManager-windows.zip`.
2. Unzip it anywhere, e.g. `C:\Apps\PhotoManager`.
3. Run `PhotoManager.exe`. ExifTool is included.

Windows SmartScreen may warn the first time because the app isn't signed: choose **More info → Run anyway**.

**Video thumbnails** need ffmpeg. Without it videos show a "video" placeholder (everything else still works).
To add it, run: `winget install Gyan.FFmpeg`, then restart the app.

## Using it

| Do this | How |
|---|---|
| Open a folder | Click it in the **Folders** tree, or type/paste a path in the address bar |
| View big | Double-click or **Enter**. In the viewer: ← → to move, **Delete** to recycle, **Enter** to play a video, **Esc** to close |
| Select | Click, Ctrl+click, Shift+click, **Ctrl+A** |
| Delete | **Delete** key (goes to the Recycle Bin) |
| Move | **Ctrl+M**, then press **1–9** for a recent folder or **Browse…** |
| Color label | **Ctrl+1** red, **Ctrl+2** yellow, **Ctrl+3** green, **Ctrl+4** blue, **Ctrl+5** purple, **Ctrl+0** none. Pressing the same label again removes it |
| Show in Explorer / open in default app | **Ctrl+E** / **Ctrl+O** |
| Refresh | **F5** |

### Keywords

- Click a button to add that keyword to all selected photos. Click it again to remove it.
  - **Filled** button: every selected photo has it. **Dashed**: some do.
- Type in **"Click here to add keywords"** and press Enter to add new ones (comma-separated). They also become buttons.
- Switch between keyword **sets** with the dropdown; **⋯** creates, renames or deletes sets.
- Right-click a button to remove it from the set (photos keep their keywords).
- Keywords on the selection that aren't in the current set show below as chips; click one to remove it from the files.

### Date taken

- Type a date the way you'd write it and press **Enter**: `6/14/24 6:32p`, `06-14-2024 06-32-05 PM`, `2024-06-14 18:32` all work. The line under the box shows how it was read.
- **Shift** moves dates by an amount: `+1h`, `-30m`, `-2d 3h` (useful for a camera on the wrong time zone).
- **Also set Windows Created/Modified dates** makes Explorer's dates match.

### Date from filename

Pick a template (or **Auto**, which tries them all top to bottom). The preview shows the new date for each selected file before anything is written; files that don't match are skipped.

Built-in templates:

| Template | Example | Notes |
|---|---|---|
| `PXL_{YYYY}{MM}{DD}_{HH}{mm}{ss}{fff}` | `PXL_20261031_140229473.jpg` | **UTC.** Google Pixel names files in UTC; this converts to your local time (10:02:29 AM in New York) |
| `IMG_{YYYY}{MM}{DD}_{HH}{mm}{ss}` | `IMG_20261023_000100_358_3.jpg` | |
| `VID_{YYYY}{MM}{DD}_{HH}{mm}{ss}` | `VID_20261023_120000.mp4` | |
| `Screenshot_{YYYY}{MM}{DD}-{HH}{mm}{ss}` | `Screenshot_20261023-143414.png` | |
| `{YYYY}-{MM}-{DD}_{HH}-{mm}-{ss}` | `2026-10-23_14-34-14.jpg` | Files already renamed by this app |
| `*{YYYY}{MM}{DD}?{HH}{mm}{ss}` | `anything 20261023-143414.jpg` | Catch-all |

**Edit…** opens the template editor, with a box to test a filename. Placeholders: `{YYYY}` `{YY}` `{MM}` `{DD}` `{HH}` (00–23)
`{hh}` (01–12) with `{AMPM}`, `{mm}` `{ss}` `{fff}` (milliseconds, ignored), and `*` any text, `?` one character, `#` one digit.
`{MM}` is month and `{mm}` is minute.

### Rename by date taken

Uses the same placeholders, e.g. `{YYYY}-{MM}-{DD}_{HH}-{mm}-{ss}` → `2026-10-23_14-34-14.jpg`.
Name clashes get `_1`, `_2`…; nothing is ever overwritten.

## What can be written where

| Files | Date taken | Keywords & labels |
|---|---|---|
| JPEG, TIFF | EXIF | XMP + IPTC |
| PNG, WEBP, HEIC, AVIF | EXIF | XMP |
| GIF | XMP | XMP |
| MP4, MOV, M4V, 3GP | QuickTime (stored as UTC, shown in local time) | XMP |
| AVI, MKV, WMV, WEBM, BMP… | read-only (shown, not editable) | — |

Editing keywords or labels keeps the file's Modified date unchanged.

## Settings

Saved in `%APPDATA%\PhotoManager\settings.json` (keyword sets, templates, recent folders, window layout).
Thumbnails are cached in `%LOCALAPPDATA%\PhotoManager\thumbs` and can be deleted at any time.

## Development

```bat
run.bat
```

creates a `.venv`, installs dependencies, downloads ExifTool into `vendor\exiftool` and starts the app.

```bat
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest
powershell -File scripts\build.ps1
```

Every push to `main` builds the Windows exe in GitHub Actions (tests run there against the real ExifTool).
To publish a release, bump `__version__` in `photo_manager/__init__.py` (and `pyproject.toml`) and push to `main`:
the build creates the matching tag and release with the zip if that version has none yet.
