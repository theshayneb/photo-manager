# Changelog

## 0.10.1

- Steam import also reads Steam's own screenshot index (`760\screenshots.vdf`), so screenshots a game saved
  itself and added to Steam's library are found wherever the file lives.
- More image types (WEBP, AVIF, JXR/HDR, BMP, TIFF, HEIC).
- **Also look in** folders (remembered, subfolders included), e.g. the folder Steam opens with *Show on Disk*.
- The dialog lists every game found with its number of screenshots and newest date.
- A screenshot found in two places is imported once (the bigger, better-quality copy).

## 0.10.0

- **Tools → Import Steam screenshots…** copies every screenshot Steam keeps on this PC (uploaded or not) straight
  into a folder you choose (remembered). Finds Steam and your account automatically; shows how many are new;
  skips ones already imported; never changes Steam's copies. Optionally sets Date taken (and Windows Created)
  from the file name, and adds the game's name as a keyword.

## 0.9.3

- New filename template for names like `4981570_20261105132923_1` (a number, `_`, then YYYYMMDDHHMMSS):
  `*_{YYYY}{MM}{DD}{HH}{mm}{ss}`. Added to existing settings automatically, before the catch-all template.
- Templates added in new versions are now always placed before your catch-all template, so Auto tries them first.

## 0.9.2

- Fixed: closing the app while it was still reading file details could show a "something went wrong" message.
  Closing now finishes all pending work (including saves), then ignores late results.
- ExifTool's pipes are closed properly when the app closes.

## 0.9.1

- Video thumbnails show how long the video is in a small chip at the bottom-right (opposite the ▶).

## 0.9.0

- **Filter** (toolbar, after Sort and Group): tick File types, Labels (colors, ⭐ Starred, 🔖 Bookmarked, No label),
  Needs rename and/or No keywords. Ticks under one heading mean "any of these"; different headings must all match.
  The status bar shows "N of M shown"; **Clear filter** shows everything again.
- **Group: Label** (was Color label) now includes ⭐ and 🔖: one group per combination, e.g. "Red ⭐", "🔖", "No label".
- **Group: File type** (JPG, PNG, HEIC, MP4…).
- ⭐ is now the star emoji, and the bookmark on photos is the red 🔖 emoji, matching the Labels buttons.

## 0.8.3

- Fixed: **Move to…** in the big preview could do nothing. Actions used the (hidden) grid selection; in the
  preview, Move to…, Delete, Rename, Convert and Copy now always act on the photo being shown (the active one
  when comparing).
- After a move/delete in the preview it goes on to the next photo; after a rename it keeps showing the photo.
- Moving a file that's briefly in use (e.g. a video that just stopped) is retried for a few seconds, and a move
  never leaves a copy in both places. Clearer "in use by another program" message if it still can't move.

## 0.8.2

- Videos in the big preview show their thumbnail until you press play (instead of a black box), and the file-type
  badge, ★/🔖 and color-label frame are drawn on top of the video too.
- The video picture is now drawn by the app itself, frame by frame.
- Closing the app deletes its window while Qt is still running (more orderly shutdown).

## 0.8.1

- Fixed: closing the app while thumbnails were still loading could crash it on exit. It now cancels and waits for
  thumbnail work (and stops any playing video) before closing.

## 0.8.0

- **Compare side by side**: select 2–4 photos and press Shift+P (or right-click → Compare). 2 or 3 sit side by
  side, 4 make a 2×2 grid. Click a photo (or use ← →) to make it the active one; the sidebar and label hotkeys
  act on it. Delete removes the active photo. Closing gives the compared photos back as the selection.
- **Videos play in the big preview**: play/pause (Space), seek bar, time, sound on/off (M) and an Auto-play
  option that's remembered. Every video starts muted. The video is released before it's moved, renamed,
  deleted or has its labels changed, so Windows never says the file is in use.

## 0.7.5

- The Shift+P preview shows the file-type badge, ★/🔖 and the color-label frame, like the grid.
  They update immediately when you press a label hotkey while previewing (hidden while cropping).

## 0.7.4

- Fixed: dragging photos did a box-selection instead of a drag, so they couldn't be dropped on a folder or
  favorite. (Qt switches dragging off for grids whose items can't be rearranged; it's now switched back on.)
- Fixed: a possible crash when closing the app after video thumbnails were shown.

## 0.7.3

- **None** moved to the end of the Labels row and now removes everything: the color, ★ and 🔖 (also Ctrl+0).

## 0.7.2

- Labels panel fits on one row: colors, a smaller None, ★, 🔖 and a ⌨ hotkeys button.

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
