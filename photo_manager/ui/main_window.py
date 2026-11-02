"""Main window: favorites + folder tree | thumbnail grid | sidebar."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QByteArray, QDir, QMimeData, QModelIndex, Qt, QTimer, QUrl
from PySide6.QtGui import (
    QAction, QActionGroup, QCloseEvent, QDesktopServices, QKeySequence, QShortcut,
)
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDockWidget, QFileSystemModel, QLabel,
    QLineEdit, QListWidgetItem, QMainWindow, QMenu, QMessageBox, QScrollArea,
    QSlider, QSplitter, QStackedWidget, QToolBar, QVBoxLayout, QWidget,
)

from ..core import dates, fileops
from ..core.convert import convert_file, needs_conversion
from ..core.crop import can_crop, save_crop
from ..core.templates import follows_pattern, rename_pattern_regex
from ..core.winshell import open_with, show_properties
from ..core.exiftool import ExifTool
from ..core.metadata import LABELS, READ_TAGS, Meta, parse_meta
from ..core.settings import Settings, cache_dir
from .dialogs import ConvertDialog, HotkeyDialog, MoveDialog, RenameDialog, TemplateDialog
from .grid import GROUPS, INFO_FIELDS, Item, PhotoModel, ThumbGrid
from .panels import PANELS, Sidebar
from .theme import THEMES, apply_theme
from .folders import FavoritesList, FolderTree
from .preview import PreviewPane
from .viewer import Viewer
from .workers import Background

META_CHUNK = 100

STYLE = """
QPushButton[keyword="true"] { padding: 2px 4px; min-width: 0px; min-height: 18px;
    border: 1px solid palette(mid); border-radius: 3px; background-color: palette(button); }
QPushButton[keyword="true"]:hover { border-color: palette(highlight); }
QPushButton[keyword="true"][state="all"] {
    background-color: palette(highlight); color: palette(highlighted-text); border-color: palette(highlight); }
QPushButton[keyword="true"][state="some"] { border: 2px dashed palette(highlight); padding: 1px 3px; }
QPushButton[chip="true"] { padding: 2px 8px; }
QPushButton[flag="true"] { padding: 0px; min-width: 28px; max-width: 28px; min-height: 20px; max-height: 20px;
    border: 1px solid palette(mid); border-radius: 4px; background-color: palette(button); font-size: 13px; }
QPushButton[flag="true"]:checked { background-color: palette(highlight); color: palette(highlighted-text);
    border-color: palette(highlight); font-weight: bold; }
QLabel[hint="true"] { color: gray; }
QToolButton[section="true"] { font-weight: bold; text-align: left; padding: 4px; border: none;
    border-bottom: 1px solid palette(mid); }
