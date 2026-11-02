"""Reading dates people type, shifting dates, and formatting dates.

Placeholders shared by rename patterns and filename templates:

    {YYYY} 4-digit year      {YY} 2-digit year
    {MM}   month 01-12       {DD} day 01-31
    {HH}   hour 00-23        {hh} hour 01-12      {AMPM} AM/PM
    {mm}   minute            {ss} second
    {name} current filename (rename patterns only)
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

DEFAULT_DISPLAY_FORMAT = "%m-%d-%Y %I:%M:%S %p"
EXIF_FORMAT = "%Y:%m:%d %H:%M:%S"


def to_exif(dt: datetime) -> str:
    return dt.strftime(EXIF_FORMAT)


def format_display(dt: datetime | None, fmt: str = DEFAULT_DISPLAY_FORMAT) -> str:
    if dt is None:
        return ""
    try:
        return dt.strftime(fmt)
    except (ValueError, TypeError):
        return dt.strftime(DEFAULT_DISPLAY_FORMAT)


# --------------------------------------------------------------------------
# Typed dates
# --------------------------------------------------------------------------

_TIME = (
    r"(?:[\sT_,]+(?P<H>\d{1,2})(?:[:\-.](?P<m>\d{2}))?(?:[:\-.](?P<s>\d{2}))?"
    r"\s*(?P<p>[ap])?\.?m?\.?)?"
)
_COMPACT_TIME = r"(?:[\sT_\-]*(?P<H>\d{2})(?P<m>\d{2})(?P<s>\d{2})?)?"

_DATE_PATTERNS = [
    # 2024-06-14 / 2024:06:14 / 2024/6/14
    re.compile(r"^(?P<Y>\d{4})[\-/.:](?P<M>\d{1,2})[\-/.:](?P<D>\d{1,2})" + _TIME + r"$", re.I),
    # 6/14/2024, 06-14-24 (US order: month first)
    re.compile(r"^(?P<M>\d{1,2})[\-/.](?P<D>\d{1,2})[\-/.](?P<Y>\d{2}|\d{4})" + _TIME + r"$", re.I),
    # 20240614 183205
    re.compile(r"^(?P<Y>\d{4})(?P<M>\d{2})(?P<D>\d{2})" + _COMPACT_TIME + r"$", re.I),
]


def _full_year(text: str) -> int:
    year = int(text)
    if len(text) == 2:
        year += 2000 if year < 70 else 1900
    return year


def parse_loose(text: str) -> datetime:
    """Parse a date the way a person types it. Month comes before day.

    Accepts e.g. "6/14/24 6:32p", "06-14-2024 06-32-05 PM",
    "2024-06-14 18:32", "2024:06:14 18:32:05", "20240614 183205".
    Raises ValueError when the text isn't a date.
    """
    cleaned = " ".join(text.strip().split())
    if not cleaned:
        raise ValueError("empty")
    for pattern in _DATE_PATTERNS:
        match = pattern.match(cleaned)
        if not match:
            continue
        g = match.groupdict()
        hour = int(g.get("H") or 0)
        ampm = (g.get("p") or "").lower()
        if ampm:
            if not 1 <= hour <= 12:
                raise ValueError("hour must be 1-12 with AM/PM")
            hour = hour % 12 + (12 if ampm == "p" else 0)
        return datetime(
            _full_year(g["Y"]), int(g["M"]), int(g["D"]),
            hour, int(g.get("m") or 0), int(g.get("s") or 0),
        )
    raise ValueError(f"not a date: {text!r}")


_SHIFT_PART = re.compile(r"(?P<n>\d+)\s*(?P<u>y|mo|w|d|h|m|s)", re.I)


def parse_shift(text: str) -> timedelta:
    """Parse an offset like "+2h", "-1d 3h 15m", "+30s" ("mo"/"y" not allowed)."""
    cleaned = text.strip().replace(" ", "")
    if not cleaned:
        raise ValueError("empty")
    sign = -1 if cleaned.startswith("-") else 1
    body = cleaned.lstrip("+-")
    pos = 0
    total = timedelta()
    units = {"w": "weeks", "d": "days", "h": "hours", "m": "minutes", "s": "seconds"}
    for match in _SHIFT_PART.finditer(body):
        if match.start() != pos:
            raise ValueError(f"can't read shift: {text!r}")
        unit = match["u"].lower()
        if unit not in units:
            raise ValueError("use w, d, h, m or s")
        total += timedelta(**{units[unit]: int(match["n"])})
        pos = match.end()
    if pos != len(body) or pos == 0:
        raise ValueError(f"can't read shift: {text!r}")
    return sign * total


# --------------------------------------------------------------------------
# Rename patterns
# --------------------------------------------------------------------------

_INVALID_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def format_pattern(pattern: str, dt: datetime, name: str = "") -> str:
    """Fill a rename pattern like "{YYYY}-{MM}-{DD}_{HH}-{mm}-{ss}".

    {name} is the file's current name without its extension.
    """
    values = {
        "YYYY": f"{dt.year:04d}",
        "YY": f"{dt.year % 100:02d}",
        "MM": f"{dt.month:02d}",
        "DD": f"{dt.day:02d}",
        "HH": f"{dt.hour:02d}",
        "hh": f"{(dt.hour % 12) or 12:02d}",
        "mm": f"{dt.minute:02d}",
        "ss": f"{dt.second:02d}",
        "AMPM": "AM" if dt.hour < 12 else "PM",
        "name": name,
    }

    def repl(match: re.Match[str]) -> str:
        return values.get(match[1], match[0])

    name = re.sub(r"\{(\w+)\}", repl, pattern)
    return _INVALID_NAME_CHARS.sub("-", name).strip().rstrip(".")
