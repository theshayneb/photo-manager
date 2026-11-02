from datetime import datetime, timedelta

import pytest

from photo_manager.core.dates import format_display, format_pattern, parse_loose, parse_shift


@pytest.mark.parametrize("text,expected", [
    ("6/14/24 6:32p", datetime(2024, 6, 14, 18, 32)),
    ("06-14-2024 06-32-05 PM", datetime(2024, 6, 14, 18, 32, 5)),
    ("06-14-2024 06:32:05 AM", datetime(2024, 6, 14, 6, 32, 5)),
    ("6/14/2024 12:15 am", datetime(2024, 6, 14, 0, 15)),
    ("6/14/2024 12 pm", datetime(2024, 6, 14, 12, 0)),
    ("2024-06-14 18:32", datetime(2024, 6, 14, 18, 32)),
    ("2024:06:14 18:32:05", datetime(2024, 6, 14, 18, 32, 5)),
    ("20240614 183205", datetime(2024, 6, 14, 18, 32, 5)),
    ("6/14/2024", datetime(2024, 6, 14)),
    ("  6/14/99  ", datetime(1999, 6, 14)),
])
def test_parse_loose(text, expected):
    assert parse_loose(text) == expected


@pytest.mark.parametrize("text", ["", "hello", "13/40/2024", "6/14/2024 13 pm", "2024-02-30"])
def test_parse_loose_rejects(text):
    with pytest.raises(ValueError):
        parse_loose(text)


def test_parse_shift():
    assert parse_shift("+1h") == timedelta(hours=1)
    assert parse_shift("-2d 3h") == -timedelta(days=2, hours=3)
    assert parse_shift("30m") == timedelta(minutes=30)
    for bad in ("", "+", "1x", "h1", "+1y"):
        with pytest.raises(ValueError):
            parse_shift(bad)


def test_format_display_default_is_us_12_hour():
    assert format_display(datetime(2026, 10, 31, 21, 14, 2)) == "10-31-2026 09:14:02 PM"


def test_format_pattern():
    dt = datetime(2026, 10, 31, 21, 14, 2)
    assert format_pattern("{YYYY}-{MM}-{DD}_{HH}-{mm}-{ss}", dt) == "2026-10-31_21-14-02"
    assert format_pattern("{MM}-{DD}-{YYYY} {hh}-{mm}-{ss} {AMPM}", dt) == "10-31-2026 09-14-02 PM"
    assert format_pattern("{YYYY}/{MM}:x", dt) == "2026-10-x"  # Windows-illegal characters replaced
