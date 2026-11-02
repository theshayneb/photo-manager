"""Round trips through the real ExifTool. Skipped when exiftool isn't installed
(CI on Windows downloads it, so these always run there)."""

import os
import sys
from datetime import datetime

import pytest
from PIL import Image

from photo_manager.core.exiftool import ExifTool, find_exiftool
from photo_manager.core.metadata import READ_TAGS, date_args, keyword_args, label_args, parse_meta

EXIFTOOL = find_exiftool()
pytestmark = pytest.mark.skipif(not EXIFTOOL, reason="ExifTool not installed")

DT = datetime(2024, 6, 14, 18, 32, 5)


@pytest.fixture(scope="module")
def et():
    with ExifTool(EXIFTOOL) as tool:
        yield tool


def make(tmp_path, name):
    path = tmp_path / name
    fmt = {".jpg": "JPEG", ".png": "PNG", ".gif": "GIF", ".webp": "WEBP", ".heic": "HEIF"}[path.suffix]
    if fmt == "HEIF":
        pytest.importorskip("pillow_heif").register_heif_opener()
    Image.new("RGB", (32, 24), "green").save(path, fmt)
    return str(path)


def read(et, path):
    [data] = et.read([path], READ_TAGS)
    return parse_meta(data)


@pytest.mark.parametrize("name", ["photo.jpg", "image.png", "anim.gif", "pic.webp", "phone ü.heic"])
def test_date_keywords_label_round_trip(et, tmp_path, name):
    path = make(tmp_path, name)
    assert et.write(path, date_args(path, DT, set_file_dates=True)) is None
    assert et.write(path, keyword_args(path, add=["josh", "new york"])) is None
    assert et.write(path, keyword_args(path, add=["josh"])) is None  # no duplicate
    assert et.write(path, keyword_args(path, remove=["new york"])) is None
    assert et.write(path, label_args("Red")) is None
    meta = read(et, path)
    assert meta.date_taken == DT
    assert meta.keywords == ["josh"]
    assert meta.label == "Red"
    if sys.platform == "win32":
        assert meta.file_created == DT
    assert datetime.fromtimestamp(os.path.getmtime(path)).replace(microsecond=0) == DT


def test_keyword_edit_preserves_modified_time(et, tmp_path):
    path = make(tmp_path, "keep.jpg")
    os.utime(path, (1_600_000_000, 1_600_000_000))
    assert et.write(path, keyword_args(path, add=["concert"])) is None
    assert int(os.path.getmtime(path)) == 1_600_000_000


def test_jpeg_keywords_visible_to_windows(et, tmp_path):
    path = make(tmp_path, "win.jpg")
    et.write(path, keyword_args(path, add=["rego park"]))
    [data] = et.read([path], READ_TAGS)
    assert data.get("IPTC:Keywords") == "rego park"
    assert data.get("XMP:Subject") == "rego park"


def test_crop_keeps_metadata(et, tmp_path):
    from photo_manager.core.crop import save_crop

    path = make(tmp_path, "keep me.jpg")
    et.write(path, date_args(path, DT, set_file_dates=True))
    et.write(path, keyword_args(path, add=["josh"]))
    et.write(path, label_args("Green"))
    copy = save_crop(path, (2, 2, 20, 16), et, as_copy=True)
    meta = read(et, copy)
    assert meta.date_taken == DT and meta.keywords == ["josh"] and meta.label == "Green"
    assert meta.image_size == "18x14"
    if sys.platform == "win32":
        assert meta.file_created == DT


def test_convert_heic_to_jpg_keeps_metadata(et, tmp_path):
    from photo_manager.core.convert import convert_file

    path = make(tmp_path, "phone.heic")
    et.write(path, date_args(path, DT, set_file_dates=True))
    et.write(path, keyword_args(path, add=["josh"]))
    et.write(path, label_args("Blue"))
    out = convert_file(path, "JPG", 90, et)
    meta = read(et, out)
    assert out.endswith("phone.jpg")
    assert meta.date_taken == DT and meta.keywords == ["josh"] and meta.label == "Blue"
    if sys.platform == "win32":
        assert meta.file_created == DT


@pytest.mark.parametrize("name", ["star.jpg", "star.png", "star.heic"])
def test_star_and_bookmark_round_trip(et, tmp_path, name):
    from photo_manager.core.metadata import flag_args

    path = make(tmp_path, name)
    assert et.write(path, flag_args("Star", True)) is None
    assert et.write(path, flag_args("Bookmark", True)) is None
    meta = read(et, path)
    assert meta.starred and meta.rating == 5 and meta.bookmarked
    assert et.write(path, flag_args("Star", False)) is None
    assert et.write(path, flag_args("Bookmark", False)) is None
    meta = read(et, path)
    assert not meta.starred and not meta.bookmarked
