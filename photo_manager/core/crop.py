"""Crop a photo and keep its metadata.

The crop box is in *upright* pixel coordinates (after EXIF orientation is
applied, i.e. as the photo is shown). The result is saved upright with
Orientation reset to 1. All other metadata (dates, keywords, labels, GPS...)
is copied from the original with ExifTool when available.

Replacing the original sends the original to the Recycle Bin first, so a crop
can always be undone from there.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image, ImageOps

from . import thumbs  # noqa: F401  (registers HEIC support)
from .fileops import unique_path

if TYPE_CHECKING:
    from .exiftool import ExifTool

CROPPABLE_EXTS = {".jpg", ".jpeg", ".jpe", ".png", ".webp", ".heic", ".heif", ".avif", ".tif", ".tiff", ".bmp", ".gif"}

ASPECT_RATIOS = {
    "Free": None,
    "Original": "original",
    "1:1": 1.0,
    "4:3": 4 / 3,
    "3:2": 3 / 2,
    "16:9": 16 / 9,
    "3:4": 3 / 4,
    "2:3": 2 / 3,
    "9:16": 9 / 16,
}


class CropError(RuntimeError):
    pass


def can_crop(path: str) -> bool:
    return Path(path).suffix.lower() in CROPPABLE_EXTS


def upright_size(path: str) -> tuple[int, int]:
    """Image size as displayed (width/height swapped for rotated photos)."""
    with Image.open(path) as im:
        w, h = im.size
        orientation = im.getexif().get(0x0112, 1)
    return (h, w) if orientation in (5, 6, 7, 8) else (w, h)


def _save_params(fmt: str, src: Image.Image) -> dict:
    params: dict = {}
    icc = src.info.get("icc_profile")
    if icc:
        params["icc_profile"] = icc
    exif = src.getexif()
    if exif:
        exif[0x0112] = 1
        params["exif"] = exif.tobytes()
    if fmt == "JPEG":
        params.update(quality=95, optimize=True)
    elif fmt in ("WEBP", "HEIF", "AVIF"):
        params["quality"] = 92
    return params


def crop_to_file(path: str, box: tuple[int, int, int, int], out_path: str,
                 et: "ExifTool | None" = None) -> None:
    """Write the cropped image to out_path (same format as path)."""
    left, top, right, bottom = box
    with Image.open(path) as src:
        fmt = src.format or ""
        upright = ImageOps.exif_transpose(src)  # before _save_params resets Orientation
        params = _save_params(fmt, src)
    width, height = upright.size
    left, top = max(0, int(left)), max(0, int(top))
    right, bottom = min(width, int(right)), min(height, int(bottom))
    if right - left < 2 or bottom - top < 2:
        raise CropError("The crop area is too small.")
    cropped = upright.crop((left, top, right, bottom))
    if fmt == "JPEG" and cropped.mode not in ("RGB", "L", "CMYK"):
        cropped = cropped.convert("RGB")
    if fmt == "GIF":
        params.pop("exif", None)
    save_format = {"MPO": "JPEG"}.get(fmt, fmt) or None
    cropped.save(out_path, save_format, **params)

    if et is not None:
        error = et.write(out_path, [
            "-TagsFromFile", path, "-all:all", "-unsafe", "-icc_profile",
            "-FileCreateDate<FileCreateDate", "-FileModifyDate<FileModifyDate",
            "-Orientation#=1",
            f"-ExifImageWidth={cropped.width}", f"-ExifImageHeight={cropped.height}",
            "-ThumbnailImage=", "-PreviewImage=",
        ])
        if error and "Nothing to do" not in error:
            raise CropError(f"Couldn't copy metadata: {error}")
    else:
        st = os.stat(path)
        os.utime(out_path, (st.st_atime, st.st_mtime))


def save_crop(path: str, box: tuple[int, int, int, int], et: "ExifTool | None" = None,
              as_copy: bool = False) -> str:
    """Crop path. Returns the path of the saved image.

    as_copy=True writes "<name>_crop<ext>" next to the original. Otherwise the
    original goes to the Recycle Bin and the cropped image takes its name.
    """
    src = Path(path)
    tmp = src.with_name(f"{src.stem}.cropping{src.suffix}")
    try:
        crop_to_file(path, box, str(tmp), et)
        if as_copy:
            dest = unique_path(src.with_name(f"{src.stem}_crop{src.suffix}"))
            os.replace(tmp, dest)
            return str(dest)
        from send2trash import send2trash

        send2trash(path)
        os.replace(tmp, path)
        return path
    finally:
        if tmp.exists():
            tmp.unlink()
