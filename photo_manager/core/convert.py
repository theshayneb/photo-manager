"""Convert images to another format (mostly HEIC/WEBP/AVIF → JPG), keeping metadata."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .crop import export_image
from .fileops import unique_path
from .media import kind

if TYPE_CHECKING:
    from .exiftool import ExifTool

# target name -> (Pillow format, extension, extensions that are already this format)
TARGETS = {
    "JPG": ("JPEG", ".jpg", {".jpg", ".jpeg", ".jpe"}),
    "PNG": ("PNG", ".png", {".png"}),
}


def needs_conversion(path: str, target: str = "JPG") -> bool:
    return kind(path) == "image" and Path(path).suffix.lower() not in TARGETS[target][2]


def convert_file(path: str, target: str = "JPG", quality: int = 92,
                 et: "ExifTool | None" = None, recycle_original: bool = False) -> str:
    """Convert one image. Returns the new file's path (same name, new extension;
    "_1" etc. is added if that name is taken). The original is kept unless
    recycle_original, in which case it goes to the Recycle Bin."""
    fmt, ext, _ = TARGETS[target]
    src = Path(path)
    dest = unique_path(src.with_suffix(ext))
    tmp = dest.with_name(f"{dest.stem}.converting{ext}")
    try:
        export_image(path, str(tmp), et, fmt=fmt, quality=quality)
        tmp.replace(dest)
    finally:
        if tmp.exists():
            tmp.unlink()
    if recycle_original:
        from send2trash import send2trash

        send2trash(path)
    return str(dest)
