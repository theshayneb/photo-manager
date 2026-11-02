"""End-to-end: the real window, driven offscreen, with the stand-in ExifTool."""

from datetime import datetime

import pytest
from PIL import Image
from PySide6.QtCore import QItemSelectionModel
from PySide6.QtWidgets import QApplication

from photo_manager.core.exiftool import ExifTool
from photo_manager.core.metadata import READ_TAGS, parse_meta
from photo_manager.core.settings import Settings
from photo_manager.ui.main_window import MainWindow

from .conftest import FAKE_EXIFTOOL


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp, tmp_path):
    folder = tmp_path / "photos"
    folder.mkdir()
    for name in ("IMG_20261023_000100_358_3.jpg", "Screenshot_20261023-143414.png", "vacation.jpg"):
        Image.new("RGB", (64, 48), "blue").save(folder / name)
    (folder / "notes.txt").write_text("not a photo")
    settings = Settings.load(tmp_path / "settings.json")
    settings.last_folder = str(folder)
    et = ExifTool(FAKE_EXIFTOOL)
    win = MainWindow(settings, et)
    win.show()
    settle(win)
    yield win, folder, et
    win.close()


def settle(win, rounds=40):
    for _ in range(rounds):
        win.bg.wait()
        win.model._pool.waitForDone()
        QApplication.processEvents()


def select(win, *names):
    sel = win.grid.selectionModel()
    sel.clearSelection()
    for name in names:
        row = next(r for r, i in enumerate(win.model.items) if i.name == name)
        sel.select(win.model.index(row), QItemSelectionModel.SelectionFlag.Select)
    win.refresh_sidebar()


def meta_of(et, path):
    return parse_meta(et.read([str(path)], READ_TAGS)[0])


def test_lists_only_media_and_loads_thumbnails(window):
    win, folder, _ = window
    assert sorted(i.name for i in win.model.items) == [
        "IMG_20261023_000100_358_3.jpg", "Screenshot_20261023-143414.png", "vacation.jpg"]
    win.grid.viewport().repaint()
    settle(win)
    assert all(i.meta is not None for i in win.model.items)
    assert any(i.thumb_state == "done" for i in win.model.items)


def test_typed_date_is_written(window):
    win, folder, et = window
    select(win, "vacation.jpg")
    win.sidebar.dates.edit.setText("6/14/24 6:32 pm")
    win.sidebar.dates.apply_typed()
    settle(win)
    meta = meta_of(et, folder / "vacation.jpg")
    assert meta.date_taken == datetime(2024, 6, 14, 18, 32)
    assert meta.file_created == datetime(2024, 6, 14, 18, 32)  # Windows dates on by default
    assert "06-14-2024 06:32:00 PM" in win.sidebar.dates.current.text()


def test_date_from_filename_skips_non_matching(window):
    win, folder, et = window
    select(win, "IMG_20261023_000100_358_3.jpg", "Screenshot_20261023-143414.png", "vacation.jpg")
    assert "2 files" in win.sidebar.dates.filename_btn.text()
    win.sidebar.dates.apply_filename()
    settle(win)
    assert meta_of(et, folder / "IMG_20261023_000100_358_3.jpg").date_taken == datetime(2026, 10, 23, 0, 1)
    assert meta_of(et, folder / "Screenshot_20261023-143414.png").date_taken == datetime(2026, 10, 23, 14, 34, 14)
    assert meta_of(et, folder / "vacation.jpg").date_taken is None


def test_keyword_buttons_toggle_and_typed_keywords(window):
    win, folder, et = window
    panel = win.sidebar.keywords
    select(win, "vacation.jpg", "IMG_20261023_000100_358_3.jpg")
    panel.buttons["josh"].click()
    settle(win)
    assert meta_of(et, folder / "vacation.jpg").keywords == ["josh"]
    assert panel.buttons["josh"].property("state") == "all"

    select(win, "vacation.jpg")
    panel.buttons["josh"].click()  # everyone has it -> removes
    settle(win)
    assert meta_of(et, folder / "vacation.jpg").keywords == []

    select(win, "vacation.jpg", "IMG_20261023_000100_358_3.jpg")
    assert panel.buttons["josh"].property("state") == "some"

    panel.add_edit.setText("coney island, josh")
    panel.add_edit.returnPressed.emit()
    settle(win)
    assert "coney island" in win.settings.keyword_sets["Shayne"]
    assert sorted(meta_of(et, folder / "vacation.jpg").keywords) == ["coney island", "josh"]


def test_color_label_shortcut_toggles(window):
    win, folder, et = window
    select(win, "vacation.jpg")
    win._label_shortcut("Red")
    settle(win)
    assert meta_of(et, folder / "vacation.jpg").label == "Red"
    win._label_shortcut("Red")  # same label again clears it
    settle(win)
    assert meta_of(et, folder / "vacation.jpg").label == ""


def test_rename_by_date(window):
    win, folder, et = window
    select(win, "IMG_20261023_000100_358_3.jpg")
    win.sidebar.dates.apply_filename()
    settle(win)
    select(win, "IMG_20261023_000100_358_3.jpg")
    assert "2026-10-23_00-01-00.jpg" in win.sidebar.rename.example.text()
    win.sidebar.rename.apply()
    settle(win)
    assert (folder / "2026-10-23_00-01-00.jpg").exists()
    assert any(i.name == "2026-10-23_00-01-00.jpg" for i in win.model.items)


def test_move_and_viewer(window, tmp_path, monkeypatch):
    win, folder, _ = window
    dest = tmp_path / "sorted"
    dest.mkdir()
    select(win, "vacation.jpg")
    win.grid.setCurrentIndex(win.model.index(win.model.row_of(str(folder / "vacation.jpg"))))
    win.open_viewer()
    assert win.viewer.isVisible() and win.viewer._pixmap is not None
    win.viewer.close()

    from photo_manager.ui import main_window

    class FakeMove:
        def __init__(self, *a, **k):
            self.folder = str(dest)

        def exec(self):
            return True

    monkeypatch.setattr(main_window, "MoveDialog", FakeMove)
    select(win, "vacation.jpg")
    win.move_selected()
    settle(win)
    assert (dest / "vacation.jpg").exists() and not (folder / "vacation.jpg").exists()
    assert len(win.model.items) == 2
    assert win.settings.recent_move_folders[0] == str(dest)
