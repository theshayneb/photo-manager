"""Main window: folder tree | thumbnail grid | sidebar."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QByteArray, QDir, QModelIndex, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDockWidget, QFileSystemModel, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QScrollArea, QSlider, QToolBar, QTreeView,
)

from ..core import dates, fileops
from ..core.exiftool import ExifTool
from ..core.metadata import LABELS, READ_TAGS, Meta, parse_meta
from ..core.settings import Settings, cache_dir
from .dialogs import MoveDialog, TemplateDialog
from .grid import Item, PhotoModel, ThumbGrid
from .panels import Sidebar
from .viewer import Viewer
from .workers import Background

META_CHUNK = 100

STYLE = """
QPushButton[keyword="true"] { padding: 4px 6px; }
QPushButton[keyword="true"][state="all"] {
    background-color: palette(highlight); color: palette(highlighted-text); font-weight: bold; }
QPushButton[keyword="true"][state="some"] { border: 2px dashed palette(highlight); }
QPushButton[chip="true"] { padding: 2px 8px; }
QLabel[hint="true"] { color: gray; }
"""


def _key(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings, exiftool: ExifTool | None):
        super().__init__()
        self.settings = settings
        self.et = exiftool
        self.exiftool_ok = exiftool is not None
        self.bg = Background(threads=1)  # ExifTool and file operations run one at a time
        self.setWindowTitle("Photo Manager")
        self.resize(1400, 900)
        self.setStyleSheet(STYLE)

        self.model = PhotoModel(cache_dir() / "thumbs", self)
        self.model.sort_by = settings.sort_by
        self.grid = ThumbGrid(self.model)
        self.grid.set_thumb_size(settings.thumb_size)
        self.grid.selectionModel().selectionChanged.connect(lambda *_: self._schedule_refresh())
        self.grid.activated.connect(lambda _idx: self.open_viewer())
        self.setCentralWidget(self.grid)

        self._build_tree()
        self._build_sidebar()
        self._build_toolbar()
        self._build_shortcuts()
        self.status = QLabel()
        self.statusBar().addWidget(self.status, 1)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(40)
        self._refresh_timer.timeout.connect(self.refresh_sidebar)
        self.viewer: Viewer | None = None

        if settings.window_geometry:
            self.restoreGeometry(QByteArray.fromBase64(settings.window_geometry.encode()))
        if settings.window_state:
            self.restoreState(QByteArray.fromBase64(settings.window_state.encode()))
        if not self.exiftool_ok:
            self.sidebar.warning.setText(
                "ExifTool wasn't found, so dates, keywords and labels can't be read or saved. "
                "Put exiftool.exe in the “exiftool” folder next to the app (see README).")
            self.sidebar.warning.setVisible(True)

        start = settings.last_folder if os.path.isdir(settings.last_folder) else str(Path.home() / "Pictures")
        if not os.path.isdir(start):
            start = str(Path.home())
        QTimer.singleShot(0, lambda: self.open_folder(start))

    # ------------------------------------------------------------------ UI

    def _build_tree(self) -> None:
        self.fs_model = QFileSystemModel(self)
        self.fs_model.setFilter(QDir.Filter.AllDirs | QDir.Filter.NoDotAndDotDot | QDir.Filter.Drives)
        self.fs_model.setRootPath("")
        self.tree = QTreeView()
        self.tree.setModel(self.fs_model)
        for col in (1, 2, 3):
            self.tree.hideColumn(col)
        self.tree.setHeaderHidden(True)
        self.tree.setAnimated(False)
        self.tree.clicked.connect(self._tree_clicked)
        self.tree.activated.connect(self._tree_clicked)
        dock = QDockWidget("Folders", self)
        dock.setObjectName("folders")
        dock.setWidget(self.tree)
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)
        self.resizeDocks([dock], [280], Qt.Orientation.Horizontal)

    def _build_sidebar(self) -> None:
        self.sidebar = Sidebar(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(self.sidebar)
        scroll.setMinimumWidth(340)
        dock = QDockWidget("Details", self)
        dock.setObjectName("details")
        dock.setWidget(scroll)
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)

    def _build_toolbar(self) -> None:
        bar = QToolBar("Main")
        bar.setObjectName("main-toolbar")
        bar.setMovable(False)
        self.addToolBar(bar)

        up = QAction("⬆ Up", self)
        up.setToolTip("Parent folder (Alt+Up)")
        up.setShortcut(QKeySequence("Alt+Up"))
        up.triggered.connect(self.go_up)
        bar.addAction(up)

        self.address = QLineEdit()
        self.address.setPlaceholderText("Folder path")
        self.address.returnPressed.connect(lambda: self.open_folder(self.address.text().strip().strip('"')))
        self.address.setMinimumWidth(320)
        bar.addWidget(self.address)

        refresh = QAction("⟳ Refresh", self)
        refresh.setShortcut(QKeySequence("F5"))
        refresh.triggered.connect(lambda: self.open_folder(self.model.folder))
        bar.addAction(refresh)
        bar.addSeparator()

        bar.addWidget(QLabel(" Sort: "))
        self.sort_combo = QComboBox()
        for label, key in (("Name", "name"), ("Date taken", "date"), ("Modified", "modified"), ("Size", "size")):
            self.sort_combo.addItem(label, key)
        self.sort_combo.setCurrentIndex(max(0, self.sort_combo.findData(self.settings.sort_by)))
        self.sort_combo.currentIndexChanged.connect(self._sort_changed)
        bar.addWidget(self.sort_combo)

        bar.addWidget(QLabel("  Size: "))
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(80, 320)
        slider.setValue(self.settings.thumb_size)
        slider.setFixedWidth(120)
        slider.valueChanged.connect(self._size_changed)
        bar.addWidget(slider)
        bar.addSeparator()

        for text, shortcut, tip, slot in (
            ("View", "", "Open the viewer (Enter / double-click)", self.open_viewer),
            ("Move to…", "Ctrl+M", "Move selected files to another folder (Ctrl+M)", self.move_selected),
            ("Delete", "", "Send selected files to the Recycle Bin (Delete)", self.delete_selected),
            ("Show in Explorer", "Ctrl+E", "Show in Windows Explorer (Ctrl+E)", self.show_in_explorer),
            ("Open with default app", "Ctrl+O", "Open in the default Windows app (Ctrl+O)", self.open_external_selected),
        ):
            action = QAction(text, self)
            action.setToolTip(tip)
            if shortcut:
                action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(slot)
            bar.addAction(action)

    def _build_shortcuts(self) -> None:
        delete = QShortcut(QKeySequence(Qt.Key.Key_Delete), self.grid)
        delete.activated.connect(self.delete_selected)
        for n, label in enumerate(LABELS, start=1):
            sc = QShortcut(QKeySequence(f"Ctrl+{n}"), self)
            sc.activated.connect(lambda name=label: self._label_shortcut(name))
        clear = QShortcut(QKeySequence("Ctrl+0"), self)
        clear.activated.connect(lambda: self._label_shortcut(""))

    # ------------------------------------------------------------- folders

    def _tree_clicked(self, index: QModelIndex) -> None:
        path = self.fs_model.filePath(index)
        if path and os.path.isdir(path):
            self.open_folder(path)

    def go_up(self) -> None:
        if self.model.folder:
            parent = os.path.dirname(os.path.normpath(self.model.folder))
            if parent and parent != os.path.normpath(self.model.folder):
                self.open_folder(parent)

    def open_folder(self, folder: str) -> None:
        if not folder or not os.path.isdir(folder):
            self.status.setText(f"Folder not found: {folder}")
            return
        folder = os.path.normpath(folder)
        self.model.load_folder(folder)
        self.settings.last_folder = folder
        self.address.setText(folder)
        index = self.fs_model.index(folder)
        if index.isValid():
            self.tree.setCurrentIndex(index)
            self.tree.scrollTo(index)
        self.grid.scrollToTop()
        if self.model.items:
            self.grid.setCurrentIndex(self.model.index(0))
        self._show_count()
        self._load_meta([i.path for i in self.model.items])
        self.refresh_sidebar()

    def _show_count(self) -> None:
        n = len(self.model.items)
        self.status.setText(f"{n} photo{'s' if n != 1 else ''} and video{'s' if n != 1 else ''}")

    def _sort_changed(self) -> None:
        self.settings.sort_by = self.sort_combo.currentData()
        selected = self.grid.selected_paths()
        self.model.set_sort(self.settings.sort_by)
        self._reselect(selected)

    def _size_changed(self, value: int) -> None:
        self.settings.thumb_size = value
        self.grid.set_thumb_size(value)

    def _reselect(self, paths: list[str]) -> None:
        sel = self.grid.selectionModel()
        sel.clearSelection()
        for path in paths:
            row = self.model.row_of(path)
            if row >= 0:
                sel.select(self.model.index(row), sel.SelectionFlag.Select)

    # ------------------------------------------------------------ metadata

    def _read_meta(self, paths: list[str], generation: int | None = None) -> dict[str, Meta]:
        if generation is not None and generation != self.model.generation:
            return {}
        result = {p: Meta() for p in paths}
        if self.et is None:
            return result
        wanted = {_key(p): p for p in paths}
        for data in self.et.read(paths, READ_TAGS):
            original = wanted.get(_key(str(data.get("SourceFile", ""))))
            if original:
                result[original] = parse_meta(data)
        return result

    def _load_meta(self, paths: list[str]) -> None:
        generation = self.model.generation
        for start in range(0, len(paths), META_CHUNK):
            chunk = paths[start : start + META_CHUNK]
            self.bg.run(lambda c=chunk: self._read_meta(c, generation), self._meta_loaded)

    def _meta_loaded(self, metas: dict[str, Meta] | None, error: str | None) -> None:
        if error:
            self.status.setText(f"Couldn't read metadata: {error}")
            return
        if metas:
            selected = self.grid.selected_paths()
            self.model.set_meta(metas)
            if self.model.sort_by == "date":
                self._reselect(selected)
            if {_key(p) for p in selected} & {_key(p) for p in metas}:
                self._schedule_refresh()

    def write_metadata(self, jobs: list[tuple[str, list[str]]], what: str) -> None:
        if not jobs or self.et is None:
            return
        et = self.et
        self.status.setText(f"Saving {what} to {len(jobs)} file(s)…")

        def work() -> tuple[list[tuple[str, str]], dict[str, Meta]]:
            errors = []
            for path, args in jobs:
                error = et.write(path, args)
                if error:
                    errors.append((path, error))
            return errors, self._read_meta([p for p, _ in jobs])

        def done(result, error: str | None) -> None:  # type: ignore[no-untyped-def]
            if error:
                QMessageBox.warning(self, "Couldn't save", error)
                return
            errors, metas = result
            for path in metas:
                self.model.refresh_file(path)
            self._meta_loaded(metas, None)
            self.refresh_sidebar()
            saved = len(jobs) - len(errors)
            self.status.setText(f"Saved {what} to {saved} file(s)." + (f" {len(errors)} failed." if errors else ""))
            if errors:
                lines = "\n".join(f"• {os.path.basename(p)}: {e}" for p, e in errors[:12])
                more = f"\n…and {len(errors) - 12} more" if len(errors) > 12 else ""
                QMessageBox.warning(self, "Some files weren't changed", lines + more)
            self.settings.save()

        self.bg.run(work, done)

    # ------------------------------------------------------------- sidebar

    def selected_items(self) -> list[Item]:
        return [i for i in (self.model.item(p) for p in self.grid.selected_paths()) if i]

    def _schedule_refresh(self) -> None:
        self._refresh_timer.start()

    def refresh_sidebar(self) -> None:
        self._refresh_timer.stop()
        items = self.selected_items()
        self.sidebar.refresh(items)
        if items:
            self.statusBar().showMessage(f"{len(items)} selected", 2000)

    def _label_shortcut(self, label: str) -> None:
        self.refresh_sidebar()
        self.sidebar.labels.apply(label)

    def edit_templates(self) -> None:
        dlg = TemplateDialog(self.settings.templates, self.settings.display_format, self)
        if dlg.exec():
            self.settings.templates = dlg.templates()
            self.settings.save()
            self.sidebar.dates.reload_templates()

    # ---------------------------------------------------------- file ops

    def _after_removal(self, removed: list[str]) -> None:
        current = self.grid.currentIndex().row()
        self.model.remove_paths(removed)
        if self.model.items:
            row = min(max(current, 0), len(self.model.items) - 1)
            self.grid.setCurrentIndex(self.model.index(row))
        self._show_count()
        self.refresh_sidebar()

    def delete_selected(self) -> None:
        paths = self.grid.selected_paths()
        if not paths:
            return
        if self.settings.confirm_delete:
            box = QMessageBox(QMessageBox.Icon.Question, "Delete",
                              f"Send {len(paths)} file{'s' if len(paths) != 1 else ''} to the Recycle Bin?",
                              QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, self)
            dont_ask = QCheckBox("Don't ask again")
            box.setCheckBox(dont_ask)
            if box.exec() != QMessageBox.StandardButton.Yes:
                return
            if dont_ask.isChecked():
                self.settings.confirm_delete = False

        def done(failures, error: str | None) -> None:  # type: ignore[no-untyped-def]
            failures = failures or []
            failed = {p for p, _ in failures}
            self._after_removal([p for p in paths if p not in failed])
            if error or failures:
                QMessageBox.warning(self, "Delete", error or "\n".join(f"{p}: {e}" for p, e in failures[:10]))
            if self.viewer and self.viewer.isVisible():
                self._viewer_show_current()

        self.bg.run(lambda: fileops.recycle(paths), done)

    def move_selected(self) -> None:
        paths = self.grid.selected_paths()
        if not paths:
            return
        dlg = MoveDialog(self.settings.recent_move_folders, self.model.folder, len(paths), self)
        if not dlg.exec() or not dlg.folder:
            return
        folder = dlg.folder
        if not os.path.isdir(folder):
            QMessageBox.warning(self, "Move", f"Folder not found:\n{folder}")
            return
        self.settings.remember_move_folder(folder)

        def done(result, error: str | None) -> None:  # type: ignore[no-untyped-def]
            if error:
                QMessageBox.warning(self, "Move", error)
                return
            moved, failures = result
            self._after_removal(list(moved))
            self.status.setText(f"Moved {len(moved)} file(s) to {folder}")
            if failures:
                QMessageBox.warning(self, "Move", "\n".join(f"{p}: {e}" for p, e in failures[:10]))

        self.bg.run(lambda: fileops.move(paths, folder), done)

    def rename_files(self, plan: dict[str, str]) -> None:
        def done(result, error: str | None) -> None:  # type: ignore[no-untyped-def]
            if error:
                QMessageBox.warning(self, "Rename", error)
                return
            renamed, failures = result
            self.model.rename_paths(renamed)
            self._reselect(list(renamed.values()) + [p for p, _ in failures])
            self.status.setText(f"Renamed {len(renamed)} file(s).")
            if failures:
                QMessageBox.warning(self, "Rename", "\n".join(f"{p}: {e}" for p, e in failures[:10]))
            self.refresh_sidebar()

        self.bg.run(lambda: fileops.rename(plan), done)

    def show_in_explorer(self) -> None:
        path = self.grid.current_path() or self.model.folder
        if not path:
            return
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))

    def open_external(self, path: str) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def open_external_selected(self) -> None:
        path = self.grid.current_path()
        if path:
            self.open_external(path)

    # -------------------------------------------------------------- viewer

    def open_viewer(self) -> None:
        if not self.grid.current_path():
            return
        if self.viewer is None:
            self.viewer = Viewer(self)
            self.viewer.navigate.connect(self._viewer_step)
            self.viewer.delete_requested.connect(self._viewer_delete)
            self.viewer.finished.connect(lambda _r: self.grid.setFocus())
        self.viewer.showMaximized()
        self._viewer_show_current()

    def _viewer_show_current(self) -> None:
        path = self.grid.current_path()
        item = self.model.item(path) if path else None
        if not item or not self.viewer:
            if self.viewer:
                self.viewer.close()
            return
        row = self.model.row_of(item.path)
        parts = [f"{row + 1} / {len(self.model.items)}", item.name]
        if item.meta and item.meta.date_taken:
            parts.append(dates.format_display(item.meta.date_taken, self.settings.display_format))
        if item.meta and item.meta.label:
            parts.append(item.meta.label)
        self.viewer.show_path(item.path, "   ·   ".join(parts), item.kind, self.open_external)

    def _viewer_step(self, delta: int) -> None:
        row = self.grid.currentIndex().row() + delta
        if 0 <= row < len(self.model.items):
            self.grid.setCurrentIndex(self.model.index(row))
            self._viewer_show_current()

    def _viewer_delete(self) -> None:
        path = self.grid.current_path()
        if path:
            self.grid.selectionModel().clearSelection()
            self.grid.setCurrentIndex(self.model.index(self.model.row_of(path)))
            self.delete_selected()

    # ---------------------------------------------------------------- close

    def closeEvent(self, event: QCloseEvent) -> None:
        self.settings.window_geometry = bytes(self.saveGeometry().toBase64()).decode()
        self.settings.window_state = bytes(self.saveState().toBase64()).decode()
        try:
            self.settings.save()
        except OSError:
            pass
        self.bg.wait(10_000)
        if self.et:
            self.et.close()
        super().closeEvent(event)

