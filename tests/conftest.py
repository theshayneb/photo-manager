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


@pytest.fixture(autouse=True)
def close_all_windows():
    """Close and delete every window/dialog a test leaves behind, while Qt is still running.

    Leftover widgets were otherwise destroyed during interpreter shutdown, sometimes after
    Qt itself, which crashed the test process after every test had passed."""
    yield
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return
    for widget in QApplication.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QApplication.processEvents()


@pytest.fixture(autouse=True)
def no_steam_store(monkeypatch):
    """Tests never ask the real Steam store for game names."""
    from photo_manager.core import steam

    monkeypatch.setattr(steam, "fetch_store_names", lambda app_ids, timeout=5.0: {})
