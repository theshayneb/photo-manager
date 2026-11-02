"""End-to-end: the real window, driven offscreen, with the stand-in ExifTool."""

import os
from datetime import datetime

import pytest
from PIL import Image
from PySide6.QtCore import QItemSelectionModel, QRectF, Qt
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
        row = next(win.model.row_of(i.path) for i in win.model.items if i.name == name)
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
    win.grid.select_paths([str(folder / "vacation.jpg")], current=str(folder / "vacation.jpg"))
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


def set_dates(win, et, folder, dates_by_name):
    for name, dt in dates_by_name.items():
        et.write(str(folder / name), [f"-AllDates={dt:%Y:%m:%d %H:%M:%S}"])
    win.open_folder(str(folder))
    settle(win)


def headers(win):
    return [r.title for r in win.model.rows if not hasattr(r, "kind")]


def test_group_by_week_respects_week_start(window):
    win, folder, et = window
    # Sat Oct 24, Sun Oct 25, Mon Oct 26 2026
    set_dates(win, et, folder, {
        "IMG_20261023_000100_358_3.jpg": datetime(2026, 10, 24, 12),
        "Screenshot_20261023-143414.png": datetime(2026, 10, 25, 12),
        "vacation.jpg": datetime(2026, 10, 26, 12),
    })
    win.set_group("week")
    assert headers(win) == ["Week 43  ·  Sun, Oct 18  –  Sat, Oct 24, 2026",
                            "Week 44  ·  Sun, Oct 25  –  Sat, Oct 31, 2026"]
    win.set_week_start("monday")
    assert headers(win) == ["Week 43  ·  Mon, Oct 19  –  Sun, Oct 25, 2026",
                            "Week 44  ·  Mon, Oct 26  –  Sun, Nov 1, 2026"]
    assert win.settings.group_by == "week" and win.settings.week_start == "monday"


def test_group_by_label_and_header_click_selects_group(window):
    win, folder, _ = window
    select(win, "vacation.jpg", "IMG_20261023_000100_358_3.jpg")
    win._label_shortcut("Blue")
    settle(win)
    win.set_group("label")
    assert headers(win) == ["Blue", "No label"]
    header_row = next(n for n, r in enumerate(win.model.rows) if getattr(r, "title", "") == "Blue")
    assert not (win.model.flags(win.model.index(header_row)) & Qt.ItemFlag.ItemIsSelectable)
    win.grid.select_paths(win.model.rows[header_row].paths)
    assert sorted(os.path.basename(p) for p in win.grid.selected_paths()) == [
        "IMG_20261023_000100_358_3.jpg", "vacation.jpg"]
    # Viewer navigation skips headers.
    first = win.model.items[0]
    assert win.model.neighbour(first.path, 1) is win.model.items[1]


def test_info_under_thumbnails(window):
    win, folder, et = window
    set_dates(win, et, folder, {"vacation.jpg": datetime(2026, 10, 31, 21, 14, 2)})
    item = win.model.item(str(folder / "vacation.jpg"))
    assert win.grid.delegate._info_lines(item) == ["10-31-2026 09:14:02 PM"]
    win._toggle_info("filesize", True)
    assert len(win.grid.delegate._info_lines(item)) == 2
    assert win.settings.thumb_info == ["date", "filesize"]


def test_rename_with_exif_create_date_and_name_token(window):
    win, folder, et = window
    et.write(str(folder / "vacation.jpg"), ["-EXIF:CreateDate=2025:01:02 03:04:05"])
    win.open_folder(str(folder))
    settle(win)
    select(win, "vacation.jpg")
    panel = win.sidebar.rename
    panel.source.setCurrentIndex(panel.source.findData("created"))
    panel.pattern.setText("{YYYY}-{MM}-{DD} {name}")
    assert "2025-01-02 vacation.jpg" in panel.example.text()
    panel.apply()
    settle(win)
    assert (folder / "2025-01-02 vacation.jpg").exists()


def test_favorites_and_panels(window, tmp_path):
    win, folder, _ = window
    win.toggle_favorite(str(folder))
    assert win.settings.favorites == [str(folder)] and win.favorites.count() == 1
    assert win.fav_action.text() == "★"
    win.toggle_favorite(str(folder))
    assert win.settings.favorites == [] and win.fav_action.text() == "☆"

    win.panel_actions["rename"].setChecked(False)
    assert win.sidebar.sections["rename"].isHidden()
    assert win.settings.hidden_panels == ["rename"]
    win.sidebar.sections["keywords"].header.setChecked(False)
    assert win.sidebar.keywords.isHidden()
    assert win.settings.collapsed_panels == ["keywords"]


