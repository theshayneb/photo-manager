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


# On Windows the test process sometimes crashes *after* all tests have finished, while
# Python tears down Qt and the Windows thumbnail/COM helpers. The results are already
# reported by then, so exit straight away with pytest's real exit status instead of
# risking a teardown crash turning a green run red. Test failures still fail the run.
_exit_status: dict[str, int] = {}


def pytest_sessionfinish(session, exitstatus):
    _exit_status["code"] = int(exitstatus)


@pytest.hookimpl(trylast=True)
def pytest_unconfigure(config):
    if sys.platform == "win32" and "code" in _exit_status:
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(_exit_status["code"])
