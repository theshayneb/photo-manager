# Changelog

## 0.7.1

- Star and Bookmark buttons in the Labels panel show just their icons (★ 🔖); hover for the name and hotkey.

## 0.7.0

- Drag photos from the grid onto a folder in the Folders tree or Favorites to move them (Ctrl to copy).
  Hovering a folder while dragging expands it.
- "Color label" panel is now **Labels**, with ★ Star and 🔖 Bookmark (on/off, alongside the color), shown on
  thumbnails. Star is saved as a 5-star rating; Bookmark as the XMP "good" flag.
- Hotkeys for every label can be changed (Labels → Hotkeys…). Defaults: Ctrl+1–5 colors, Ctrl+0 none,
  Ctrl+S Star, Ctrl+B Bookmark.

## 0.6.0

- Rename panel shows a File → New name list (with the exact final names, including `_1` for duplicates).
- Files not named in the current rename format are highlighted in amber with ⚠; the status bar counts them and
  View → Select files that need renaming (Ctrl+Shift+R) selects them.
- File type badges on thumbnails (JPG, PNG, HEIC, WEBP, AVIF, GIF, videos…).
- Convert images to JPG (or PNG), keeping metadata; originals kept or sent to the Recycle Bin.
- App icon.

## 0.5.0

- Keyword buttons are equal-size boxes in a 3-column grid again (slightly shorter than before).
- Renames default to `08-15-2026 11-42-44 AM` (`{MM}-{DD}-{YYYY} {hh}-{mm}-{ss} {AMPM}`); existing settings switch over once.
- New filename template so dates can be read back from names in that format.

## 0.4.0

- Fixed: the **Edit…** button for filename templates did nothing (the dialog crashed while opening).
- Unexpected errors now show a message and are logged to `%LOCALAPPDATA%\PhotoManager\errors.log`.
- Right-click menu on photos: Preview, View, Open, Open with…, Rename… (F2), Crop…, Color label, Copy (Ctrl+C),
  Copy path, Move to…, Show in Explorer, Properties, Delete.
- Group headers collapse/expand on click (Ctrl+click selects the group; right-click for Collapse/Expand all).
- New filename template and rename preset for digits-only names like `20261024084049_1`.
- Rename patterns are a dropdown of saved presets; patterns you use are remembered.

## 0.3.0

- **Shift+P** preview inside the window (← → to move, Esc/Shift+P to close); the sidebar follows the photo.
- **Crop** (C in the preview) with aspect ratios; replaces the original (original to Recycle Bin) or saves a copy.
  Metadata is kept and rotated photos are saved upright.
- Keyword sets can be edited: rename the set, rename/reorder/add/remove keywords.
- Keyword buttons are compact chips that wrap; the sidebar is tighter overall.
- Smooth scrolling in the thumbnail grid (it used to jump a whole row per wheel step).
- The folder tree no longer expands itself to follow the open folder.
- Week groups show the week number.
- Removed the date Shift option.

## 0.2.0

- Sidebar panels collapse (click the title) and can be hidden (View → Sidebar panels); F9 hides the whole sidebar.
- Video thumbnails using Windows' own thumbnails (no ffmpeg needed).
- Rename can use Date taken, EXIF Create Date, or Windows Created/Modified, and `{name}`.
- Date taken (and optionally dimensions, file size, keywords) shown under each thumbnail.
- Group the grid by day, week (Sunday or Monday start), month, or color label.
- Favorite folders above the folder tree (Ctrl+D), also offered in Move to….
- Dark theme (deep grey), switchable under View → Theme.

## 0.1.0

- First release: browse, delete, move, rename by date, date taken editing and filename templates,
  keyword buttons, color labels.
