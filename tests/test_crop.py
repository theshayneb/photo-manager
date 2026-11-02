from pathlib import Path

import pytest
from PIL import Image

from photo_manager.core.crop import CropError, crop_to_file, save_crop, upright_size


def test_crop_uses_upright_coordinates_and_resets_orientation(tmp_path):
    src = tmp_path / "rot.jpg"
    exif = Image.Exif()
    exif[0x0112] = 6  # stored 400x200 landscape, shown as 200x400 portrait
    Image.new("RGB", (400, 200), "red").save(src, exif=exif)
    assert upright_size(str(src)) == (200, 400)
    out = tmp_path / "out.jpg"
    crop_to_file(str(src), (0, 0, 100, 300), str(out))
    with Image.open(out) as im:
        assert im.size == (100, 300)
        assert im.getexif().get(0x0112) == 1


def test_save_crop_as_copy_and_replace(tmp_path, monkeypatch):
    src = tmp_path / "a.png"
    Image.new("RGBA", (50, 40), (0, 0, 255, 128)).save(src)
    copy = save_crop(str(src), (5, 5, 25, 25), as_copy=True)
    assert Path(copy).name == "a_crop.png" and src.exists()

    trashed = []
    monkeypatch.setattr("send2trash.send2trash", lambda p: trashed.append(p) or Path(p).unlink())
    assert save_crop(str(src), (0, 0, 10, 10)) == str(src)
    assert trashed == [str(src)]
    with Image.open(src) as im:
        assert im.size == (10, 10)
    assert not list(tmp_path.glob("*.cropping*"))


def test_tiny_crop_is_refused(tmp_path):
    src = tmp_path / "a.jpg"
    Image.new("RGB", (50, 40)).save(src)
    with pytest.raises(CropError):
        crop_to_file(str(src), (5, 5, 6, 6), str(tmp_path / "o.jpg"))
