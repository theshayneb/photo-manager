"""Windows Explorer thumbnails. Runs only on Windows (CI)."""

import sys

import pytest
from PIL import Image

from photo_manager.core.winthumb import shell_thumbnail

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")


def test_shell_thumbnail_of_a_jpeg(tmp_path):
    path = tmp_path / "wide.jpg"
    Image.new("RGB", (800, 400), "orange").save(path)
    im = shell_thumbnail(str(path), 256)
    assert im is not None
    assert max(im.size) <= 256 and im.width > im.height
    r, g, b = im.convert("RGB").getpixel((im.width // 2, im.height // 2))
    assert r > 200 and 100 < g < 200 and b < 80  # orange, not garbage


def test_shell_thumbnail_missing_file(tmp_path):
    assert shell_thumbnail(str(tmp_path / "nope.mp4"), 256) is None
