from pathlib import Path

from PIL import Image

from photo_manager.core import fileops, thumbs
from photo_manager.core.exiftool import ExifTool
from photo_manager.core.metadata import READ_TAGS, keyword_args, parse_meta
from photo_manager.core.settings import Settings
from photo_manager.core.templates import FilenameTemplate

from .conftest import FAKE_EXIFTOOL


def test_stay_open_protocol_round_trip(tmp_path):
    photo = tmp_path / "ünïcode photo.jpg"
    photo.write_bytes(b"x")
    with ExifTool(FAKE_EXIFTOOL) as et:
        assert et.execute("-ver")[0].strip() == "13.00"
        assert et.write(str(photo), keyword_args(str(photo), add=["josh"])) is None
        assert et.write(str(photo), keyword_args(str(photo), add=["josh", "new york"])) is None
        [data] = et.read([str(photo)], READ_TAGS)
        assert parse_meta(data).keywords == ["josh", "new york"]
        assert et.write(str(tmp_path / "missing.jpg"), ["-XMP-xmp:Label=Red"])


def test_unique_names_and_renames(tmp_path):
    for name in ("a.jpg", "b.jpg", "2026-10-31.jpg"):
        (tmp_path / name).write_bytes(b"x")
    plan = fileops.plan_renames({str(tmp_path / "a.jpg"): "2026-10-31", str(tmp_path / "b.jpg"): "2026-10-31"})
    assert sorted(Path(p).name for p in plan.values()) == ["2026-10-31_1.jpg", "2026-10-31_2.jpg"]
    done, failures = fileops.rename(plan)
    assert len(done) == 2 and not failures


def test_move_never_overwrites(tmp_path):
    src, dest = tmp_path / "src", tmp_path / "dest"
    src.mkdir(), dest.mkdir()
    (src / "a.jpg").write_bytes(b"new")
    (dest / "a.jpg").write_bytes(b"old")
    moved, failures = fileops.move([str(src / "a.jpg")], str(dest))
    assert not failures and Path(moved[str(src / "a.jpg")]).name == "a_1.jpg"
    assert (dest / "a.jpg").read_bytes() == b"old"


def test_thumbnail_respects_orientation_and_caches(tmp_path):
    photo = tmp_path / "rotated.jpg"
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90°: stored landscape, shown portrait
    Image.new("RGB", (400, 200), "red").save(photo, exif=exif)
    im = thumbs.thumbnail(str(photo), 100, tmp_path / "cache")
    assert im is not None and im.size == (50, 100)
    assert list((tmp_path / "cache").rglob("*.png"))
    assert thumbs.thumbnail(str(tmp_path / "broken.jpg"), 100) is None


def test_settings_round_trip(tmp_path):
    path = tmp_path / "settings.json"
    s = Settings.load(path)
    assert "josh" in s.keyword_sets["Shayne"]
    s.templates.append(FilenameTemplate("Mine", "DSC_{YYYY}{MM}{DD}", utc=False))
    s.keyword_sets["Trips"] = ["paris"]
    s.save()
    again = Settings.load(path)
    assert again.templates[-1].name == "Mine" and again.keyword_sets["Trips"] == ["paris"]


def test_move_retries_while_a_file_is_briefly_in_use(tmp_path, monkeypatch):
    src, dest = tmp_path / "a.mp4", tmp_path / "out" / "a.mp4"
    src.write_bytes(b"video")
    dest.parent.mkdir()
    real_rename = fileops.os.rename
    attempts = []

    def flaky_rename(a, b):
        attempts.append(1)
        if len(attempts) < 3:  # "in use" for the first two tries, like a just-stopped video
            raise PermissionError(32, "The process cannot access the file")
        return real_rename(a, b)

    monkeypatch.setattr(fileops.os, "rename", flaky_rename)
    fileops.move_one(str(src), str(dest), retry_seconds=5)
    assert dest.read_bytes() == b"video" and not src.exists() and len(attempts) == 3


def test_failed_move_never_leaves_two_copies(tmp_path, monkeypatch):
    import errno

    src, dest = tmp_path / "a.jpg", tmp_path / "out" / "a.jpg"
    src.write_bytes(b"photo")
    dest.parent.mkdir()

    def other_drive(a, b):
        raise OSError(errno.EXDEV, "different drive")

    def locked_remove(p):
        if str(p) == str(src):
            raise PermissionError(32, "in use")
        return real_remove(p)

    real_remove = fileops.os.remove
    monkeypatch.setattr(fileops.os, "rename", other_drive)
    monkeypatch.setattr(fileops.os, "remove", locked_remove)
    monkeypatch.setattr(fileops, "IN_USE_RETRY_SECONDS", 0.3)
    moved, failures = fileops.move([str(src)], str(dest.parent))
    assert not moved and failures and "in use" in failures[0][1]
    assert src.exists() and not dest.exists()  # original kept, no stray copy
