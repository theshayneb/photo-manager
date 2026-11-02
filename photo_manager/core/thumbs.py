"""Thumbnail and preview loading with Pillow (plus HEIC) and ffmpeg for video.

No Qt here, so it can run in worker threads and be tested on its own.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps

from .media import kind
from .winthumb import shell_thumbnail

try:  # HEIC/HEIF support
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:  # pragma: no cover
    pass

Image.MAX_IMAGE_PIXELS = None  # big panoramas are fine; these are the user's own files

_FFMPEG = shutil.which("ffmpeg")


def open_image(path: str, max_size: int | None = None) -> Image.Image:
    """Open an image upright (EXIF orientation applied), optionally downscaled."""
    with Image.open(path) as im:
        if max_size:
            im.draft("RGB", (max_size, max_size))  # fast JPEG downscale
        im.seek(0)
        im = ImageOps.exif_transpose(im)
        if max_size:
            im.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        mode = "RGBA" if im.mode in ("RGBA", "LA", "P", "PA") else "RGB"
        return im.convert(mode)


def video_frame(path: str, max_size: int) -> Image.Image | None:
    if not _FFMPEG:
        return None
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    for seek in ("1", "0"):
        try:
            result = subprocess.run(
                [_FFMPEG, "-v", "error", "-ss", seek, "-i", path, "-frames:v", "1",
                 "-vf", f"scale={max_size}:{max_size}:force_original_aspect_ratio=decrease",
                 "-f", "image2pipe", "-vcodec", "png", "-"],
                capture_output=True, timeout=20, creationflags=flags,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.stdout:
            return Image.open(BytesIO(result.stdout)).convert("RGB")
    return None


def _cache_file(cache_dir: Path, path: str, size: int) -> Path | None:
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = f"{os.path.normcase(path)}|{st.st_mtime_ns}|{st.st_size}|{size}"
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
    return cache_dir / digest[:2] / f"{digest}.png"


def thumbnail(path: str, size: int, cache_dir: Path | None = None) -> Image.Image | None:
    """Return a thumbnail no bigger than size x size, or None if unreadable."""
    cached = _cache_file(cache_dir, path, size) if cache_dir else None
    if cached and cached.exists():
        try:
            with Image.open(cached) as im:
                return im.copy()
        except OSError:
            pass
    im = None
    try:
        if kind(path) == "video":
            # Windows' own thumbnail first (same as Explorer), then ffmpeg if installed.
            im = shell_thumbnail(path, size) or video_frame(path, size)
        else:
            im = open_image(path, size)
    except Exception:  # noqa: BLE001 - corrupt/unsupported files just get no thumbnail
        im = None
    if im is None and kind(path) != "video":
        try:
            im = shell_thumbnail(path, size)
        except Exception:  # noqa: BLE001
            im = None
    if im is not None and cached:
        try:
            cached.parent.mkdir(parents=True, exist_ok=True)
            im.save(cached, "PNG", optimize=False, compress_level=1)
        except OSError:
            pass
    return im
