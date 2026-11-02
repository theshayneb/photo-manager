"""File-type knowledge: which files we show and what metadata each can hold."""

from __future__ import annotations

from pathlib import Path

IMAGE_EXTS = {
    ".jpg", ".jpeg", ".jpe", ".png", ".gif", ".webp", ".heic", ".heif",
    ".avif", ".tif", ".tiff", ".bmp",
}

VIDEO_EXTS = {
    ".mp4", ".m4v", ".mov", ".3gp", ".avi", ".mkv", ".wmv", ".webm",
    ".mts", ".m2ts", ".mpg", ".mpeg", ".flv",
}

# Formats that can carry IPTC keywords (everything else gets XMP only).
IPTC_EXTS = {".jpg", ".jpeg", ".jpe", ".tif", ".tiff"}

# Video containers ExifTool can write dates/XMP into (QuickTime family).
WRITABLE_VIDEO_EXTS = {".mp4", ".m4v", ".mov", ".3gp"}

# Image formats ExifTool cannot write to at all.
READONLY_IMAGE_EXTS = {".bmp"}


def ext(path: str | Path) -> str:
    return Path(path).suffix.lower()


def kind(path: str | Path) -> str | None:
    """Return "image", "video" or None for files we don't show."""
    e = ext(path)
    if e in IMAGE_EXTS:
        return "image"
    if e in VIDEO_EXTS:
        return "video"
    return None


def is_media(path: str | Path) -> bool:
    return kind(path) is not None


def metadata_writable(path: str | Path) -> bool:
    """True when ExifTool can write dates/keywords/labels into the file itself."""
    e = ext(path)
    if e in VIDEO_EXTS:
        return e in WRITABLE_VIDEO_EXTS
    return e in IMAGE_EXTS and e not in READONLY_IMAGE_EXTS
