from datetime import datetime

from photo_manager.core.media import kind, metadata_writable
from photo_manager.core.metadata import date_args, keyword_args, label_args, parse_meta

DT = datetime(2026, 10, 31, 21, 14, 2)


def test_parse_meta_prefers_exif_date_and_merges_keywords():
    meta = parse_meta({
        "SourceFile": "a.jpg",
        "EXIF:DateTimeOriginal": "2026:10:31 21:14:02",
        "EXIF:CreateDate": "2020:01:01 00:00:00",
        "File:FileCreateDate": "2026:11:01 08:00:00-04:00",
        "IPTC:Keywords": ["concert", "Josh"],
        "XMP:Subject": ["josh", "brooklyn"],
        "XMP:Label": "red",
        "Composite:ImageSize": "4032x3024",
    })
    assert meta.date_taken == DT and meta.date_source == "EXIF"
    assert meta.file_created == datetime(2026, 11, 1, 8, 0, 0)
    assert meta.keywords == ["josh", "brooklyn", "concert"]
    assert meta.label == "Red"
    assert meta.image_size == "4032x3024"


def test_parse_meta_video_and_odd_values():
    meta = parse_meta({"QuickTime:CreateDate": "2026:10:31 21:14:02-04:00", "XMP:Subject": 2024,
                       "EXIF:DateTimeOriginal": "0000:00:00 00:00:00"})
    assert meta.date_taken == DT and meta.date_source == "video"
    assert meta.keywords == ["2024"]


def test_date_args_image_video_and_file_dates():
    assert date_args("a.jpg", DT, set_file_dates=False) == ["-AllDates=2026:10:31 21:14:02", "-P"]
    video = date_args("b.mp4", DT, set_file_dates=True)
    assert "-QuickTime:CreateDate=2026:10:31 21:14:02" in video
    assert "-FileCreateDate=2026:10:31 21:14:02" in video and "-P" not in video


def test_keyword_args_jpeg_writes_iptc_and_xmp_without_duplicates():
    args = keyword_args("a.JPG", add=["josh"], remove=["me"])
    assert args[0] == "-P"
    assert "-XMP-dc:Subject-=me" in args and "-IPTC:Keywords-=me" in args
    assert args.index("-XMP-dc:Subject-=josh") < args.index("-XMP-dc:Subject+=josh")
    assert "-IPTC:CodedCharacterSet=UTF8" in args


def test_keyword_args_png_is_xmp_only():
    assert not any("IPTC" in a for a in keyword_args("a.png", add=["josh"]))


def test_label_args():
    assert label_args("Red") == ["-P", "-XMP-xmp:Label=Red"]
    assert label_args("") == ["-P", "-XMP-xmp:Label="]


def test_media_kinds():
    assert kind("x.HEIC") == "image" and kind("x.mov") == "video" and kind("x.txt") is None
    assert metadata_writable("x.webp") and metadata_writable("x.mp4")
    assert not metadata_writable("x.avi") and not metadata_writable("x.bmp")
