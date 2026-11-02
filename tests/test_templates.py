from datetime import datetime

import pytest

from photo_manager.core.templates import (
    DEFAULT_TEMPLATES, FilenameTemplate, TemplateError, compile_pattern, match_any,
)


def auto(filename):
    found = match_any(DEFAULT_TEMPLATES, filename)
    return (found[0].name, found[1]) if found else None


def test_samsung_style_img_name():
    assert auto("IMG_20261023_000100_358_3.jpg") == (
        "Phone photo (IMG_)", datetime(2026, 10, 23, 0, 1, 0))


def test_screenshot_name():
    assert auto("Screenshot_20261023-143414.png") == (
        "Screenshot", datetime(2026, 10, 23, 14, 34, 14))


def test_pixel_names_are_converted_from_utc(new_york_tz):
    # 14:02:29 UTC on Oct 31 is 10:02:29 in New York (EDT).
    assert auto("PXL_20261031_140229473.jpg") == (
        "Pixel (PXL_, UTC time)", datetime(2026, 10, 31, 10, 2, 29))
    # 01:14:02 UTC on Nov 1 is still the evening of Oct 31 in New York.
    name, dt = auto("PXL_20261101_011402198.LS.mp4")
    assert dt == datetime(2026, 10, 31, 21, 14, 2)


def test_non_matching_names_are_skipped():
    assert auto("vacation.jpg") is None
    assert auto("IMG_2026.jpg") is None


def test_impossible_dates_do_not_match():
    assert FilenameTemplate("x", "IMG_{YYYY}{MM}{DD}").match("IMG_20261345.jpg") is None


def test_twelve_hour_clock_with_ampm():
    t = FilenameTemplate("x", "{MM}-{DD}-{YYYY} {hh}-{mm}-{ss} {AMPM}")
    assert t.match("06-14-2024 06-32-05 PM.jpg") == datetime(2024, 6, 14, 18, 32, 5)
    assert t.match("06-14-2024 12-05-00 am.jpg") == datetime(2024, 6, 14, 0, 5, 0)


def test_wildcards_and_case_insensitivity():
    t = FilenameTemplate("x", "*{YYYY}{MM}{DD}?{HH}{mm}{ss}")
    assert t.match("whatsapp image 20240614-183205.jpeg") == datetime(2024, 6, 14, 18, 32, 5)
    assert FilenameTemplate("x", "img_{YYYY}{MM}{DD}").match("IMG_20240614.jpg") == datetime(2024, 6, 14)


@pytest.mark.parametrize("pattern", ["", "IMG_{MM}{DD}", "{YYYY}{MM}", "{YYYY}{MM}{DD}{MM}", "{nope}"])
def test_bad_patterns_are_rejected(pattern):
    with pytest.raises(TemplateError):
        compile_pattern(pattern)


def test_rename_pattern_regex_flags_misnamed_files():
    from photo_manager.core.templates import follows_pattern, rename_pattern_regex

    rx = rename_pattern_regex("{MM}-{DD}-{YYYY} {hh}-{mm}-{ss} {AMPM}")
    assert follows_pattern("08-15-2026 11-42-44 AM.jpg", rx)
    assert follows_pattern("08-15-2026 11-42-44 pm_2.HEIC", rx)
    for bad in ("IMG_20261023_000100_926_19.jpg", "08-15-2026 11-42-44.jpg",
                "08-15-2026 11-42-44 AM copy.jpg", "2026-08-15_11-42-44.jpg"):
        assert not follows_pattern(bad, rx), bad
    named = rename_pattern_regex("{YYYY}-{MM}-{DD} {name}")
    assert follows_pattern("2026-08-15 beach.jpg", named)
    assert rename_pattern_regex("{name}") is None  # no date: nothing is flagged
    assert follows_pattern("anything.jpg", None)
