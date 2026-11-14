"""End-to-end: the real window, driven offscreen, with the stand-in ExifTool."""

import os
import time
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
    assert win.sidebar.rename.preview_rows() == [("IMG_20261023_000100_358_3.jpg", "10-23-2026 12-01-00 AM.jpg")]
    win.sidebar.rename.apply()
    settle(win)
    assert (folder / "10-23-2026 12-01-00 AM.jpg").exists()
    assert any(i.name == "10-23-2026 12-01-00 AM.jpg" for i in win.model.items)


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
    panel.pattern.setCurrentText("{YYYY}-{MM}-{DD} {name}")
    assert panel.preview_rows() == [("vacation.jpg", "2025-01-02 vacation.jpg")]
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


def test_template_dialog_opens_for_real(qapp):
    """Regression: the Edit… button crashed while building this dialog."""
    from photo_manager.core.settings import Settings
    from photo_manager.ui.dialogs import TemplateDialog

    dlg = TemplateDialog(Settings().templates, "%m-%d-%Y %I:%M:%S %p")
    assert dlg.table.rowCount() == len(Settings().templates)
    dlg.sample.setText("20261024084049_1.jpg")
    assert "10-24-2026 08:40:49 AM" in dlg.result_label.text()
    assert "Digits only" in dlg.result_label.text()


def test_digits_only_template_added_for_existing_users(tmp_path):
    import json

    from photo_manager.core.settings import Settings

    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"templates": [
        {"name": "Mine", "pattern": "DSC_{YYYY}{MM}{DD}", "utc": False},
        {"name": "Catch-all", "pattern": "*{YYYY}{MM}{DD}?{HH}{mm}{ss}", "utc": False},
    ]}))
    s = Settings.load(path)
    patterns = [t.pattern for t in s.templates]
    assert "{YYYY}{MM}{DD}{HH}{mm}{ss}" in patterns
    assert patterns.index("{YYYY}{MM}{DD}{HH}{mm}{ss}") < patterns.index("*{YYYY}{MM}{DD}?{HH}{mm}{ss}")
    s.save()
    # Deleting it later sticks: it isn't re-added on the next load.
    s.templates = [t for t in s.templates if t.pattern != "{YYYY}{MM}{DD}{HH}{mm}{ss}"]
    s.save()
    assert "{YYYY}{MM}{DD}{HH}{mm}{ss}" not in [t.pattern for t in Settings.load(path).templates]


def test_rename_presets_include_digits_only(window):
    win, folder, et = window
    panel = win.sidebar.rename
    presets = [panel.pattern.itemText(i) for i in range(panel.pattern.count())]
    assert "{YYYY}{MM}{DD}{HH}{mm}{ss}" in presets
    for name in ("vacation.jpg", "IMG_20261023_000100_358_3.jpg"):
        et.write(str(folder / name), ["-AllDates=2026:10:24 08:40:49"])
    win.open_folder(str(folder))
    settle(win)
    select(win, "vacation.jpg", "IMG_20261023_000100_358_3.jpg")
    panel.pattern.setCurrentText("{YYYY}{MM}{DD}{HH}{mm}{ss}")
    panel.apply()
    settle(win)
    # Two photos from the same second: the second one gets _1.
    assert (folder / "20261024084049.jpg").exists() and (folder / "20261024084049_1.jpg").exists()


def test_manual_rename(window, monkeypatch):
    win, folder, _ = window
    from photo_manager.core.fileops import check_new_name
    from photo_manager.ui import main_window
    from photo_manager.ui.dialogs import RenameDialog

    path = str(folder / "vacation.jpg")
    dlg = RenameDialog(path)
    assert dlg.edit.selectedText() == "vacation"
    assert check_new_name(path, "a:b.jpg").startswith("A file name can't contain")
    assert "already exists" in check_new_name(path, "Screenshot_20261023-143414.png")
    assert check_new_name(path, "Vacation.jpg") is None  # changing only the case is fine

    class FakeRename:
        def __init__(self, *a, **k):
            pass

        def exec(self):
            return True

        def new_name(self):
            return "beach day.jpg"

    monkeypatch.setattr(main_window, "RenameDialog", FakeRename)
    win.grid.select_paths([path], current=path)
    win.rename_current()
    settle(win)
    assert (folder / "beach day.jpg").exists()
    assert win.grid.selected_paths() == [str(folder / "beach day.jpg")]


def test_copy_files_to_clipboard(window):
    win, folder, _ = window
    select(win, "vacation.jpg")
    win.copy_files()
    urls = QApplication.clipboard().mimeData().urls()
    # Qt may use forward slashes on Windows; it's the same file.
    assert [os.path.normcase(os.path.normpath(u.toLocalFile())) for u in urls] == [
        os.path.normcase(str(folder / "vacation.jpg"))]
    # Don't leave a file list on the Windows clipboard when the test process exits.
    QApplication.clipboard().clear()
    QApplication.processEvents()


def test_collapsible_groups(window):
    win, folder, et = window
    select(win, "vacation.jpg")
    win._label_shortcut("Red")
    settle(win)
    win.set_group("label")
    red = str(folder / "vacation.jpg")
    win.grid.toggle_group("Red")
    assert win.grid.isRowHidden(win.model.row_of(red))
    assert red not in win.grid.selected_paths()  # hidden photos are deselected
    win.grid.selectAll()
    assert red not in win.grid.selected_paths()  # Ctrl+A skips collapsed groups
    others = [i for i in win.model.items if i.path != red]
    assert win.model.neighbour(others[0].path, 1) is others[1]
    # Survives regrouping (e.g. after metadata loads).
    win.regroup()
    assert win.grid.isRowHidden(win.model.row_of(red))
    win.grid.set_all_groups(False)
    assert not win.grid.isRowHidden(win.model.row_of(red))


