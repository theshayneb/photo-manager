# Photo Manager

A simple Windows 11 photo browser that does a few things well:

- **Browse** folders on any drive, with fast thumbnails (JPEG, PNG, GIF, WEBP, HEIC, AVIF, TIFF and videos).
- **Delete** to the Recycle Bin, **move** to a folder (with recent folders), **rename by date taken**.
- **Fix "date taken"** by typing a date, shifting by hours/days, or **reading it from the filename** with templates.
- **Keyword buttons**: one click adds or removes a keyword on every selected photo.
- **Labels**: a color (red, yellow, green, blue, purple) plus ★ Star and 🔖 Bookmark, each on its own hotkey.

Everything is written **into the files** with [ExifTool](https://exiftool.org) (XMP, plus IPTC for JPEG/TIFF), so
Windows Explorer, XnView, Lightroom and Bridge all see the same keywords, labels and dates.

## Install

1. Open the repository's **Releases** page (or **Actions → latest Build → Artifacts**) and download `PhotoManager-windows.zip`.
2. Unzip it anywhere, e.g. `C:\Apps\PhotoManager`.
3. Run `PhotoManager.exe`. ExifTool is included.

Windows SmartScreen may warn the first time because the app isn't signed: choose **More info → Run anyway**.

**Video thumbnails** come from Windows itself (the same ones Explorer shows). If a video has no thumbnail in
Explorer either, installing ffmpeg (`winget install Gyan.FFmpeg`) gives the app a second way to make one.

## Using it

| Do this | How |
|---|---|
| Open a folder | Click it in the **Folders** tree, or type/paste a path in the address bar |
| Quick preview (inside the window) | **Shift+P**. ← → to move, **C** to crop, **Shift+P** or **Esc** to close. The sidebar follows the photo you're looking at |
| View big | Double-click or **Enter**. In the viewer: ← → to move, **Delete** to recycle, **Enter** to play a video, **Esc** to close |
| Select | Click, Ctrl+click, Shift+click, **Ctrl+A** |
| Delete | **Delete** key (goes to the Recycle Bin) |
| Right-click menu | Preview, View, Open, Open with…, **Rename… (F2)**, Crop…, Color label, Copy (**Ctrl+C**, paste in Explorer), Copy path, Move to…, Show in Explorer, Properties, Delete |
| Move | **Ctrl+M**, then press **1–9** for a recent folder or **Browse…** |
| Labels | **Ctrl+1** red, **Ctrl+2** yellow, **Ctrl+3** green, **Ctrl+4** blue, **Ctrl+5** purple, **Ctrl+S** ★ Star, **Ctrl+B** 🔖 Bookmark, **Ctrl+0** None (removes all labels). Pressing a label again removes it. Change any of these with the **⌨** button in the Labels panel (or View → Label hotkeys…) |
| Move by dragging | Drag photos onto a folder in the **Folders** tree or **Favorites**. Hold **Ctrl** to copy instead. Hover over a folder to open it while dragging |
| Show in Explorer / open in default app | **Ctrl+E** / **Ctrl+O** |
| Refresh | **F5** |
| Favorite folder | **Ctrl+D** or the ☆ button adds/removes the current folder; or right-click a folder in the tree |
| Show/hide the sidebar | **F9** |

### View menu

- **File type badges**: a colored label on each thumbnail (JPG blue, PNG green, HEIC orange, WEBP purple,
  AVIF pink, GIF teal, videos red).
- **Highlight names not in rename format**: files whose names don't match the current Rename pattern show in
  amber with ⚠, and the status bar counts them. **Select files that need renaming** (**Ctrl+Shift+R**) selects
  them all, ready for the Rename panel.

- **Sidebar panels**: hide panels you don't use. Click a panel's title in the sidebar to collapse it.
- **Show under thumbnails**: Date taken (on by default), dimensions, file size, keywords.
- **Group by**: day, week or month taken, or color label (also in the toolbar). Weeks can start on Sunday or Monday,
  and show their week number (Sunday weeks: week 1 contains Jan 1; Monday weeks: ISO week numbers).
  **Click a group's header to collapse or expand it**; Ctrl+click selects everything in it. Right-click a header
  for Collapse all / Expand all. Ctrl+A and arrow keys skip collapsed groups.
- **Theme**: Dark (default), Light, or follow Windows.

### Keywords

- Click a button to add that keyword to all selected photos. Click it again to remove it.
  - **Filled** button: every selected photo has it. **Dashed**: some do.
- Type in **"Click here to add keywords"** and press Enter to add new ones (comma-separated). They also become buttons.
- Switch between keyword **sets** with the dropdown; **⋯** creates, edits or deletes sets.
  **Edit this set…** renames the set and lets you rename, reorder (drag), add and remove its keywords.
- Right-click a button to remove it from the set (photos keep their keywords).
- Keywords on the selection that aren't in the current set show below as chips; click one to remove it from the files.

### Date taken

- Type a date the way you'd write it and press **Enter**: `6/14/24 6:32p`, `06-14-2024 06-32-05 PM`, `2024-06-14 18:32` all work. The line under the box shows how it was read.
- **Also set Windows Created/Modified dates** makes Explorer's dates match.

### Crop

In the preview (**Shift+P**) press **C** (or click **Crop**). Drag to draw a box, drag its edges or corners to adjust,
or drag inside it to move it. Pick an **aspect ratio** (Free, Original, 1:1, 4:3, 3:2, 16:9 and portrait versions).
**Enter** saves, **Esc** cancels.

- By default the cropped photo **replaces the original, and the original goes to the Recycle Bin**, so you can
  always get it back. Tick **Save as a copy** to keep the original and save `name_crop.jpg` next to it.
- Dates, keywords, labels and the rest of the metadata are kept. Rotated phone photos are saved upright.

### Date from filename

Pick a template (or **Auto**, which tries them all top to bottom). The preview shows the new date for each selected file before anything is written; files that don't match are skipped.

Built-in templates:

| Template | Example | Notes |
|---|---|---|
| `PXL_{YYYY}{MM}{DD}_{HH}{mm}{ss}{fff}` | `PXL_20261031_140229473.jpg` | **UTC.** Google Pixel names files in UTC; this converts to your local time (10:02:29 AM in New York) |
| `IMG_{YYYY}{MM}{DD}_{HH}{mm}{ss}` | `IMG_20261023_000100_358_3.jpg` | |
| `VID_{YYYY}{MM}{DD}_{HH}{mm}{ss}` | `VID_20261023_120000.mp4` | |
| `Screenshot_{YYYY}{MM}{DD}-{HH}{mm}{ss}` | `Screenshot_20261023-143414.png` | |
| `{MM}-{DD}-{YYYY} {hh}-{mm}-{ss} {AMPM}` | `08-15-2026 11-42-44 AM.jpg` | Files renamed by this app |
| `{YYYY}-{MM}-{DD}_{HH}-{mm}-{ss}` | `2026-10-23_14-34-14.jpg` | |
| `{YYYY}{MM}{DD}{HH}{mm}{ss}` | `20261024084049_1.jpg` | Digits only |
| `*{YYYY}{MM}{DD}?{HH}{mm}{ss}` | `anything 20261023-143414.jpg` | Catch-all |

**Edit…** opens the template editor, with a box to test a filename. Placeholders: `{YYYY}` `{YY}` `{MM}` `{DD}` `{HH}` (00–23)
`{hh}` (01–12) with `{AMPM}`, `{mm}` `{ss}` `{fff}` (milliseconds, ignored), and `*` any text, `?` one character, `#` one digit.
`{MM}` is month and `{mm}` is minute.

### Convert (HEIC / WEBP / AVIF → JPG)

Select images and use **Convert…** in the toolbar or right-click → **Convert to JPG…**. Choose JPG (with quality)
or PNG, and whether to keep the originals or send them to the Recycle Bin. Each new file goes next to its original
with the same name (e.g. `phone.heic` → `phone.jpg`; `_1` is added if that name is taken). Dates, keywords, labels
and the rest of the metadata are copied; transparent areas become white in JPGs.

### Rename

The Rename panel lists every selected file with its new name before you click **Rename**.

Choose which date to use: **Date taken** (EXIF DateTimeOriginal), **EXIF Create Date**, or the Windows
Created/Modified date. The pattern uses the same placeholders plus `{name}` (the current name), e.g.
`{YYYY}-{MM}-{DD}_{HH}-{mm}-{ss}` → `2026-10-23_14-34-14.jpg`.
The default is `{MM}-{DD}-{YYYY} {hh}-{mm}-{ss} {AMPM}` → `08-15-2026 11-42-44 AM.jpg`. Pick another saved pattern
from the list or type your own (patterns you use are added to the list). Also built in:
`{YYYY}-{MM}-{DD}_{HH}-{mm}-{ss}`, `{YYYY}{MM}{DD}{HH}{mm}{ss}` (e.g. `20261024084049`) and `{YYYY}-{MM}-{DD} {name}`. Name clashes get `_1`, `_2`… (so two photos from the same second
become `08-15-2026 11-42-44 AM.jpg` and `08-15-2026 11-42-44 AM_1.jpg`); nothing is ever overwritten.

To rename a single file by hand, right-click it → **Rename…** or press **F2**.

### Labels

The **Labels** panel has the five colors (one per photo), two on/off labels that work alongside the color,
**★ Star** and **🔖 Bookmark**, and **None**, which removes all of them. They show on the thumbnails. Star is saved as a 5-star rating, so Windows
Explorer and Lightroom see it too; Bookmark is only shown in this app.

## What can be written where

| Files | Date taken | Keywords & labels |
|---|---|---|
| JPEG, TIFF | EXIF | XMP + IPTC |
| PNG, WEBP, HEIC, AVIF | EXIF | XMP |
| GIF | XMP | XMP |
| MP4, MOV, M4V, 3GP | QuickTime (stored as UTC, shown in local time) | XMP |
| AVI, MKV, WMV, WEBM, BMP… | read-only (shown, not editable) | — |

Editing keywords or labels keeps the file's Modified date unchanged.

## If something goes wrong

Unexpected errors pop up a message and are written to `%LOCALAPPDATA%\PhotoManager\errors.log`.
Sending me that file is the quickest way to get a bug fixed.

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
