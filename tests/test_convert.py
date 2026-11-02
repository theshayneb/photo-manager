from pathlib import Path

import pytest
from PIL import Image

from photo_manager.core.convert import convert_file, needs_conversion


def test_heic_to_jpg_upright_with_same_name(tmp_path):
    pillow_heif = pytest.importorskip("pillow_heif")
    pillow_heif.register_heif_opener()
    src = tmp_path / "phone.heic"
    Image.new("RGB", (64, 32), "orange").save(src, "HEIF")
    out = convert_file(str(src), "JPG", 90)
    assert Path(out).name == "phone.jpg" and src.exists()
    with Image.open(out) as im:
        assert im.format == "JPEG" and im.size == (64, 32)


def test_transparent_webp_goes_on_white_and_names_dont_clash(tmp_path):
    src = tmp_path / "logo.webp"
    Image.new("RGBA", (20, 20), (255, 0, 0, 0)).save(src, "WEBP", lossless=True)
    (tmp_path / "logo.jpg").write_bytes(b"existing")
    out = convert_file(str(src), "JPG")
    assert Path(out).name == "logo_1.jpg"
    with Image.open(out) as im:
        r, g, b = im.convert("RGB").getpixel((10, 10))
        assert min(r, g, b) > 240  # white, not black
    assert (tmp_path / "logo.jpg").read_bytes() == b"existing"


def test_recycle_original(tmp_path, monkeypatch):
    src = tmp_path / "a.png"
    Image.new("RGB", (8, 8)).save(src)
    trashed = []
    monkeypatch.setattr("send2trash.send2trash", lambda p: trashed.append(p) or Path(p).unlink())
    out = convert_file(str(src), "JPG", recycle_original=True)
    assert trashed == [str(src)] and Path(out).exists()


def test_needs_conversion():
    assert needs_conversion("x.HEIC") and needs_conversion("x.webp") and needs_conversion("x.avif")
    assert not needs_conversion("x.JPG") and not needs_conversion("x.jpeg") and not needs_conversion("x.mp4")
    assert needs_conversion("x.jpg", "PNG") and not needs_conversion("x.png", "PNG")