def test_keyword_buttons_are_equal_size_boxes(window):
    win, _, _ = window
    panel = win.sidebar.keywords
    win.resize(1400, 900)
    QApplication.processEvents()
    assert isinstance(panel.grid, type(panel.grid)) and panel.grid.__class__.__name__ == "QGridLayout"
    widths = {b.width() for b in panel.buttons.values()}
    assert max(widths) - min(widths) <= 1  # every box the same width (±1px rounding)
    me = panel.grid.getItemPosition(panel.grid.indexOf(panel.buttons["me"]))[:2]
    new_york = panel.grid.getItemPosition(panel.grid.indexOf(panel.buttons["new york"]))[:2]
    assert me == (0, 0) and new_york == (1, 0)  # 2 per row (narrow panel), in set order


def test_rename_default_is_us_format(window, tmp_path):
    import json

    from photo_manager.core.settings import Settings

    win, folder, et = window
    assert win.sidebar.rename.pattern.currentText() == "{MM}-{DD}-{YYYY} {hh}-{mm}-{ss} {AMPM}"
    et.write(str(folder / "vacation.jpg"), ["-AllDates=2026:08:15 11:42:44"])
    win.open_folder(str(folder))
    settle(win)
    select(win, "vacation.jpg")
    win.sidebar.rename.apply()
    settle(win)
    assert (folder / "08-15-2026 11-42-44 AM.jpg").exists()
    # ...and reading the date back from such a name works.
    from photo_manager.core.templates import DEFAULT_TEMPLATES, match_any

    assert match_any(DEFAULT_TEMPLATES, "08-15-2026 11-42-44 PM_1.jpg")[1] == datetime(2026, 8, 15, 23, 42, 44)

    # Existing settings with the old default pattern switch over once.
    path = tmp_path / "old.json"
    path.write_text(json.dumps({"rename_pattern": "{YYYY}-{MM}-{DD}_{HH}-{mm}-{ss}"}))
    s = Settings.load(path)
    assert s.rename_pattern == "{MM}-{DD}-{YYYY} {hh}-{mm}-{ss} {AMPM}"
    assert s.rename_presets[0] == s.rename_pattern
    s.rename_pattern = "{YYYY}-{MM}-{DD}_{HH}-{mm}-{ss}"  # choosing the old one again later sticks
    s.save()
    assert Settings.load(path).rename_pattern == "{YYYY}-{MM}-{DD}_{HH}-{mm}-{ss}"


def test_misnamed_files_are_flagged_and_selectable(window):
    win, folder, et = window
    # None of the sample files follow "08-15-2026 11-42-44 AM".
    assert len(win.misnamed_paths()) == 3
    assert "not in rename format" in win.status.text()
    item = win.model.item(str(folder / "vacation.jpg"))
    assert win.grid.delegate.is_misnamed(item)
    win.select_misnamed()
    assert len(win.grid.selected_paths()) == 3
    # Rename one into the format; it stops being flagged.
    et.write(str(folder / "vacation.jpg"), ["-AllDates=2026:08:15 11:42:44"])
    win.open_folder(str(folder))
    settle(win)
    select(win, "vacation.jpg")
    win.sidebar.rename.apply()
    settle(win)
    assert len(win.misnamed_paths()) == 2
    # Turning the highlight off clears it.
    win._toggle_misnamed(False)
    assert win.misnamed_paths() == [] and "not in rename format" not in win.status.text()


def test_type_badges_labels():
    from photo_manager.ui.grid import type_label

    assert [type_label(p) for p in ("a.jpeg", "b.HEIF", "c.webp", "d.mp4", "e.tiff")] == [
        "JPG", "HEIC", "WEBP", "MP4", "TIF"]


def test_rename_preview_lists_every_file_with_final_names(window):
    win, folder, et = window
    for name in ("vacation.jpg", "IMG_20261023_000100_358_3.jpg"):
        et.write(str(folder / name), ["-AllDates=2026:08:15 11:42:44"])
    win.open_folder(str(folder))
    settle(win)
    select(win, "vacation.jpg", "IMG_20261023_000100_358_3.jpg", "Screenshot_20261023-143414.png")
    rows = dict(win.sidebar.rename.preview_rows())
    assert sorted([rows["vacation.jpg"], rows["IMG_20261023_000100_358_3.jpg"]]) == [
        "08-15-2026 11-42-44 AM.jpg", "08-15-2026 11-42-44 AM_1.jpg"]
    assert rows["Screenshot_20261023-143414.png"] == "no date — skipped"
    assert win.sidebar.rename.button.text() == "Rename 2 files"


def test_convert_from_the_window(window, monkeypatch):
    win, folder, _ = window
    from photo_manager.ui import main_window

    class FakeConvert:
        def __init__(self, paths, settings, parent=None):
            self.paths = paths
            settings.convert_target, settings.convert_recycle = "JPG", False

        def exec(self):
            return True

        def to_convert(self):
            return [p for p in self.paths if p.endswith(".png")]

    monkeypatch.setattr(main_window, "ConvertDialog", FakeConvert)
    select(win, "Screenshot_20261023-143414.png", "vacation.jpg")
    win.convert_selected()
    settle(win)
    new = folder / "Screenshot_20261023-143414.jpg"
    assert new.exists() and (folder / "Screenshot_20261023-143414.png").exists()
    assert win.grid.selected_paths() == [str(new)]
    assert win.model.item(str(new)) is not None


