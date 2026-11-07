"""Filename templates: read a date out of a filename such as IMG_20261023_000100.

Pattern syntax (matched from the start of the filename, case-insensitive;
anything after the pattern is ignored, so extensions and suffixes don't matter):

    {YYYY} {YY} {MM} {M} {DD} {D} {HH} {H} {hh} {h} {mm} {ss}
    {fff}   fractional seconds / milliseconds (any number of digits, ignored)
    {AMPM}  AM or PM (use with {hh} or {h})
    *       any text (including none)
    ?       exactly one character
    #       exactly one digit

Note {MM} is month and {mm} is minute.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

_TOKENS = {
    "YYYY": r"(?P<Y>\d{4})",
    "YY": r"(?P<y>\d{2})",
    "MM": r"(?P<M>\d{2})",
    "M": r"(?P<M>\d{1,2})",
    "DD": r"(?P<D>\d{2})",
    "D": r"(?P<D>\d{1,2})",
    "HH": r"(?P<H>\d{2})",
    "H": r"(?P<H>\d{1,2})",
    "hh": r"(?P<h>\d{2})",
    "h": r"(?P<h>\d{1,2})",
    "mm": r"(?P<m>\d{2})",
    "ss": r"(?P<s>\d{2})",
    "fff": r"(?P<f>\d+)",
    "AMPM": r"(?P<p>[AP]M)",
}

_PIECE = re.compile(r"\{(\w+)\}|(\*)|(\?)|(#)|([^{*?#]+|\{)")


class TemplateError(ValueError):
    pass


@dataclass
class FilenameTemplate:
    name: str
    pattern: str
    utc: bool = False  # filename time is UTC (Google Pixel does this)

    def compile(self) -> re.Pattern[str]:
        return compile_pattern(self.pattern)

    def match(self, filename: str) -> datetime | None:
        try:
            regex = self.compile()
        except TemplateError:
            return None
        found = regex.match(filename)
        if not found:
            return None
        try:
            dt = _build_datetime(found.groupdict())
        except ValueError:
            return None
        if self.utc:
            dt = dt.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
        return dt

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "FilenameTemplate":
        return cls(
            name=str(data.get("name", "")),
            pattern=str(data.get("pattern", "")),
            utc=bool(data.get("utc", False)),
        )


def compile_pattern(pattern: str) -> re.Pattern[str]:
    if not pattern.strip():
        raise TemplateError("The pattern is empty.")
    parts: list[str] = []
    for token, star, question, hash_, literal in _PIECE.findall(pattern):
        if token:
            if token not in _TOKENS:
                raise TemplateError(f"Unknown placeholder {{{token}}}.")
            parts.append(_TOKENS[token])
        elif star:
            parts.append(".*?")
        elif question:
            parts.append(".")
        elif hash_:
            parts.append(r"\d")
        else:
            parts.append(re.escape(literal))
    regex = "".join(parts)
    try:
        compiled = re.compile(regex, re.IGNORECASE)
    except re.error as exc:
        raise TemplateError(f"Each placeholder can only be used once ({exc}).") from exc
    names = compiled.groupindex
    if "Y" not in names and "y" not in names:
        raise TemplateError("The pattern needs a year: {YYYY} or {YY}.")
    if "M" not in names or "D" not in names:
        raise TemplateError("The pattern needs a month {MM} and a day {DD}.")
    return compiled


def _build_datetime(g: dict[str, str | None]) -> datetime:
    year = int(g["Y"]) if g.get("Y") else 2000 + int(g["y"] or 0)
    if g.get("h"):
        hour = int(g["h"])
        if not 1 <= hour <= 12:
            raise ValueError("12-hour clock out of range")
        if g.get("p"):
            hour = hour % 12 + (12 if g["p"].upper() == "PM" else 0)
    else:
        hour = int(g.get("H") or 0)
    return datetime(
        year, int(g["M"] or 0), int(g["D"] or 0),
        hour, int(g.get("m") or 0), int(g.get("s") or 0),
    )


def match_any(
    templates: list[FilenameTemplate], filename: str
) -> tuple[FilenameTemplate, datetime] | None:
    """Try templates in order; return the first that matches."""
    for template in templates:
        dt = template.match(filename)
        if dt is not None:
            return template, dt
    return None


DEFAULT_TEMPLATES = [
    FilenameTemplate("Pixel (PXL_, UTC time)", "PXL_{YYYY}{MM}{DD}_{HH}{mm}{ss}{fff}", utc=True),
    FilenameTemplate("Phone photo (IMG_)", "IMG_{YYYY}{MM}{DD}_{HH}{mm}{ss}"),
    FilenameTemplate("Phone video (VID_)", "VID_{YYYY}{MM}{DD}_{HH}{mm}{ss}"),
    FilenameTemplate("Screenshot", "Screenshot_{YYYY}{MM}{DD}-{HH}{mm}{ss}"),
    FilenameTemplate("Renamed by this app (08-15-2026 11-42-44 AM)", "{MM}-{DD}-{YYYY} {hh}-{mm}-{ss} {AMPM}"),
    FilenameTemplate("Already renamed", "{YYYY}-{MM}-{DD}_{HH}-{mm}-{ss}"),
    FilenameTemplate("Digits only (YYYYMMDDHHMMSS)", "{YYYY}{MM}{DD}{HH}{mm}{ss}"),
    FilenameTemplate("Number_YYYYMMDDHHMMSS (e.g. 4981570_20261105132923_1)", "*_{YYYY}{MM}{DD}{HH}{mm}{ss}"),
    FilenameTemplate("Anything with YYYYMMDD_HHMMSS", "*{YYYY}{MM}{DD}?{HH}{mm}{ss}"),
]


def rename_pattern_regex(pattern: str) -> re.Pattern[str] | None:
    """A regex that fully matches a file name (without extension) produced by a
    rename pattern, including the "_1", "_2" added for duplicates. None if the
    pattern has no date in it (then nothing is flagged)."""
    try:
        compiled = compile_pattern(pattern.replace("{name}", "*"))
    except TemplateError:
        return None
    return re.compile(rf"(?:{compiled.pattern})(?:_\d+)?", re.IGNORECASE)


def follows_pattern(filename: str, regex: re.Pattern[str] | None) -> bool:
    if regex is None:
        return True
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    return regex.fullmatch(stem) is not None
