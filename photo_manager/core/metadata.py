"""What we read from each file, and the ExifTool arguments for each kind of edit."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from .dates import to_exif
from .media import IPTC_EXTS, ext, kind

READ_TAGS = [
    "-EXIF:DateTimeOriginal",
    "-EXIF:CreateDate",
    "-XMP:DateTimeOriginal",
    "-XMP:DateCreated",
    "-XMP:CreateDate",
    "-QuickTime:CreateDate",
    "-File:FileCreateDate",
    "-File:FileModifyDate",
    "-IPTC:Keywords",
    "-XMP:Subject",
    "-XMP:Label",
    "-XMP:Rating",
    "-XMP-xmpDM:Good",
    "-Duration#",  # videos: length in seconds (# = plain number)
    "-Composite:ImageSize",
]

# Where "date taken" comes from, best source first.
_DATE_SOURCES = [
    ("EXIF:DateTimeOriginal", "EXIF"),
    ("XMP:DateTimeOriginal", "XMP"),
    ("XMP:DateCreated", "XMP"),
    ("EXIF:CreateDate", "EXIF"),
    ("XMP:CreateDate", "XMP"),
    ("QuickTime:CreateDate", "video"),
]

LABELS = ["Red", "Yellow", "Green", "Blue", "Purple"]

_EXIF_DATE = re.compile(r"(\d{4})[:\-](\d{2})[:\-](\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?")


@dataclass
class Meta:
    date_taken: datetime | None = None
    date_source: str = ""
    create_date: datetime | None = None  # EXIF/XMP/QuickTime CreateDate ("digitized")
    file_created: datetime | None = None
    file_modified: datetime | None = None
    keywords: list[str] = field(default_factory=list)
    label: str = ""
    rating: int = 0
    bookmarked: bool = False
    duration: float | None = None  # videos: length in seconds
    image_size: str = ""

    @property
    def starred(self) -> bool:
        return self.rating > 0


def parse_exif_date(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    match = _EXIF_DATE.match(value.strip())
    if not match:
        return None
    try:
        return datetime(*(int(x or 0) for x in match.groups()))  # type: ignore[misc]
    except ValueError:  # 0000:00:00 and friends
        return None


def _as_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)]


def parse_duration(value: object) -> float | None:
    """Seconds from ExifTool's Duration: 12.5, "12.5", "12.50 s" or "0:01:05"."""
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    text = str(value or "").strip().lower().replace("(approx)", "").strip()
    if not text:
        return None
    try:
        if ":" in text:
            seconds = 0.0
            for part in text.split(":"):
                seconds = seconds * 60 + float(part)
            return seconds or None
        return float(text.rstrip("s").strip()) or None
    except ValueError:
        return None


def format_duration(seconds: float | None) -> str:
    """0:07, 4:32, 1:05:33."""
    if not seconds or seconds <= 0:
        return ""
    total = int(round(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def parse_meta(data: dict) -> Meta:
    meta = Meta()
    for key, source in _DATE_SOURCES:
        dt = parse_exif_date(data.get(key))
        if dt:
            meta.date_taken, meta.date_source = dt, source
            break
    for key in ("EXIF:CreateDate", "XMP:CreateDate", "QuickTime:CreateDate"):
        meta.create_date = parse_exif_date(data.get(key))
        if meta.create_date:
            break
    meta.file_created = parse_exif_date(data.get("File:FileCreateDate"))
    meta.file_modified = parse_exif_date(data.get("File:FileModifyDate"))
    seen: dict[str, None] = {}
    for kw in _as_list(data.get("XMP:Subject")) + _as_list(data.get("IPTC:Keywords")):
        kw = kw.strip()
        if kw and kw.casefold() not in {k.casefold() for k in seen}:
            seen[kw] = None
    meta.keywords = list(seen)
    label = str(data.get("XMP:Label") or "")
    meta.label = next((name for name in LABELS if name.lower() == label.lower()), label)
    try:
        meta.rating = int(data.get("XMP:Rating") or 0)
    except (TypeError, ValueError):
        meta.rating = 0
    meta.bookmarked = str(data.get("XMP:Good", "")).strip().lower() in ("true", "1")
    for key, value in data.items():
        if key.split(":")[-1] == "Duration":
            meta.duration = parse_duration(value)
            if meta.duration:
                break
    meta.image_size = str(data.get("Composite:ImageSize") or "").replace(" ", "x")
    return meta


# --------------------------------------------------------------------------
# Write arguments
# --------------------------------------------------------------------------

def date_args(path: str, dt: datetime, set_file_dates: bool) -> list[str]:
    """Arguments that set "date taken" (and optionally Windows file dates)."""
    value = to_exif(dt)
    args: list[str] = []
    if kind(path) == "video":
        # QuickTime stores UTC; QuickTimeUTC=1 (common args) converts local -> UTC.
        for tag in ("CreateDate", "ModifyDate", "TrackCreateDate", "TrackModifyDate",
                    "MediaCreateDate", "MediaModifyDate"):
            args.append(f"-QuickTime:{tag}={value}")
    else:
        # AllDates = DateTimeOriginal, CreateDate, ModifyDate. ExifTool puts them
        # in EXIF, or in XMP for formats without EXIF (GIF).
        args.append(f"-AllDates={value}")
    if set_file_dates:
        args += [f"-FileCreateDate={value}", f"-FileModifyDate={value}"]
    else:
        args.append("-P")
    return args


def keyword_args(path: str, add: list[str] = (), remove: list[str] = ()) -> list[str]:  # type: ignore[assignment]
    """Add/remove keywords without creating duplicates (XMP, plus IPTC for JPEG/TIFF)."""
    tags = ["XMP-dc:Subject"]
    if ext(path) in IPTC_EXTS:
        tags.append("IPTC:Keywords")
    args = ["-P"]
    for tag in tags:
        for kw in remove:
            args.append(f"-{tag}-={kw}")
        for kw in add:
            # "-=" then "+=" is ExifTool's idiom for "add if not already there".
            args += [f"-{tag}-={kw}", f"-{tag}+={kw}"]
    if "IPTC:Keywords" in tags and (add or remove):
        args.append("-IPTC:CodedCharacterSet=UTF8")
    return args


def label_args(label: str) -> list[str]:
    return ["-P", f"-XMP-xmp:Label={label}"]


# Star and Bookmark are on/off flags, independent of the color label.
# Star is stored as a 5-star rating (Windows Explorer, Lightroom and Bridge show it);
# Bookmark uses the XMP "Good" flag (xmpDM:good), which other apps generally ignore.
FLAGS = ("Star", "Bookmark")


def flag_args(flag: str, on: bool) -> list[str]:
    if flag == "Star":
        return ["-P", "-XMP-xmp:Rating=5" if on else "-XMP-xmp:Rating="]
    if flag == "Bookmark":
        return ["-P", "-XMP-xmpDM:Good=True" if on else "-XMP-xmpDM:Good="]
    raise ValueError(flag)


def has_flag(meta: "Meta | None", flag: str) -> bool:
    if meta is None:
        return False
    return meta.starred if flag == "Star" else meta.bookmarked