def test_convert_dialog_counts(qapp, tmp_path):
    from photo_manager.core.settings import Settings
    from photo_manager.ui.dialogs import ConvertDialog

    s = Settings()
    dlg = ConvertDialog(["a.heic", "b.webp", "c.jpg", "d.mp4"], s)
    assert dlg.to_convert() == ["a.heic", "b.webp"]
    assert dlg.ok.text() == "Convert 2"
    dlg.target.setCurrentText("PNG")
    assert dlg.to_convert() == ["a.heic", "b.webp", "c.jpg"]
    assert not dlg.quality.isEnabled()


def _drop_event(widget, pos, paths, ctrl=False):
    from PySide6.QtCore import QMimeData, QPointF, QUrl
    from PySide6.QtGui import QDropEvent

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    mods = Qt.KeyboardModifier.ControlModifier if ctrl else Qt.KeyboardModifier.NoModifier
    return QDropEvent(QPointF(pos), Qt.DropAction.MoveAction | Qt.DropAction.CopyAction, mime,
                      Qt.MouseButton.LeftButton, mods), mime


def test_drop_photos_on_a_favorite_moves_them(window, tmp_path):
    win, folder, _ = window
    dest = tmp_path / "Keepers"
    dest.mkdir()
    win.toggle_favorite(str(dest))
    QApplication.processEvents()
    item = win.favorites.item(0)
    pos = win.favorites.visualItemRect(item).center()
    got = []
    win.favorites.files_dropped.connect(lambda paths, f, copy: got.append((paths, f, copy)))
    event, _mime = _drop_event(win.favorites, pos, [folder / "vacation.jpg"])
    win.favorites.dropEvent(event)
    assert got and got[0][1] == str(dest) and got[0][2] is False
    settle(win)
    assert (dest / "vacation.jpg").exists() and not (folder / "vacation.jpg").exists()
    assert win.model.item(str(folder / "vacation.jpg")) is None

    # Ctrl+drop copies.
    event, _mime = _drop_event(win.favorites, pos, [folder / "Screenshot_20261023-143414.png"], ctrl=True)
    win.favorites.dropEvent(event)
    settle(win)
    assert (dest / "Screenshot_20261023-143414.png").exists()
    assert (folder / "Screenshot_20261023-143414.png").exists()


def test_drop_on_folder_tree_moves(window, tmp_path):
    win, folder, _ = window
    from photo_manager.ui.folders import FolderTree

    dest = tmp_path / "Sorted"
    dest.mkdir()
    tree = win.tree
    assert isinstance(tree, FolderTree)
    tree.folder_at = lambda pos: str(dest)  # the real tree loads drives asynchronously
    event, _mime = _drop_event(tree, tree.rect().center(), [folder / "vacation.jpg"])
    tree.dropEvent(event)
    settle(win)
    assert (dest / "vacation.jpg").exists()


def test_grid_items_are_draggable(window):
    win, folder, _ = window
    row = win.model.row_of(str(folder / "vacation.jpg"))
    assert win.model.flags(win.model.index(row)) & Qt.ItemFlag.ItemIsDragEnabled


def test_star_and_bookmark_toggle_independently_of_color(window):
    win, folder, et = window
    select(win, "vacation.jpg")
    win._label_shortcut("Red")
    settle(win)
    win._flag_shortcut("Star")
    settle(win)
    win._flag_shortcut("Bookmark")
    settle(win)
    meta = meta_of(et, folder / "vacation.jpg")
    assert meta.label == "Red" and meta.starred and meta.bookmarked
    assert win.sidebar.labels.flag_buttons["Star"].isChecked()
    win._flag_shortcut("Star")  # again -> off
    settle(win)
    meta = meta_of(et, folder / "vacation.jpg")
    assert not meta.starred and meta.bookmarked and meta.label == "Red"
    assert win.sidebar.sections["labels"].header.text() == "Labels"


def test_label_hotkeys_are_configurable(window, monkeypatch):
    win, _, _ = window
    from photo_manager.ui import main_window

    keys = {s.key().toString() for s in win.label_shortcuts}
    assert {"Ctrl+1", "Ctrl+0", "Ctrl+S", "Ctrl+B"} <= keys

    class FakeHotkeys:
        def __init__(self, *a, **k):
            pass

        def exec(self):
            return True

        def hotkeys(self):
            return {"Red": "R", "Star": "Ctrl+8", "Bookmark": ""}

    monkeypatch.setattr(main_window, "HotkeyDialog", FakeHotkeys)
    win.edit_label_hotkeys()
    keys = {s.key().toString() for s in win.label_shortcuts}
    assert keys == {"R", "Ctrl+8"}
    assert "(Ctrl+8)" in win.sidebar.labels.flag_buttons["Star"].toolTip()


def test_hotkey_dialog_rejects_clashes(qapp):
    from PySide6.QtGui import QKeySequence

    from photo_manager.core.settings import DEFAULT_LABEL_HOTKEYS
    from photo_manager.ui.dialogs import HotkeyDialog

    dlg = HotkeyDialog(DEFAULT_LABEL_HOTKEYS, DEFAULT_LABEL_HOTKEYS, {"Ctrl+M": "Move to"})
    dlg.edits["Star"].setKeySequence(QKeySequence("Ctrl+1"))
    dlg._accept()
    assert "both" in dlg.error.text()
    dlg.edits["Star"].setKeySequence(QKeySequence("Ctrl+M"))
    dlg._accept()
    assert "Move to" in dlg.error.text()
    dlg._defaults()
    assert dlg.hotkeys() == DEFAULT_LABEL_HOTKEYS


