import os
import sys
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

FAKE_EXIFTOOL = [sys.executable, str(Path(__file__).with_name("fake_exiftool.py"))]


@pytest.fixture
def new_york_tz(monkeypatch):
    """Run in US Eastern time so UTC filename conversions are predictable."""
    if not hasattr(time, "tzset"):
        pytest.skip("needs time.tzset (not available on Windows)")
    monkeypatch.setenv("TZ", "America/New_York")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


@pytest.fixture(autouse=True)
def isolated_appdata(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