def test_dark_theme_applies(window):
    win, _, _ = window
    win.set_theme("dark")
    assert QApplication.instance().palette().window().color().name() == "#26282c"
    win.set_theme("light")
    assert win.settings.theme == "light"


def test_week_numbers_at_year_boundaries():
    from datetime import date

    from photo_manager.ui.grid import week_number

    # US: week 1 is the week containing Jan 1 (2027-01-01 is a Friday).
    assert week_number(date(2026, 12, 27), "sunday") == (2027, 1)
    assert week_number(date(2026, 12, 20), "sunday") == (2026, 52)
    assert week_number(date(2026, 1, 4), "sunday") == (2026, 2)
    # ISO: 2026-12-28 (Monday) is week 53 of 2026; 2027-01-04 is week 1.
    assert week_number(date(2026, 12, 28), "monday") == (2026, 53)
    assert week_number(date(2027, 1, 4), "monday") == (2027, 1)


def test_scrolling_is_smooth_not_a_row_at_a_time(window):
    win, _, _ = window
    from PySide6.QtWidgets import QAbstractItemView

    assert win.grid.verticalScrollMode() == QAbstractItemView.ScrollMode.ScrollPerPixel
    win.grid.doItemsLayout()
    step = win.grid.verticalScrollBar().singleStep()
    row = win.settings.thumb_size + 38 + 16
    assert 10 <= step * 3 <= row // 2


def test_folder_tree_does_not_follow_open_folder(window, tmp_path):
    win, folder, _ = window
    other = tmp_path / "other"
    other.mkdir()
    before = win.tree.currentIndex()
    win.open_folder(str(other))
    assert win.tree.currentIndex() == before


def test_keyword_set_dialog_edits(qapp):
    from photo_manager.ui.dialogs import KeywordSetDialog

    dlg = KeywordSetDialog("Shayne", ["me", "josh", "queens"], ["Trips"])
    dlg.list.item(1).setText("Josh B")
    dlg.new_kw.setText("coney island, me")
    dlg._add_typed()
    dlg.list.setCurrentRow(0)
    dlg.list.item(0).setSelected(True)
    dlg._remove()
    dlg.name.setText("People")
    assert dlg.result_value() == ("People", ["Josh B", "queens", "coney island"])
    dlg.name.setText("trips")
    dlg._accept()
    assert "already" in dlg.error.text()


def test_edit_set_updates_buttons(window, monkeypatch):
    win, _, _ = window
    from photo_manager.ui import dialogs

    class FakeDialog:
        def __init__(self, *a, **k):
            pass

        def exec(self):
            return True

        def result_value(self):
            return "People", ["me", "josh"]

    monkeypatch.setattr(dialogs, "KeywordSetDialog", FakeDialog)
    win.sidebar.keywords._edit_set()
    assert win.settings.keyword_sets == {"People": ["me", "josh"]}
    assert win.settings.current_keyword_set == "People"
    assert sorted(win.sidebar.keywords.buttons) == ["josh", "me"]


def test_shift_p_preview_and_crop(window, monkeypatch):
    win, folder, et = window
    path = str(folder / "vacation.jpg")
    win.grid.select_paths([path], current=path)
    win.grid.setFocus()
    win.open_preview()
    assert win.previewing and win.preview.canvas.pixmap is not None
    # Arrow keys move through photos and the sidebar follows.
    win._preview_step(-1)
    assert win.grid.current_path() != path
    win._preview_step(1)
    assert win.grid.current_path() == path

    trashed = []
    monkeypatch.setattr("send2trash.send2trash", lambda p: trashed.append(p) or os.remove(p))
    win.preview.start_crop()
    assert win.preview.cropping
    win.preview.canvas.box = QRectF(10, 8, 30, 20)
    win.preview.as_copy.setChecked(False)
    win.preview.apply_crop()
    settle(win)
    from PIL import Image

    with Image.open(path) as im:
        assert im.size == (30, 20)
    assert trashed == [path]

    win.close_preview()
    assert not win.previewing


def test_aspect_ratio_crop_box(qapp):
    from PySide6.QtCore import QPointF

    from photo_manager.ui.preview import CropCanvas

    canvas = CropCanvas()
    canvas.resize(400, 300)
    canvas.full_size = (4000, 3000)
    canvas.ratio = 1.0
    box = canvas._constrain(QPointF(100, 100), QPointF(1100, 500))
    assert round(box.width()) == round(box.height()) == 1000
    # Never leaves the image.
    box = canvas._constrain(QPointF(3500, 2500), QPointF(4900, 3900))
    assert box.right() <= 4000 and box.bottom() <= 3000
    assert round(box.width()) == round(box.height())