def test_old_settings_get_new_label_hotkeys(tmp_path):
    import json

    from photo_manager.core.settings import Settings

    path = tmp_path / "s.json"
    path.write_text(json.dumps({"label_hotkeys": {"Red": "F6"}}))
    s = Settings.load(path)
    assert s.label_hotkeys["Red"] == "F6" and s.label_hotkeys["Star"] == "Ctrl+S"


def test_none_clears_color_star_and_bookmark(window):
    win, folder, et = window
    select(win, "vacation.jpg")
    win._label_shortcut("Green")
    settle(win)
    win._flag_shortcut("Star")
    settle(win)
    win._flag_shortcut("Bookmark")
    settle(win)
    win._clear_labels_shortcut()
    settle(win)
    meta = meta_of(et, folder / "vacation.jpg")
    assert meta.label == "" and not meta.starred and not meta.bookmarked
    # None sits after the icons on the same row.
    panel = win.sidebar.labels
    QApplication.processEvents()
    # Same row: vertical centres line up (buttons differ in height by a few pixels).
    assert abs(panel.clear.geometry().center().y() - panel.buttons["Red"].geometry().center().y()) <= 3
    assert panel.clear.x() > panel.flag_buttons["Bookmark"].x() > panel.buttons["Purple"].x()


def test_dragging_a_photo_starts_a_drag_not_a_box_selection(window, monkeypatch):
    """Regression: setMovement(Static) silently disabled dragging, so a drag became
    a rubber-band selection."""
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication as App

    win, folder, _ = window
    grid = win.grid
    assert grid.dragEnabled()
    path = str(folder / "vacation.jpg")
    grid.select_paths([path], current=path)
    started = []
    monkeypatch.setattr(type(grid), "startDrag", lambda self, actions: started.append(self.selected_paths()))
    rect = grid.visualRect(win.model.index(win.model.row_of(path)))
    start = rect.center()
    QTest.mousePress(grid.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    for step in range(1, 6):
        QTest.mouseMove(grid.viewport(), start + QPoint(step * (App.startDragDistance() + 5), 0))
    QTest.mouseRelease(grid.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                       start + QPoint(80, 0))
    assert started == [[path]]


def test_preview_shows_type_badge_and_labels(window):
    win, folder, _ = window
    path = str(folder / "vacation.jpg")
    win.grid.select_paths([path], current=path)
    win.open_preview()
    canvas = win.preview.canvas
    assert canvas.mark_path == path and canvas.show_type
    assert canvas.mark_meta is None or not canvas.mark_meta.starred
    # Pressing label hotkeys while previewing updates the marks straight away.
    win._flag_shortcut("Star")
    settle(win)
    win._label_shortcut("Purple")
    settle(win)
    assert canvas.mark_meta.starred and canvas.mark_meta.label == "Purple"
    assert "Purple" in win.preview.caption.text()
    canvas.resize(400, 300)
    canvas.grab()  # paints without errors
    win._toggle_badges(False)
    assert not canvas.show_type
    win.close_preview()


@pytest.fixture
def five_photos(window):
    win, folder, et = window
    for n in range(2):
        Image.new("RGB", (64, 48), "red").save(folder / f"extra{n}.jpg")
    win.open_folder(str(folder))
    settle(win)
    return win, folder, et


def _pane_positions(win):
    grid = win.preview.compare_grid
    return [grid.getItemPosition(grid.indexOf(p))[:2] for p in win.preview.panes]


@pytest.mark.parametrize("count,positions", [
    (2, [(0, 0), (0, 1)]),
    (3, [(0, 0), (0, 1), (0, 2)]),
    (4, [(0, 0), (0, 1), (1, 0), (1, 1)]),
])
def test_compare_layouts(five_photos, count, positions):
    win, _, _ = five_photos
    paths = [i.path for i in win.model.items[:count]]
    win.grid.select_paths(paths)
    win.open_preview()
    assert win.comparing and win.preview.comparing
    assert [p.path for p in win.preview.panes] == paths
    assert _pane_positions(win) == positions
    assert not win.preview.crop_btn.isEnabled()
    win.close_preview()
    assert sorted(win.grid.selected_paths()) == sorted(paths)  # selection given back


def test_compare_more_than_four_uses_first_four(five_photos):
    win, _, _ = five_photos
    win.grid.select_paths([i.path for i in win.model.items])
    win.open_preview()
    assert len(win.preview.panes) == 4
    assert "first 4 of 5" in win.status.text()
    win.close_preview()


def test_compare_labels_apply_to_the_clicked_photo_only(five_photos):
    win, folder, et = five_photos
    a, b, c = [i.path for i in win.model.items[:3]]
    win.grid.select_paths([a, b, c])
    win.open_preview()
    assert win.preview.path == a and win.preview.panes[0].active
    win.preview.panes[1].clicked.emit(b)  # click the second photo
    assert win.preview.path == b and win.preview.panes[1].active and not win.preview.panes[0].active
    assert win.grid.selected_paths() == [b]  # sidebar / hotkeys now act on b
    win._flag_shortcut("Star")
    settle(win)
    win._label_shortcut("Yellow")
    settle(win)
    assert meta_of(et, b).starred and meta_of(et, b).label == "Yellow"
    assert not meta_of(et, a).starred and not meta_of(et, c).starred
    pane_b = win.preview.panes[1]
    assert pane_b.canvas.mark_meta.starred  # marks on that pane updated
    # Arrow keys move the active photo, wrapping around.
    win.preview._step_active(1)
    assert win.preview.path == c
    win.preview._step_active(1)
    assert win.preview.path == a
    win.close_preview()


def test_compare_delete_removes_active_and_closes_up(five_photos, monkeypatch):
    win, folder, _ = five_photos
    monkeypatch.setattr("photo_manager.core.fileops.send2trash", lambda p: os.remove(p))
    win.settings.confirm_delete = False
    a, b, c = [i.path for i in win.model.items[:3]]
    win.grid.select_paths([a, b, c])
    win.open_preview()
    win.preview._step_active(1)
    win._preview_delete()
    settle(win)
    assert not os.path.exists(b)
    assert [p.path for p in win.preview.panes] == [a, c] and win.comparing
    win.preview.set_active(a)
    win.grid.select_paths([a], current=a)
    win._preview_delete()
    settle(win)
    assert not win.comparing and win.previewing  # one left: normal preview
    assert win.preview.path == c
    win.close_preview()


def test_switching_compare_sets_leaves_no_old_panes(five_photos):
    win, _, _ = five_photos
    width = win.width()
    win.grid.select_paths([i.path for i in win.model.items[:4]])
    win.open_preview()
    win.close_preview()
    win.grid.select_paths([i.path for i in win.model.items[2:5]])
    win.open_preview()
    QApplication.processEvents()
    panes = [w for w in win.preview.compare_host.findChildren(type(win.preview.panes[0])) if w.isVisible()]
    assert len(panes) == 3 and sum(p.active for p in panes) == 1
    assert win.width() == width  # long captions don't push the window wider
    win.close_preview()


def _make_video(path):
    import shutil
    import subprocess

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("needs ffmpeg to make a test video")
    subprocess.run([ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=10",
                    "-f", "lavfi", "-i", "sine=frequency=440", "-t", "1", "-pix_fmt", "yuv420p",
                    "-shortest", str(path)], check=True, timeout=60)


def test_video_plays_in_preview_muted_with_remembered_autoplay(window):
    win, folder, _ = window
    if not win.preview.video.available:
        pytest.skip("Qt multimedia not available")
    clip, clip2 = folder / "clip.mp4", folder / "clip2.mp4"
    _make_video(clip)
    _make_video(clip2)
    win.open_folder(str(folder))
    settle(win)
    video = win.preview.video

    # Auto-play off (default): loads paused, muted.
    win.grid.select_paths([str(clip)], current=str(clip))
    win.open_preview()
    assert win.preview.showing_video and video.path == str(clip)
    assert video.is_muted() and not video.is_playing()
    assert not win.preview.crop_btn.isEnabled()

    # Unmute, then go to the next video: it starts muted again.
    video.toggle_mute()
    assert not video.is_muted()
    video.autoplay.setChecked(True)
    assert win.settings.video_autoplay is True  # remembered
    win.grid.select_paths([str(clip2)], current=str(clip2))
    win._preview_show_current()
    assert video.path == str(clip2) and video.is_muted()

    # Space toggles play/pause; M toggles sound.
    from PySide6.QtTest import QTest

    QTest.keyClick(win.preview, Qt.Key.Key_M)
    assert not video.is_muted()
    # Leaving the preview stops playback and releases the file.
    win.close_preview()
    assert video.path == "" and not video.is_playing()


def test_video_is_released_before_its_labels_are_written(window):
    win, folder, et = window
    if not win.preview.video.available:
        pytest.skip("Qt multimedia not available")
    clip = folder / "clip.mp4"
    _make_video(clip)
    win.open_folder(str(folder))
    settle(win)
    win.grid.select_paths([str(clip)], current=str(clip))
    win.open_preview()
    released = []
    original = win.preview.stop_video
    win.preview.stop_video = lambda: (released.append(True), original())
    win._flag_shortcut("Star")
    settle(win)
    assert released  # stopped before writing
    assert meta_of(et, clip).starred
    assert win.preview.showing_video  # and shown again afterwards
    win.close_preview()


def test_closing_waits_for_thumbnail_threads(qapp, tmp_path):
    """Regression: closing while thumbnails were still loading could abort the app on exit."""
    folder = tmp_path / "many"
    folder.mkdir()
    for n in range(60):
        Image.new("RGB", (1600, 1200), (n * 4 % 255, 80, 120)).save(folder / f"p{n:02d}.jpg", quality=95)
    settings = Settings.load(tmp_path / "s.json")
    settings.last_folder = str(folder)
    win = MainWindow(settings, ExifTool(FAKE_EXIFTOOL))
    win.show()
    QApplication.processEvents()
    for item in win.model.items:  # queue every thumbnail at once
        win.model._request_thumb(item)
    win.close()  # straight away, while they're loading
    assert win.model._pool.activeThreadCount() == 0


def test_video_preview_shows_thumbnail_and_marks_before_playing(window):
    win, folder, _ = window
    if not win.preview.video.available:
        pytest.skip("Qt multimedia not available")
    clip = folder / "clip.mp4"
    _make_video(clip)
    win.open_folder(str(folder))
    settle(win)
    win.grid.select_paths([str(clip)], current=str(clip))
    win.open_preview()
    screen = win.preview.video.video
    assert not screen.poster.isNull()  # a still frame instead of a black box
    assert not screen.picture_rect().isEmpty()
    win._label_shortcut("Blue")
    settle(win)
    path, kind, meta, show_type = screen.marks
    assert path == str(clip) and kind == "video" and show_type and meta.label == "Blue"
    image = screen.grab().toImage()
    center = image.pixelColor(image.width() // 2, image.height() // 2)
    assert (center.red(), center.green(), center.blue()) != (0, 0, 0)  # not black
    win.close_preview()


def test_move_while_previewing_shows_the_next_photo(window, tmp_path, monkeypatch):
    """Regression: Move to… in the big preview moved the file but kept showing it."""
    win, folder, _ = window
    from photo_manager.ui import main_window

    dest = tmp_path / "dest"
    dest.mkdir()

    class FakeMove:
        def __init__(self, *a, **k):
            self.folder = str(dest)

        def exec(self):
            return True

    monkeypatch.setattr(main_window, "MoveDialog", FakeMove)
    path = str(folder / "IMG_20261023_000100_358_3.jpg")
    win.grid.select_paths([path], current=path)
    win.open_preview()
    win.move_selected()
    settle(win)
    assert (dest / "IMG_20261023_000100_358_3.jpg").exists() and not os.path.exists(path)
    assert win.previewing and win.preview.path != path
    assert os.path.exists(win.preview.path)
    assert win.grid.current_path() == win.preview.path  # sidebar/labels follow the shown photo


def test_rename_while_previewing_keeps_showing_it(window, monkeypatch):
    win, folder, _ = window
    from photo_manager.ui import main_window

    class FakeRename:
        def __init__(self, *a, **k):
            pass

        def exec(self):
            return True

        def new_name(self):
            return "renamed.jpg"

    monkeypatch.setattr(main_window, "RenameDialog", FakeRename)
    path = str(folder / "vacation.jpg")
    win.grid.select_paths([path], current=path)
    win.open_preview()
    win.rename_current()
    settle(win)
    assert win.preview.path == str(folder / "renamed.jpg")
    assert "renamed.jpg" in win.preview.caption.text()


def test_move_in_preview_acts_on_the_shown_photo_even_if_nothing_is_selected(window, tmp_path, monkeypatch):
    """Regression: Move to… used the hidden grid's selection; with nothing selected it did nothing."""
    win, folder, _ = window
    from photo_manager.ui import main_window

    dest = tmp_path / "dest"
    dest.mkdir()

    class FakeMove:
        def __init__(self, *a, **k):
            self.folder = str(dest)

        def exec(self):
            return True

    monkeypatch.setattr(main_window, "MoveDialog", FakeMove)
    path = str(folder / "vacation.jpg")
    win.grid.select_paths([path], current=path)
    win.open_preview()
    win.grid.selectionModel().clearSelection()  # e.g. after clicking around
    assert win.grid.selected_paths() == []
    win.move_selected()
    settle(win)
    assert (dest / "vacation.jpg").exists() and not os.path.exists(path)
    assert win.model.item(path) is None  # gone from the grid too
    win.close_preview()
    assert path not in [i.path for i in win.model.items]


def test_group_by_label_includes_star_and_bookmark(window):
    win, folder, _ = window
    select(win, "vacation.jpg")
    win._label_shortcut("Red")
    settle(win)
    win._flag_shortcut("Star")
    settle(win)
    select(win, "Screenshot_20261023-143414.png")
    win._flag_shortcut("Bookmark")
    settle(win)
    win.set_group("label")
    assert headers(win) == ["Red  ⭐", "🔖", "No label"]
    assert win.group_combo.currentText() == "Label"


def test_group_by_file_type(window):
    win, _, _ = window
    win.set_group("type")
    assert headers(win) == ["JPG", "PNG"]


def _names(win):
    return sorted(i.name for i in win.model.items)


def test_filter_by_type_label_rename_and_keywords(window):
    win, folder, et = window
    select(win, "vacation.jpg")
    win._flag_shortcut("Star")
    settle(win)
    win.sidebar.keywords.buttons["josh"].click()
    settle(win)

    win.filters["types"] = {"PNG"}
    win.apply_filter()
    assert _names(win) == ["Screenshot_20261023-143414.png"]
    assert "1 of 3 shown" in win.status.text() and win.filter_btn.text() == "Filter (1)"

    win.clear_filter()
    win.filters["labels"] = {"Star"}
    win.apply_filter()
    assert _names(win) == ["vacation.jpg"]

    win.clear_filter()
    win.filters["no_keywords"] = True
    win.apply_filter()
    assert "vacation.jpg" not in _names(win) and len(_names(win)) == 2

    # Across headings the conditions combine (AND): JPGs that have no keywords.
    win.filters["types"] = {"JPG"}
    win.apply_filter()
    assert _names(win) == ["IMG_20261023_000100_358_3.jpg"]

    win.clear_filter()
    assert len(win.model.items) == 3 and win.filter_btn.text() == "Filter"


def test_filter_needs_rename_and_menu(window):
    win, folder, et = window
    et.write(str(folder / "vacation.jpg"), ["-AllDates=2026:08:15 11:42:44"])
    win.open_folder(str(folder))
    settle(win)
    select(win, "vacation.jpg")
    win.sidebar.rename.apply()
    settle(win)
    win.filters["needs_rename"] = True
    win.apply_filter()
    assert "08-15-2026 11-42-44 AM.jpg" not in _names(win) and len(_names(win)) == 2
    # The menu lists the file types present and shows what's ticked.
    win._fill_filter_menu()
    texts = {a.text(): a.isChecked() for a in win.filter_menu.actions() if a.isCheckable()}
    assert texts["Needs rename"] is True and texts["JPG"] is False and "PNG" in texts
    assert "⭐ Starred" in texts and "No keywords" in texts


def test_filtered_out_photos_still_get_their_labels_updated(window):
    win, folder, et = window
    win.filters["types"] = {"PNG"}
    win.apply_filter()
    hidden = win.model.item(str(folder / "vacation.jpg"))
    assert hidden is not None and win.model.row_of(hidden.path) == -1
    win.model.set_meta({hidden.path: parse_meta({"XMP:Label": "Green"})})
    assert hidden.meta.label == "Green"
    win.clear_filter()


def test_video_thumbnail_shows_its_length(window):
    import json

    win, folder, _ = window
    clip = folder / "clip.mp4"
    clip.write_bytes(b"not really a video")
    (folder / "clip.mp4.fake.json").write_text(json.dumps({"QuickTime:Duration": 125.0}))
    win.open_folder(str(folder))
    settle(win)
    item = win.model.item(str(clip))
    assert item.meta.duration == 125.0
    win.grid.viewport().repaint()  # paints the "2:05" chip without errors


def test_results_arriving_after_close_are_dropped(qapp, tmp_path, capsys):
    """Regression: a metadata read finishing just after the window closed called into it."""
    folder = tmp_path / "pics"
    folder.mkdir()
    for n in range(30):
        Image.new("RGB", (64, 48), "red").save(folder / f"p{n}.jpg")
    settings = Settings.load(tmp_path / "s.json")
    settings.last_folder = str(folder)
    win = MainWindow(settings, ExifTool(FAKE_EXIFTOOL))
    win.show()
    QApplication.processEvents()  # starts the metadata reads
    win.close()
    win.deleteLater()
    from PySide6.QtCore import QEvent

    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QApplication.processEvents()
    assert "already deleted" not in capsys.readouterr().err


def test_label_set_just_before_closing_is_still_saved(window):
    win, folder, et = window
    select(win, "vacation.jpg")
    win._label_shortcut("Purple")  # queued...
    win.close()                    # ...and the window closes straight away
    assert meta_of(et, folder / "vacation.jpg").label == "Purple"


def test_existing_users_get_the_number_date_template(tmp_path):
    import json

    from photo_manager.core.settings import Settings

    path = tmp_path / "s.json"
    known = ["PXL_{YYYY}{MM}{DD}_{HH}{mm}{ss}{fff}", "{YYYY}{MM}{DD}{HH}{mm}{ss}"]
    path.write_text(json.dumps({
        "known_default_templates": known,
        "templates": [
            {"name": "Digits", "pattern": "{YYYY}{MM}{DD}{HH}{mm}{ss}", "utc": False},
            {"name": "Catch-all", "pattern": "*{YYYY}{MM}{DD}?{HH}{mm}{ss}", "utc": False},
        ]}))
    patterns = [t.pattern for t in Settings.load(path).templates]
    assert "*_{YYYY}{MM}{DD}{HH}{mm}{ss}" in patterns
    assert patterns.index("*_{YYYY}{MM}{DD}{HH}{mm}{ss}") < patterns.index("*{YYYY}{MM}{DD}?{HH}{mm}{ss}")


def test_import_steam_screenshots_end_to_end(window, tmp_path, monkeypatch):
    from photo_manager.ui import main_window
    from photo_manager.ui.dialogs import SteamImportDialog

    from .test_steam import make_steam

    win, folder, et = window
    steam_root = make_steam(tmp_path / "steamhome")
    dest = tmp_path / "SteamShots"

    # The dialog finds the account and counts what's new.
    win.settings.steam_path = str(steam_root)
    dlg = SteamImportDialog(win.settings)
    dlg.dest.setText(str(dest))
    assert dlg.account.currentData() == "12345"
    assert "3 screenshots from 2 games" in dlg.summary.text() and "3 new" in dlg.summary.text()
    assert dlg.ok.text() == "Import 3"
    dlg.keyword.setChecked(True)
    dlg._accept()

    class Accepting(SteamImportDialog):
        def exec(self):
            return True

    monkeypatch.setattr(main_window, "SteamImportDialog", Accepting)
    win.quiet_steam_import = True
    win.import_steam()
    settle(win)
    done, failures = win.steam_import_result
    assert len(done) == 3 and not failures
    assert all(p.is_file() for p in dest.iterdir())  # straight into the folder, no subfolders
    shot = dest / "20261104213012_1.jpg"
    meta = meta_of(et, shot)
    assert meta.date_taken == datetime(2026, 11, 4, 21, 30, 12)
    assert meta.file_created == datetime(2026, 11, 4, 21, 30, 12)
    assert meta.keywords == ["Team Fortress 2"]

    # Running it again finds nothing new.
    for f in dest.iterdir():  # real ExifTool rewrites the file when it saves the date: size changes
        if f.suffix.lower() in (".jpg", ".png"):
            f.write_bytes(f.read_bytes() + b"date written")
    again = SteamImportDialog(win.settings)
    assert again.plan == [] and not again.ok.isEnabled()
    assert "imported before" in again.summary.text()
    assert again.dest.text() == str(dest)  # the folder is remembered


def test_steam_dialog_lists_games_and_remembers_extra_folders(qapp, tmp_path):
    from photo_manager.core.settings import Settings
    from photo_manager.ui.dialogs import SteamImportDialog

    from .test_steam import make_steam

    root = make_steam(tmp_path / "home")
    extra = tmp_path / "Uncompressed" / "Hades"
    extra.mkdir(parents=True)
    (extra / "20261107091500_1.png").write_bytes(b"z" * 20)
    s = Settings.load(tmp_path / "s.json")
    s.steam_path, s.steam_dest = str(root), str(tmp_path / "out")
    dlg = SteamImportDialog(s)
    games = [dlg.games.topLevelItem(i).text(0) for i in range(dlg.games.topLevelItemCount())]
    assert games == ["Team Fortress 2", "App 999999"]  # newest first
    dlg.extra.addItem(str(tmp_path / "Uncompressed"))
    dlg._update()
    games = [dlg.games.topLevelItem(i).text(0) for i in range(dlg.games.topLevelItemCount())]
    assert games[0] == "Hades" and "4 new" in dlg.summary.text()
    dlg._accept()
    assert s.steam_extra_folders == [str(tmp_path / "Uncompressed")]
    again = SteamImportDialog(s)
    assert again.extra_folders() == [str(tmp_path / "Uncompressed")]


def test_steam_dialog_names_uninstalled_games_from_the_store(qapp, tmp_path, monkeypatch):
    from photo_manager.core import steam
    from photo_manager.core.settings import Settings
    from photo_manager.ui.dialogs import SteamImportDialog

    deck = tmp_path / "Deck" / "1234567" / "screenshots"
    deck.mkdir(parents=True)
    (deck / "20261107085800_1.jpg").write_bytes(b"k" * 10)
    asked = []

    def fake_fetch(app_ids, timeout=5.0):
        asked.append(list(app_ids))
        return {"1234567": "Hello Kitty Island Adventure"}

    monkeypatch.setattr(steam, "fetch_store_names", fake_fetch)
    s = Settings.load(tmp_path / "s.json")
    s.steam_path, s.steam_dest = "", str(tmp_path / "out")
    s.steam_extra_folders = [str(tmp_path / "Deck")]
    dlg = SteamImportDialog(s)
    deadline = time.time() + 5
    while dlg.games.topLevelItemCount() and dlg.games.topLevelItem(0).text(0).startswith("App ") \
            and time.time() < deadline:
        qapp.processEvents()
    assert dlg.games.topLevelItem(0).text(0) == "Hello Kitty Island Adventure"
    assert dlg.plan[0][0].game == "Hello Kitty Island Adventure"
    assert Settings.load(tmp_path / "s.json").steam_game_names == {"1234567": "Hello Kitty Island Adventure"}
    SteamImportDialog(s)
    assert asked == [["1234567"]]  # cached: not asked again


def test_folder_updates_itself_when_files_are_added_or_removed(window, qapp):
    win, folder, _ = window
    win.grid.select_paths([str(folder / "vacation.jpg")])
    Image.new("RGB", (64, 48), "red").save(folder / "new from phone.jpg")
    (folder / "Screenshot_20261023-143414.png").unlink()
    deadline = time.time() + 10
    names = set()
    while time.time() < deadline:
        qapp.processEvents()
        names = {i.name for i in win.model.all_items}
        if "new from phone.jpg" in names and "Screenshot_20261023-143414.png" not in names:
            break
        time.sleep(0.05)
    assert names == {"IMG_20261023_000100_358_3.jpg", "vacation.jpg", "new from phone.jpg"}
    assert win.grid.selected_paths() == [str(folder / "vacation.jpg")]  # selection kept
    settle(win)
    assert win.model.item(str(folder / "new from phone.jpg")).meta is not None  # its metadata was read


def test_steam_import_is_on_the_toolbar(window):
    win, _, _ = window
    from PySide6.QtWidgets import QToolBar

    bar = win.findChild(QToolBar, "main-toolbar")
    assert "Steam import…" in [a.text() for a in bar.actions()]


def test_steam_mark_older_ones_as_imported(qapp, tmp_path, monkeypatch):
    """Imported earlier and moved elsewhere: mark everything before a cut-off as imported."""
    from datetime import datetime

    from PySide6.QtCore import QDateTime
    from PySide6.QtWidgets import QDateTimeEdit, QDialog, QLabel

    from photo_manager.core.settings import Settings
    from photo_manager.ui.dialogs import SteamImportDialog

    from .test_steam import make_steam

    root = make_steam(tmp_path / "home")  # screenshots from 01-01-2026, 11-04-2026 9:30:12 PM and 9:30:15 PM
    s = Settings.load(tmp_path / "s.json")
    s.steam_path, s.steam_dest = str(root), str(tmp_path / "Camera Roll")
    dlg = SteamImportDialog(s)
    assert len(dlg.plan) == 3

    def pick(self):  # the cut-off dialog: choose 11-04-2026 9:30:14 PM and confirm
        self.findChild(QDateTimeEdit).setDateTime(QDateTime(datetime(2026, 11, 4, 21, 30, 14)))
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", pick)
    dlg._mark_older()
    assert "2</b> will be marked" in dlg._mark_dialog.findChildren(QLabel)[-1].text()
    assert [os.path.basename(shot.path) for shot, _ in dlg.plan] == ["20261104213015_1.jpg"]
    assert [os.path.basename(shot.path) for shot, _ in SteamImportDialog(s).plan] == ["20261104213015_1.jpg"]


def test_import_videos_end_to_end(window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from photo_manager.ui import main_window as mw

    from .test_folder_import import make_share

    win, folder, _ = window
    share = make_share(tmp_path / "net")
    win.settings.video_sources = [str(share)]
    win.settings.video_dest = str(folder)  # straight into the open folder
    dlg = mw.VideoImportDialog(win.settings)
    deadline = time.time() + 5
    while dlg.scanning and time.time() < deadline:
        QApplication.processEvents()
    assert len(dlg.plan) == 3 and "3 new" in dlg.summary.text() and dlg.ok.isEnabled()
    assert dlg.folders.topLevelItemCount() == 3  # one row per subfolder

    def run_dialog(self):
        deadline = time.time() + 5
        while self.scanning and time.time() < deadline:
            QApplication.processEvents()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(mw.VideoImportDialog, "exec", run_dialog)
    win.quiet_import = True
    win.import_videos()
    win.copy_bg.wait()
    settle(win)
    done, failures = win.video_import_result
    assert len(done) == 3 and not failures
    assert {"top.mp4", "beach.MOV", "party.mkv"} <= {i.name for i in win.model.all_items}  # shown without F5
    again = mw.VideoImportDialog(win.settings)
    while again.scanning:
        QApplication.processEvents()
    assert again.plan == [] and "3 imported before" in again.summary.text()