QLabel[dockTitle="true"] { font-weight: bold; padding: 4px 2px 2px 2px; }
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
        self.model.group_by = settings.group_by if settings.group_by in GROUPS else "none"
        self.model.week_start = settings.week_start
        self.grid = ThumbGrid(self.model)
        self.grid.delegate.display_format = settings.display_format
        self.grid.set_thumb_size(settings.thumb_size)
        self.grid.set_info_fields(settings.thumb_info)
        self.grid.delegate.show_type_badges = settings.type_badges
        self.grid.selectionModel().selectionChanged.connect(lambda *_: self._schedule_refresh())
        self.grid.activated.connect(lambda _idx: self.open_viewer())
        self.grid.drag_finished.connect(self._drag_finished)
        self.grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.grid.customContextMenuRequested.connect(self._grid_menu)
        self.preview = PreviewPane(settings)
        self.preview.closed.connect(self.close_preview)
        self.preview.navigate.connect(self._preview_step)
        self.preview.delete_requested.connect(self._preview_delete)
        self.preview.crop_requested.connect(self.crop_file)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.grid)
        self.stack.addWidget(self.preview)
        self.setCentralWidget(self.stack)

        self._build_folders()
        self._build_sidebar()
        self._build_toolbar()
        self._build_menus()
        self._build_shortcuts()
        self.status = QLabel()
        self.statusBar().addWidget(self.status, 1)
        self.rename_pattern_changed()

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

    def _build_folders(self) -> None:
        self.fs_model = QFileSystemModel(self)
        self.fs_model.setFilter(QDir.Filter.AllDirs | QDir.Filter.NoDotAndDotDot | QDir.Filter.Drives)
        self.fs_model.setRootPath("")
        self.tree = FolderTree()
        self.tree.files_dropped.connect(self.move_paths)
        self.tree.setModel(self.fs_model)
        for col in (1, 2, 3):
            self.tree.hideColumn(col)
        self.tree.setHeaderHidden(True)
        self.tree.setAnimated(False)
        self.tree.clicked.connect(self._tree_clicked)
        self.tree.activated.connect(self._tree_clicked)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_menu)

        self.favorites = FavoritesList()
        self.favorites.files_dropped.connect(self.move_paths)
        self.favorites.itemClicked.connect(lambda item: self.open_folder(item.data(Qt.ItemDataRole.UserRole)))
        self.favorites.model().rowsMoved.connect(lambda *_: self._save_favorite_order())
        self.favorites.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.favorites.customContextMenuRequested.connect(self._favorites_menu)
        self.favorites.setToolTip("Right-click a folder in the tree → Add to Favorites. Drag to reorder. Drop photos here to move them.")
        self._fill_favorites()

        def titled(title: str, widget: QWidget) -> QWidget:
            box = QWidget()
            layout = QVBoxLayout(box)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
            label = QLabel(title)
            label.setProperty("dockTitle", True)
            layout.addWidget(label)
            layout.addWidget(widget)
            return box

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(titled("★ Favorites", self.favorites))
        splitter.addWidget(titled("Folders", self.tree))
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 4)
        splitter.setSizes([150, 600])
        dock = QDockWidget("Folders", self)
        dock.setObjectName("folders")
        dock.setTitleBarWidget(QWidget())
        dock.setWidget(splitter)
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
        self.details_dock = QDockWidget("Details", self)
        self.details_dock.setObjectName("details")
        self.details_dock.setTitleBarWidget(QWidget())
        self.details_dock.setWidget(scroll)
        self.details_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.details_dock)

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
        self.address.setMinimumWidth(280)
        bar.addWidget(self.address)

        self.fav_action = QAction("☆", self)
        self.fav_action.setToolTip("Add this folder to Favorites (Ctrl+D)")
        self.fav_action.setShortcut(QKeySequence("Ctrl+D"))
        self.fav_action.triggered.connect(lambda: self.toggle_favorite(self.model.folder))
        bar.addAction(self.fav_action)

        refresh = QAction("⟳", self)
        refresh.setToolTip("Refresh (F5)")
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

        bar.addWidget(QLabel("  Group: "))
        self.group_combo = QComboBox()
        for key, label in GROUPS.items():
            self.group_combo.addItem(label, key)
        self.group_combo.setCurrentIndex(max(0, self.group_combo.findData(self.model.group_by)))
        self.group_combo.currentIndexChanged.connect(lambda _i: self.set_group(self.group_combo.currentData()))
        bar.addWidget(self.group_combo)

        bar.addWidget(QLabel("  Size: "))
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(80, 320)
        slider.setValue(self.settings.thumb_size)
        slider.setFixedWidth(110)
        slider.valueChanged.connect(self._size_changed)
        bar.addWidget(slider)
        bar.addSeparator()

        for text, shortcut, tip, slot in (
            ("View", "", "Open the viewer (Enter / double-click)", self.open_viewer),
            ("Move to…", "Ctrl+M", "Move selected files to another folder (Ctrl+M)", self.move_selected),
            ("Convert…", "", "Convert selected images to JPG or PNG", self.convert_selected),
            ("Delete", "", "Send selected files to the Recycle Bin (Delete)", self.delete_selected),
            ("Show in Explorer", "Ctrl+E", "Show in Windows Explorer (Ctrl+E)", self.show_in_explorer),
            ("Open", "Ctrl+O", "Open in the default Windows app (Ctrl+O)", self.open_external_selected),
        ):
            action = QAction(text, self)
            action.setToolTip(tip)
            if shortcut:
                action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(slot)
            bar.addAction(action)

    def _build_menus(self) -> None:
        view = self.menuBar().addMenu("&View")

        panels = view.addMenu("Sidebar panels")
        self.panel_actions: dict[str, QAction] = {}
        for key, title in PANELS.items():
            action = panels.addAction(title)
            action.setCheckable(True)
            action.setChecked(key not in self.settings.hidden_panels)
            action.toggled.connect(lambda on, k=key: self.sidebar.set_panel_visible(k, on))
            self.panel_actions[key] = action
        panels.addSeparator()
        sidebar_toggle = self.details_dock.toggleViewAction()
        sidebar_toggle.setText("Show sidebar")
        sidebar_toggle.setShortcut(QKeySequence("F9"))
        panels.addAction(sidebar_toggle)

        badges = view.addAction("File type badges")
        badges.setCheckable(True)
        badges.setChecked(self.settings.type_badges)
        badges.toggled.connect(self._toggle_badges)
        misnamed = view.addAction("Highlight names not in rename format")
        misnamed.setCheckable(True)
        misnamed.setChecked(self.settings.highlight_misnamed)
        misnamed.toggled.connect(self._toggle_misnamed)
        select_misnamed = view.addAction("Select files that need renaming")
        select_misnamed.setShortcut(QKeySequence("Ctrl+Shift+R"))
        select_misnamed.triggered.connect(self.select_misnamed)
        view.addAction("Label hotkeys…", self.edit_label_hotkeys)
        view.addSeparator()
        info = view.addMenu("Show under thumbnails")
        for key, title in INFO_FIELDS.items():
            action = info.addAction(title)
            action.setCheckable(True)
            action.setChecked(key in self.settings.thumb_info)
            action.toggled.connect(lambda on, k=key: self._toggle_info(k, on))

        group = view.addMenu("Group by")
        self.group_actions = QActionGroup(self)
        self.group_menu_actions: dict[str, QAction] = {}
        for key, title in GROUPS.items():
            action = group.addAction(title)
            action.setCheckable(True)
            action.setChecked(key == self.model.group_by)
            action.triggered.connect(lambda _c=False, k=key: self.set_group(k))
            self.group_actions.addAction(action)
            self.group_menu_actions[key] = action
        group.addSeparator()
        weeks = QActionGroup(self)
        for key, title in (("sunday", "Weeks start on Sunday"), ("monday", "Weeks start on Monday")):
            action = group.addAction(title)
            action.setCheckable(True)
            action.setChecked(self.settings.week_start == key)
            action.triggered.connect(lambda _c=False, k=key: self.set_week_start(k))
            weeks.addAction(action)

        theme = view.addMenu("Theme")
        themes = QActionGroup(self)
        for key, title in THEMES.items():
            action = theme.addAction(title)
            action.setCheckable(True)
            action.setChecked(self.settings.theme == key)
            action.triggered.connect(lambda _c=False, k=key: self.set_theme(k))
            themes.addAction(action)

    def _build_shortcuts(self) -> None:
        delete = QShortcut(QKeySequence(Qt.Key.Key_Delete), self.grid)
        delete.activated.connect(self.delete_selected)
        self.label_shortcuts: list[QShortcut] = []
        self._build_label_shortcuts()
        for keys, slot in (("F2", self.rename_current), ("Ctrl+C", self.copy_files)):
            sc = QShortcut(QKeySequence(keys), self.grid)
            sc.setContext(Qt.ShortcutContext.WidgetShortcut)
            sc.activated.connect(slot)
        preview = QShortcut(QKeySequence("Shift+P"), self.grid)
        preview.setContext(Qt.ShortcutContext.WidgetShortcut)
        preview.activated.connect(self.open_preview)

    # Keys the app already uses; label hotkeys can't take these.
    RESERVED_KEYS = {
        "Ctrl+M": "Move to", "Ctrl+E": "Show in Explorer", "Ctrl+O": "Open", "Ctrl+D": "Favorite folder",
        "Ctrl+C": "Copy", "Ctrl+A": "Select all", "F2": "Rename", "F5": "Refresh", "F9": "Sidebar",
        "Shift+P": "Preview", "Ctrl+Shift+R": "Select files that need renaming", "Del": "Delete",
        "Alt+Up": "Parent folder",
    }

    def _build_label_shortcuts(self) -> None:
        for sc in self.label_shortcuts:
            sc.setEnabled(False)
            sc.deleteLater()
        self.label_shortcuts = []
        actions = {label: (lambda name=label: self._label_shortcut(name)) for label in LABELS}
        actions["None"] = lambda: self._label_shortcut("")
        actions["Star"] = lambda: self._flag_shortcut("Star")
        actions["Bookmark"] = lambda: self._flag_shortcut("Bookmark")
        for name, slot in actions.items():
            keys = self.settings.label_hotkeys.get(name, "")
            if keys:
                sc = QShortcut(QKeySequence(keys), self)
                sc.activated.connect(slot)
                self.label_shortcuts.append(sc)

    def edit_label_hotkeys(self) -> None:
        from ..core.settings import DEFAULT_LABEL_HOTKEYS

        dlg = HotkeyDialog(self.settings.label_hotkeys, DEFAULT_LABEL_HOTKEYS, self.RESERVED_KEYS, self)
        if dlg.exec():
            self.settings.label_hotkeys = dlg.hotkeys()
            self.settings.save()
            self._build_label_shortcuts()
            self.sidebar.labels.update_tooltips()

    def _flag_shortcut(self, flag: str) -> None:
        self.refresh_sidebar()
        self.sidebar.labels.toggle_flag(flag)

    # -------------------------------------------------------------- options

    def set_group(self, key: str) -> None:
        if key not in GROUPS:
            return
        self.settings.group_by = key
        self.model.group_by = key
        for widget_key, action in self.group_menu_actions.items():
            action.setChecked(widget_key == key)
        self.group_combo.blockSignals(True)
        self.group_combo.setCurrentIndex(max(0, self.group_combo.findData(key)))
        self.group_combo.blockSignals(False)
        self.regroup()

    def set_week_start(self, key: str) -> None:
        self.settings.week_start = key
        self.model.week_start = key
        if self.model.group_by == "week":
            self.regroup()

    def set_theme(self, key: str) -> None:
        self.settings.theme = key
        apply_theme(key)
        self.grid.viewport().update()

    def _toggle_info(self, key: str, on: bool) -> None:
        fields = [f for f in self.settings.thumb_info if f != key]
        if on:
            fields.append(key)
        self.settings.thumb_info = [f for f in INFO_FIELDS if f in fields]
        self.grid.set_info_fields(self.settings.thumb_info)

    # ------------------------------------------------------------ favorites

    def _fill_favorites(self) -> None:
        self.favorites.clear()
        for folder in self.settings.favorites:
            name = os.path.basename(os.path.normpath(folder)) or folder
            item = QListWidgetItem(f"★  {name}")
            item.setData(Qt.ItemDataRole.UserRole, folder)
            item.setToolTip(folder)
            if not os.path.isdir(folder):
                item.setForeground(Qt.GlobalColor.gray)
                item.setToolTip(folder + "  (not found)")
            self.favorites.addItem(item)

    def _save_favorite_order(self) -> None:
        self.settings.favorites = [self.favorites.item(i).data(Qt.ItemDataRole.UserRole)
                                   for i in range(self.favorites.count())]

    def is_favorite(self, folder: str) -> bool:
        return any(_key(f) == _key(folder) for f in self.settings.favorites)

    def toggle_favorite(self, folder: str) -> None:
        if not folder:
            return
        if self.is_favorite(folder):
            self.settings.favorites = [f for f in self.settings.favorites if _key(f) != _key(folder)]
        else:
            self.settings.favorites.append(os.path.normpath(folder))
        self._fill_favorites()
        self._update_fav_button()
        self.settings.save()

    def _update_fav_button(self) -> None:
        fav = self.is_favorite(self.model.folder) if self.model.folder else False
        self.fav_action.setText("★" if fav else "☆")
        self.fav_action.setToolTip(("Remove this folder from" if fav else "Add this folder to") + " Favorites (Ctrl+D)")

    def _tree_menu(self, pos) -> None:  # type: ignore[no-untyped-def]
        index = self.tree.indexAt(pos)
        path = self.fs_model.filePath(index) if index.isValid() else ""
        if not path:
            return
        menu = QMenu(self)
        menu.addAction("Remove from Favorites" if self.is_favorite(path) else "Add to Favorites",
                       lambda: self.toggle_favorite(path))
        menu.addAction("Open", lambda: self.open_folder(path))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _favorites_menu(self, pos) -> None:  # type: ignore[no-untyped-def]
        item = self.favorites.itemAt(pos)
        if not item:
            return
        folder = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        menu.addAction("Open", lambda: self.open_folder(folder))
        menu.addAction("Remove from Favorites", lambda: self.toggle_favorite(folder))
        menu.exec(self.favorites.viewport().mapToGlobal(pos))

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
        self._update_fav_button()
        # The folder tree is left alone (no auto-expanding to the open folder).
        self.grid.scrollToTop()
        first = self.model.first_item_row()
        if first >= 0:
            self.grid.setCurrentIndex(self.model.index(first))
        self._show_count()
        self._load_meta([i.path for i in self.model.items])
        self.refresh_sidebar()

    def _show_count(self) -> None:
        n = len(self.model.items)
        text = f"{n} photo{'s' if n != 1 else ''} and video{'s' if n != 1 else ''}"
        misnamed = len(self.misnamed_paths())
        if misnamed:
            text += f"   ·   ⚠ {misnamed} not in rename format (Ctrl+Shift+R selects them)"
        self.status.setText(text)

    # --------------------------------------------------------- name format

    def rename_pattern_changed(self) -> None:
        regex = rename_pattern_regex(self.settings.rename_pattern) if self.settings.highlight_misnamed else None
        self.grid.delegate.name_regex = regex
        self.grid.viewport().update()
        if hasattr(self, "status"):
            self._show_count()

    def misnamed_paths(self) -> list[str]:
        regex = self.grid.delegate.name_regex
        if regex is None:
            return []
        return [i.path for i in self.model.visible_items() if not follows_pattern(i.name, regex)]

    def select_misnamed(self) -> None:
        if self.grid.delegate.name_regex is None:
            self._toggle_misnamed(True)
        paths = self.misnamed_paths()
        self.grid.select_paths(paths)
        if paths:
            self.grid.scrollTo(self.model.index(self.model.row_of(paths[0])))
        self.refresh_sidebar()

    def _toggle_misnamed(self, on: bool) -> None:
        self.settings.highlight_misnamed = on
        self.rename_pattern_changed()

    def _toggle_badges(self, on: bool) -> None:
        self.settings.type_badges = on
        self.grid.delegate.show_type_badges = on
        self.grid.viewport().update()

    # ------------------------------------------------------------- convert

    def convert_selected(self) -> None:
        paths = self.grid.selected_paths()
        if not any(needs_conversion(p, t) for p in paths for t in ("JPG", "PNG")):
            QMessageBox.information(self, "Convert", "Select some images to convert first.")
            return
        dlg = ConvertDialog(paths, self.settings, self)
        if not dlg.exec():
            return
        todo = dlg.to_convert()
        target, quality = self.settings.convert_target, self.settings.convert_quality
        recycle = self.settings.convert_recycle
        et = self.et
        self.status.setText(f"Converting {len(todo)} file(s) to {target}…")

        def work() -> tuple[dict[str, str], list[tuple[str, str]]]:
            done, failures = {}, []
            for path in todo:
                try:
                    done[path] = convert_file(path, target, quality, et, recycle)
                except Exception as exc:  # noqa: BLE001
                    failures.append((path, str(exc)))
            return done, failures

        def finished(result, error: str | None) -> None:  # type: ignore[no-untyped-def]
            if error:
                QMessageBox.warning(self, "Convert", error)
                return
            done, failures = result
            for new in done.values():
                self.model.add_path(new)
            if recycle:
                self.model.remove_paths(list(done))
            self.regroup(select=list(done.values()))
            self._load_meta(list(done.values()))
            self._show_count()
            self.refresh_sidebar()
            msg = f"Converted {len(done)} file(s) to {target}."
            if recycle and done:
                msg += " Originals are in the Recycle Bin."
            self.status.setText(msg)
            if failures:
                QMessageBox.warning(self, "Convert", "Some files weren't converted:\n" +
                                    "\n".join(f"• {os.path.basename(p)}: {e}" for p, e in failures[:10]))

        self.bg.run(work, finished)

    def _sort_changed(self) -> None:
        self.settings.sort_by = self.sort_combo.currentData()
        self.model.sort_by = self.settings.sort_by
        self.regroup()

    def _size_changed(self, value: int) -> None:
        self.settings.thumb_size = value
        self.grid.set_thumb_size(value)

    def regroup(self, select: list[str] | None = None, current: str | None = None) -> None:
        """Rebuild the grid order/groups while keeping selection, focus and scroll position."""
        selected = self.grid.selected_paths() if select is None else select
        current = current if current is not None else self.grid.current_path()
        scroll = self.grid.verticalScrollBar().value()
        self.model.regroup()
        self.grid.select_paths(selected, current=current)
        self.grid.doItemsLayout()
        self.grid.verticalScrollBar().setValue(scroll)

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
            if self.model.needs_regroup_for_meta():
                self.regroup(selected)
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
        gone = {_key(p) for p in removed}
        current = self.grid.current_path()
        target = None
        if current:
            for delta in range(1, len(self.model.items) + 1):
                for d in (delta, -delta):
                    cand = self.model.neighbour(current, d)
                    if cand and _key(cand.path) not in gone:
                        target = cand.path
                        break
                if target:
                    break
            if _key(current) not in gone:
                target = current
        self.model.remove_paths(removed)
        self.regroup(select=[target] if target else [], current=target)
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
            if self.previewing:
                self._preview_show_current()

        self.bg.run(lambda: fileops.recycle(paths), done)

    def move_selected(self) -> None:
        paths = self.grid.selected_paths()
        if not paths:
            return
        dlg = MoveDialog(self.settings.favorites, self.settings.recent_move_folders,
                         self.model.folder, len(paths), self)
        if not dlg.exec() or not dlg.folder:
            return
        folder = dlg.folder
        if not os.path.isdir(folder):
            QMessageBox.warning(self, "Move", f"Folder not found:\n{folder}")
            return
        self.settings.remember_move_folder(folder)
        self.move_paths(paths, folder)

    def move_paths(self, paths: list[str], folder: str, copy: bool = False) -> None:
        """Move (or copy) files into folder, never overwriting; updates the grid."""
        here = os.path.normcase(os.path.normpath(self.model.folder or ""))
        if not copy and os.path.normcase(os.path.normpath(folder)) == here:
            self.status.setText("Those files are already in this folder.")
            return
        verb = "Copied" if copy else "Moved"

        def done(result, error: str | None) -> None:  # type: ignore[no-untyped-def]
            if error:
                QMessageBox.warning(self, verb, error)
                return
            changed, failures = result
            if copy:
                if os.path.normcase(os.path.normpath(folder)) == here:
                    for new in changed.values():
                        self.model.add_path(new)
                    self.regroup()
                    self._show_count()
            else:
                self._after_removal(list(changed))
            self.status.setText(f"{verb} {len(changed)} file(s) to {folder}")
            if failures:
                QMessageBox.warning(self, verb, "\n".join(f"{p}: {e}" for p, e in failures[:10]))

        work = fileops.copy if copy else fileops.move
        self.bg.run(lambda: work(paths, folder), done)

    def _drag_finished(self, paths: list[str]) -> None:
        """After dragging out to Explorer, drop files that were moved away from the grid."""
        def check() -> None:
            gone = [p for p in paths if not os.path.exists(p) and self.model.item(p)]
            if gone:
                self._after_removal(gone)

        QTimer.singleShot(1500, check)

    def rename_files(self, plan: dict[str, str]) -> None:
        def done(result, error: str | None) -> None:  # type: ignore[no-untyped-def]
            if error:
                QMessageBox.warning(self, "Rename", error)
                return
            renamed, failures = result
            self.model.rename_paths(renamed)
            self.regroup(select=list(renamed.values()) + [p for p, _ in failures])
            self._show_count()
            self.status.setText(self.status.text() + f"   ·   Renamed {len(renamed)} file(s).")
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
        position = next((n for n, i in enumerate(self.model.items) if i is item), 0)
        parts = [f"{position + 1} / {len(self.model.items)}", item.name]
        if item.meta and item.meta.date_taken:
            parts.append(dates.format_display(item.meta.date_taken, self.settings.display_format))
        if item.meta and item.meta.label:
            parts.append(item.meta.label)
        self.viewer.show_path(item.path, "   ·   ".join(parts), item.kind, self.open_external)

    def _viewer_step(self, delta: int) -> None:
        path = self.grid.current_path()
        target = self.model.neighbour(path, delta) if path else None
        if target:
            self.grid.select_paths([target.path], current=target.path)
            self.grid.scrollTo(self.model.index(self.model.row_of(target.path)))
            self._viewer_show_current()

    def _viewer_delete(self) -> None:
        path = self.grid.current_path()
        if path:
            self.grid.select_paths([path], current=path)
            self.delete_selected()

    # --------------------------------------------------------- right-click

    def _grid_menu(self, pos) -> None:  # type: ignore[no-untyped-def]
        index = self.grid.indexAt(pos)
        if not index.isValid():
            return
        header = self.model.header_at(index.row())
        menu = QMenu(self)
        if header is not None:
            menu.addAction("Expand group" if header.collapsed else "Collapse group",
                           lambda: self.grid.toggle_group(header.title))
            menu.addAction("Select the photos in this group", lambda: self.select_group(header))
            menu.addSeparator()
            menu.addAction("Collapse all groups", lambda: self.grid.set_all_groups(True))
            menu.addAction("Expand all groups", lambda: self.grid.set_all_groups(False))
            menu.exec(self.grid.viewport().mapToGlobal(pos))
            return
        item = self.model.item_at(index.row())
        if item is None:
            return
        if item.path not in self.grid.selected_paths():
            self.grid.select_paths([item.path], current=item.path)
        else:
            self.grid.selectionModel().setCurrentIndex(index, self.grid.selectionModel().SelectionFlag.NoUpdate)
        self.refresh_sidebar()
        paths = self.grid.selected_paths()
        single = len(paths) == 1
        windows = sys.platform == "win32"

        def add(text: str, slot, shortcut: str = "", enabled: bool = True) -> None:  # type: ignore[no-untyped-def]
            action = menu.addAction(text, slot)
            if shortcut:
                action.setShortcut(QKeySequence(shortcut))
                action.setShortcutVisibleInContextMenu(True)
            action.setEnabled(enabled)

        add("Preview", self.open_preview, "Shift+P")
        add("View", self.open_viewer, "Return")
        add("Open", self.open_external_selected, "Ctrl+O")
        if windows:
            add("Open with…", lambda: open_with(item.path))
        menu.addSeparator()
        add("Rename…", self.rename_current, "F2", single)
        add("Crop…", self.crop_current, "", single and item.kind == "image" and can_crop(item.path))
        add("Convert to JPG…", self.convert_selected, "",
            any(needs_conversion(p, "JPG") for p in paths))
        labels = menu.addMenu("Labels")
        keys = self.settings.label_hotkeys
        entries = [(label, label, lambda name=label: self._label_shortcut(name)) for label in LABELS]
        entries.append(("None", "No color", lambda: self._label_shortcut("")))
        entries.append(None)
        entries.append(("Star", "★ Star", lambda: self._flag_shortcut("Star")))
        entries.append(("Bookmark", "🔖 Bookmark", lambda: self._flag_shortcut("Bookmark")))
        for entry in entries:
            if entry is None:
                labels.addSeparator()
                continue
            name, text, slot = entry
            action = labels.addAction(text, slot)
            if keys.get(name):
                action.setShortcut(QKeySequence(keys[name]))
                action.setShortcutVisibleInContextMenu(True)
        labels.addSeparator()
        labels.addAction("Hotkeys…", self.edit_label_hotkeys)
        labels.setEnabled(self.exiftool_ok)
        menu.addSeparator()
        add("Copy", self.copy_files, "Ctrl+C")
        add("Copy path" if single else f"Copy {len(paths)} paths", self.copy_paths)
        add("Move to…", self.move_selected, "Ctrl+M")
        add("Show in Explorer", self.show_in_explorer, "Ctrl+E")
        if windows:
            add("Properties", lambda: show_properties(item.path), "", single)
        menu.addSeparator()
        add("Delete (to Recycle Bin)", self.delete_selected, "Delete")
        menu.exec(self.grid.viewport().mapToGlobal(pos))

    def select_group(self, header) -> None:  # type: ignore[no-untyped-def]
        if header.collapsed:
            self.grid.toggle_group(header.title)
        self.grid.select_paths(header.paths)

    def rename_current(self) -> None:
        paths = self.grid.selected_paths()
        path = self.grid.current_path() if len(paths) != 1 else paths[0]
        if not path:
            return
        dlg = RenameDialog(path, self)
        if not dlg.exec():
            return
        new_path = os.path.join(os.path.dirname(path), dlg.new_name())
        if new_path != path:
            self.rename_files({path: new_path})

    def copy_files(self) -> None:
        paths = self.grid.selected_paths()
        if not paths:
            return
        data = QMimeData()
        data.setUrls([QUrl.fromLocalFile(p) for p in paths])
        data.setText("\n".join(os.path.normpath(p) for p in paths))
        QApplication.clipboard().setMimeData(data)
        self.status.setText(f"Copied {len(paths)} file(s) — paste them in Explorer.")

    def copy_paths(self) -> None:
        paths = self.grid.selected_paths()
        QApplication.clipboard().setText("\n".join(os.path.normpath(p) for p in paths))

    def crop_current(self) -> None:
        self.open_preview()
        if self.previewing:
            self.preview.start_crop()

    # ------------------------------------------------------- preview / crop

    @property
    def previewing(self) -> bool:
        return self.stack.currentWidget() is self.preview

    def open_preview(self) -> None:
        if not self.grid.current_path():
            return
        self.stack.setCurrentWidget(self.preview)
        self._preview_show_current()
        self.preview.setFocus()

    def close_preview(self) -> None:
        self.preview.cancel_crop()
        self.stack.setCurrentWidget(self.grid)
        path = self.grid.current_path()
        if path:
            self.grid.scrollTo(self.model.index(self.model.row_of(path)))
        self.grid.setFocus()

    def _caption(self, item: Item) -> str:
        position = next((n for n, i in enumerate(self.model.items) if i is item), 0)
        parts = [f"{position + 1} / {len(self.model.items)}", f"<b>{item.name}</b>"]
        if item.meta and item.meta.date_taken:
            parts.append(dates.format_display(item.meta.date_taken, self.settings.display_format))
        if item.meta and item.meta.label:
            parts.append(item.meta.label)
        return "   ·   ".join(parts)

    def _preview_show_current(self) -> None:
        path = self.grid.current_path()
        item = self.model.item(path) if path else None
        if not item:
            self.close_preview()
            return
        self.preview.show_item(item.path, item.kind, self._caption(item))
        self.refresh_sidebar()

    def _preview_step(self, delta: int) -> None:
        path = self.grid.current_path()
        target = self.model.neighbour(path, delta) if path else None
        if target:
            self.grid.select_paths([target.path], current=target.path)
            self._preview_show_current()

    def _preview_delete(self) -> None:
        path = self.grid.current_path()
        if path:
            self.grid.select_paths([path], current=path)
            self.delete_selected()

    def crop_file(self, path: str, box: tuple, as_copy: bool) -> None:
        et = self.et
        self.status.setText("Saving crop…")

        def done(new_path, error: str | None) -> None:  # type: ignore[no-untyped-def]
            if error:
                QMessageBox.warning(self, "Crop", f"The crop wasn't saved:\n{error}")
                self.status.setText("Crop not saved.")
                return
            if as_copy:
                self.model.add_path(new_path)
                self.regroup(select=[new_path], current=new_path)
                self._show_count()
                self.status.setText(f"Saved cropped copy: {os.path.basename(new_path)}")
            else:
                self.model.refresh_file(new_path)
                self.model.reload_thumb(new_path)
                self.status.setText("Cropped. The original is in the Recycle Bin.")
            self._load_meta([new_path])
            if self.previewing:
                self._preview_show_current()
            self.refresh_sidebar()

        self.bg.run(lambda: save_crop(path, box, et, as_copy), done)

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
