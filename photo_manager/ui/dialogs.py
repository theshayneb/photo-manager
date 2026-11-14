"""Template editor and the Move-to-folder picker."""

from __future__ import annotations

import os

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from ..core import dates
from ..core.templates import FilenameTemplate, TemplateError, compile_pattern, match_any

TEMPLATE_HELP = (
    "<b>Placeholders</b>: {YYYY} {YY} year · {MM} month · {DD} day · {HH} hour 00–23 · "
    "{hh} hour 01–12 with {AMPM} · {mm} minute · {ss} second · {fff} milliseconds (ignored)<br>"
    "<b>Wildcards</b>: * any text · ? one character · # one digit<br>"
    "The pattern is matched from the start of the filename; anything after it is ignored. "
    "Tick <b>UTC</b> when the camera writes the filename in UTC (Google Pixel “PXL_” files do). "
    "In <b>Auto</b> mode templates are tried top to bottom."
)


class TemplateDialog(QDialog):
    def __init__(self, templates: list[FilenameTemplate], display_format: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Filename date templates")
        self.resize(720, 460)
        self.display_format = display_format
        layout = QVBoxLayout(self)
        help_label = QLabel(TEMPLATE_HELP)
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Name", "Pattern", "UTC"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setColumnWidth(0, 200)
        self.table.verticalHeader().setVisible(False)
        self.table.itemChanged.connect(lambda _i: self._test())
        layout.addWidget(self.table, 1)
        for template in templates:
            self._add_row(template)

        row = QHBoxLayout()
        for text, slot in (("Add", lambda: self._add_row(FilenameTemplate("New template", "IMG_{YYYY}{MM}{DD}_{HH}{mm}{ss}"))),
                           ("Remove", self._remove_row), ("Move up", lambda: self._move(-1)),
                           ("Move down", lambda: self._move(1))):
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            row.addWidget(btn)
        row.addStretch(1)
        layout.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("Test a filename:"))
        self.sample = QLineEdit("PXL_20261031_140229473.jpg")
        self.sample.textChanged.connect(lambda _t: self._test())
        row.addWidget(self.sample, 1)
        layout.addLayout(row)
        self.result_label = QLabel()
        layout.addWidget(self.result_label)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._ready = True
        self._test()

    def _add_row(self, template: FilenameTemplate) -> None:
        self.table.blockSignals(True)
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(template.name))
        self.table.setItem(row, 1, QTableWidgetItem(template.pattern))
        check = QCheckBox()
        check.setChecked(template.utc)
        check.toggled.connect(lambda _c: self._test())
        holder = QWidget()
        hl = QHBoxLayout(holder)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hl.addWidget(check)
        self.table.setCellWidget(row, 2, holder)
        self.table.blockSignals(False)
        self._test()

    def _remove_row(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)
            self._test()

    def _move(self, delta: int) -> None:
        row = self.table.currentRow()
        target = row + delta
        if row < 0 or not 0 <= target < self.table.rowCount():
            return
        templates = self.templates()
        templates.insert(target, templates.pop(row))
        self.table.setRowCount(0)
        for template in templates:
            self._add_row(template)
        self.table.setCurrentCell(target, 1)

    def templates(self) -> list[FilenameTemplate]:
        out = []
        for row in range(self.table.rowCount()):
            name = (self.table.item(row, 0) or QTableWidgetItem("")).text().strip()
            pattern = (self.table.item(row, 1) or QTableWidgetItem("")).text().strip()
            holder = self.table.cellWidget(row, 2)
            check = holder.findChild(QCheckBox) if holder else None
            out.append(FilenameTemplate(name or pattern, pattern, bool(check and check.isChecked())))
        return out

    def _errors(self) -> list[str]:
        errors = []
        for n, template in enumerate(self.templates(), start=1):
            try:
                compile_pattern(template.pattern)
            except TemplateError as exc:
                errors.append(f"Row {n} ({template.name}): {exc}")
        return errors

    def _test(self) -> None:
        if not getattr(self, "_ready", False):  # still building the dialog
            return
        errors = self._errors()
        if errors:
            self.result_label.setText("<span style='color:#e5484d'>" + "<br>".join(errors) + "</span>")
            return
        found = match_any(self.templates(), self.sample.text().strip())
        if found:
            self.result_label.setText(f"✓ <b>{dates.format_display(found[1], self.display_format)}</b>"
                                f" — matched “{found[0].name}”")
        else:
            self.result_label.setText("No template matches this filename.")

    def _accept(self) -> None:
        if not self._errors():
            self.accept()


class MoveDialog(QDialog):
    """Pick a destination: recent folders (double-click / Enter) or Browse."""

    def __init__(self, favorites: list[str], recent: list[str], start_dir: str, count: int,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"Move {count} file{'s' if count != 1 else ''} to…")
        self.resize(520, 360)
        self.start_dir = start_dir
        self.folder = ""
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("★ Favorites, then recent folders (number keys pick 1–9):"))
        self.list = QListWidget()
        folders, seen = [], set()
        for folder in [*favorites, *recent]:
            key = os.path.normcase(os.path.normpath(folder))
            if key not in seen and os.path.isdir(folder):
                seen.add(key)
                folders.append((folder, folder in favorites))
        for n, (folder, fav) in enumerate(folders):
            star = "★ " if fav else "   "
            item = QListWidgetItem(f"{n + 1}.  {star}{folder}" if n < 9 else f"      {star}{folder}")
            item.setData(Qt.ItemDataRole.UserRole, folder)
            self.list.addItem(item)
        self.list.itemActivated.connect(lambda item: self._choose(item.data(Qt.ItemDataRole.UserRole)))
        if self.list.count():
            self.list.setCurrentRow(0)
        layout.addWidget(self.list, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        browse = buttons.addButton("Browse…", QDialogButtonBox.ButtonRole.ActionRole)
        browse.clicked.connect(self._browse)
        move = buttons.addButton("Move", QDialogButtonBox.ButtonRole.AcceptRole)
        move.clicked.connect(self._move_current)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        if not self.list.count():
            move.setEnabled(False)

    def keyPressEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        text = event.text()
        if text.isdigit() and text != "0" and int(text) <= min(9, self.list.count()):
            self._choose(self.list.item(int(text) - 1).data(Qt.ItemDataRole.UserRole))
            return
        super().keyPressEvent(event)

    def _move_current(self) -> None:
        item = self.list.currentItem()
        if item:
            self._choose(item.data(Qt.ItemDataRole.UserRole))

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Move to folder", self.start_dir)
        if folder:
            self._choose(folder)

    def _choose(self, folder: str) -> None:
        self.folder = os.path.normpath(folder)
        self.accept()


class KeywordSetDialog(QDialog):
    """Edit a keyword set: its name, and its keywords (rename, reorder, add, remove)."""

    def __init__(self, name: str, keywords: list[str], other_names: list[str], parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Edit keyword set")
        self.resize(380, 480)
        self.other_names = {n.casefold() for n in other_names}
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel("Set name:"))
        self.name = QLineEdit(name)
        row.addWidget(self.name, 1)
        layout.addLayout(row)
        layout.addWidget(QLabel("Keywords (double-click to rename, drag to reorder):"))
        self.list = QListWidget()
        self.list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        for kw in keywords:
            self._add_item(kw)
        layout.addWidget(self.list, 1)

        row = QHBoxLayout()
        self.new_kw = QLineEdit()
        self.new_kw.setPlaceholderText("New keyword (Enter to add)")
        self.new_kw.returnPressed.connect(self._add_typed)
        row.addWidget(self.new_kw, 1)
        for text, slot in (("Remove", self._remove), ("Sort A–Z", self._sort)):
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            row.addWidget(btn)
        layout.addLayout(row)
        note = QLabel("Changes here only affect the buttons. Keywords already on photos stay as they are.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.error = QLabel()
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _add_item(self, keyword: str) -> None:
        item = QListWidgetItem(keyword)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        self.list.addItem(item)

    def _add_typed(self) -> None:
        for word in self.new_kw.text().split(","):
            word = word.strip()
            if word and word.casefold() not in {k.casefold() for k in self.keywords()}:
                self._add_item(word)
        self.new_kw.clear()

    def _remove(self) -> None:
        for item in self.list.selectedItems():
            self.list.takeItem(self.list.row(item))

    def _sort(self) -> None:
        words = sorted(self.keywords(), key=str.casefold)
        self.list.clear()
        for word in words:
            self._add_item(word)

    def keywords(self) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for i in range(self.list.count()):
            word = self.list.item(i).text().strip()
            if word and word.casefold() not in seen:
                seen.add(word.casefold())
                out.append(word)
        return out

    def result_value(self) -> tuple[str, list[str]]:
        return self.name.text().strip(), self.keywords()

    def _accept(self) -> None:
        name = self.name.text().strip()
        if not name:
            self.error.setText("<span style='color:#e5484d'>The set needs a name.</span>")
        elif name.casefold() in self.other_names:
            self.error.setText("<span style='color:#e5484d'>Another set already has that name.</span>")
        else:
            self.accept()


class RenameDialog(QDialog):
    """Rename one file. The name (without extension) starts selected, like Explorer."""

    def __init__(self, path: str, parent: QWidget | None = None):
        from ..core.fileops import check_new_name

        super().__init__(parent)
        self.path = path
        self._check = check_new_name
        self.setWindowTitle("Rename")
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("New name:"))
        name = os.path.basename(path)
        self.edit = QLineEdit(name)
        stem = os.path.splitext(name)[0]
        self.edit.setSelection(0, len(stem))
        self.edit.textChanged.connect(lambda _t: self.error.setText(""))
        layout.addWidget(self.edit)
        self.error = QLabel()
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def new_name(self) -> str:
        return self.edit.text().strip()

    def _accept(self) -> None:
        problem = self._check(self.path, self.new_name())
        if problem:
            self.error.setText(f"<span style='color:#e5484d'>{problem}</span>")
            return
        if os.path.splitext(self.new_name())[1].lower() != os.path.splitext(self.path)[1].lower():
            self.error.setText("<span style='color:#e5484d'>Keep the same extension "
                               f"({os.path.splitext(self.path)[1]}) so the file still opens.</span>")
            return
        self.accept()


class ConvertDialog(QDialog):
    """Convert images to JPG (or PNG): quality, and what to do with the originals."""

    def __init__(self, paths: list[str], settings, parent: QWidget | None = None):  # type: ignore[no-untyped-def]
        from PySide6.QtWidgets import QComboBox, QRadioButton, QSlider

        from ..core.convert import needs_conversion

        super().__init__(parent)
        self.paths = paths
        self.settings = settings
        self._needs = needs_conversion
        self.setWindowTitle("Convert")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)

        row = QHBoxLayout()
        row.addWidget(QLabel("Convert to:"))
        self.target = QComboBox()
        self.target.addItems(["JPG", "PNG"])
        self.target.setCurrentText(getattr(settings, "convert_target", "JPG"))
        self.target.currentTextChanged.connect(lambda _t: self._update())
        row.addWidget(self.target)
        row.addStretch(1)
        layout.addLayout(row)

        row = QHBoxLayout()
        self.quality_label = QLabel()
        self.quality = QSlider(Qt.Orientation.Horizontal)
        self.quality.setRange(60, 100)
        self.quality.setValue(int(getattr(settings, "convert_quality", 92)))
        self.quality.valueChanged.connect(lambda _v: self._update())
        row.addWidget(self.quality_label)
        row.addWidget(self.quality, 1)
        layout.addLayout(row)

        layout.addWidget(QLabel("Originals:"))
        self.keep = QRadioButton("Keep them")
        self.recycle = QRadioButton("Send them to the Recycle Bin")
        (self.recycle if getattr(settings, "convert_recycle", False) else self.keep).setChecked(True)
        layout.addWidget(self.keep)
        layout.addWidget(self.recycle)

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        note = QLabel("Dates, keywords, labels and other metadata are copied to the new files. "
                      "Each new file goes next to its original with the same name.")
        note.setWordWrap(True)
        note.setProperty("hint", True)
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._update()

    def to_convert(self) -> list[str]:
        return [p for p in self.paths if self._needs(p, self.target.currentText())]

    def _update(self) -> None:
        jpg = self.target.currentText() == "JPG"
        self.quality.setEnabled(jpg)
        self.quality_label.setText(f"JPG quality: {self.quality.value()}" if jpg else "PNG is lossless")
        todo = self.to_convert()
        skipped = len(self.paths) - len(todo)
        text = f"{len(todo)} file{'s' if len(todo) != 1 else ''} will be converted to {self.target.currentText()}."
        if skipped:
            text += f" {skipped} skipped (already {self.target.currentText()}, or a video)."
        self.summary.setText(text)
        self.ok.setText(f"Convert {len(todo)}")
        self.ok.setEnabled(bool(todo))

    def _accept(self) -> None:
        self.settings.convert_target = self.target.currentText()
        self.settings.convert_quality = self.quality.value()
        self.settings.convert_recycle = self.recycle.isChecked()
        self.accept()


class HotkeyDialog(QDialog):
    """Choose the keyboard shortcut for each label."""

    NAMES = ["Red", "Yellow", "Green", "Blue", "Purple", "Star", "Bookmark", "None"]
    TITLES = {"None": "None (remove all labels)", "Star": "⭐ Star", "Bookmark": "🔖 Bookmark"}

    def __init__(self, hotkeys: dict[str, str], defaults: dict[str, str],
                 reserved: dict[str, str] | None = None, parent: QWidget | None = None):
        from PySide6.QtGui import QKeySequence
        from PySide6.QtWidgets import QFormLayout, QKeySequenceEdit

        super().__init__(parent)
        self.setWindowTitle("Label hotkeys")
        self.defaults = defaults
        self.reserved = reserved or {}
        self._seq = QKeySequence
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Click a box and press the keys you want. Clear a box to have no hotkey."))
        form = QFormLayout()
        self.edits = {}
        for name in self.NAMES:
            edit = QKeySequenceEdit(QKeySequence(hotkeys.get(name, "")))
            edit.setMaximumSequenceLength(1)
            edit.setClearButtonEnabled(True)
            self.edits[name] = edit
            form.addRow(self.TITLES.get(name, name) + ":", edit)
        layout.addLayout(form)
        self.error = QLabel()
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
                                   | QDialogButtonBox.StandardButton.RestoreDefaults)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(self._defaults)
        layout.addWidget(buttons)

    def _defaults(self) -> None:
        for name, edit in self.edits.items():
            edit.setKeySequence(self._seq(self.defaults.get(name, "")))

    def hotkeys(self) -> dict[str, str]:
        from PySide6.QtGui import QKeySequence

        return {name: edit.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
                for name, edit in self.edits.items()}

    def _accept(self) -> None:
        seen: dict[str, str] = {}
        for name, keys in self.hotkeys().items():
            if keys in self.reserved:
                self.error.setText(f"<span style='color:#e5484d'>{keys} is already used for "
                                   f"{self.reserved[keys]}.</span>")
                return
            if keys and keys in seen:
                self.error.setText(f"<span style='color:#e5484d'>{keys} is used for both "
                                   f"{seen[keys]} and {name}.</span>")
                return
            if keys:
                seen[keys] = name
        self.accept()


class _NamesRelay(QObject):
    """Carries Steam store names from the lookup thread back to the UI thread."""

    done = Signal(dict)


class SteamImportDialog(QDialog):
    """Pick the Steam folder, account and destination; shows how many screenshots are new."""

    def __init__(self, settings, parent: QWidget | None = None):  # type: ignore[no-untyped-def]
        from PySide6.QtWidgets import QComboBox, QFormLayout

        from ..core import steam

        super().__init__(parent)
        self._steam = steam
        self.settings = settings
        self.setWindowTitle("Import Steam screenshots")
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        intro = QLabel("Copies the screenshots Steam keeps on this PC (all of them, uploaded or not) straight "
                       "into the folder you choose. Steam's own copies are not changed, and screenshots you've "
                       "already imported are skipped.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()
        self.steam_path = QLineEdit(settings.steam_path or steam.find_steam() or "")
        self.steam_path.setPlaceholderText(r"e.g. C:\Program Files (x86)\Steam")
        self.steam_path.editingFinished.connect(self._reload_accounts)
        form.addRow("Steam folder:", self._with_browse(self.steam_path, "Steam folder"))
        self.account = QComboBox()
        self.account.currentIndexChanged.connect(lambda _i: self._update())
        form.addRow("Steam account:", self.account)
        self.dest = QLineEdit(settings.steam_dest)
        self.dest.setPlaceholderText(r"e.g. D:\Pictures\Steam")
        self.dest.textChanged.connect(lambda _t: self._update())
        form.addRow("Save into:", self._with_browse(self.dest, "Save Steam screenshots into"))
        layout.addLayout(form)

        layout.addWidget(QLabel("<b>Also look in</b> (optional):"))
        hint = QLabel("Add folders with more screenshots, e.g. the folder your Steam Deck's screenshots "
                      "sync into, or a game's own screenshot folder. Subfolders are included.")
        hint.setWordWrap(True)
        hint.setProperty("hint", True)
        layout.addWidget(hint)
        row = QHBoxLayout()
        self.extra = QListWidget()
        self.extra.setMaximumHeight(64)
        for folder in settings.steam_extra_folders:
            self.extra.addItem(folder)
        row.addWidget(self.extra, 1)
        buttons_col = QVBoxLayout()
        add = QPushButton("Add folder…")
        add.clicked.connect(self._add_extra)
        remove = QPushButton("Remove")
        remove.clicked.connect(self._remove_extra)
        buttons_col.addWidget(add)
        buttons_col.addWidget(remove)
        buttons_col.addStretch(1)
        row.addLayout(buttons_col)
        layout.addLayout(row)

        self.set_date = QCheckBox("Set Date taken (and Windows Created date) from the screenshot's file name")
        self.set_date.setChecked(settings.steam_set_date)
        self.keyword = QCheckBox("Add the game's name as a keyword")
        self.keyword.setChecked(settings.steam_keyword)
        for box in (self.set_date, self.keyword):
            layout.addWidget(box)

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        from PySide6.QtWidgets import QTreeWidget

        self.games = QTreeWidget()
        self.games.setHeaderLabels(["Game", "Screenshots", "Newest"])
        self.games.setRootIsDecorated(False)
        self.games.setMaximumHeight(150)
        self.games.setColumnWidth(0, 280)
        layout.addWidget(self.games)
        mark_row = QHBoxLayout()
        self.mark_btn = QPushButton("Mark older ones as imported…")
        self.mark_btn.setToolTip("Already have these screenshots (e.g. imported, then moved elsewhere)? "
                                 "Mark everything taken before a date and time as imported.")
        self.mark_btn.clicked.connect(self._mark_older)
        mark_row.addWidget(self.mark_btn)
        mark_row.addStretch(1)
        layout.addLayout(mark_row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.plan: list = []
        self.shots: list = []
        self.seen_in_dest: set[str] = set()
        self._asked: set[str] = set()  # app ids already looked up in the Steam store
        self._relay = _NamesRelay(self)
        self._relay.done.connect(self._got_names)
        self._reload_accounts()

    def _with_browse(self, edit: QLineEdit, title: str) -> QWidget:
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(edit, 1)
        button = QPushButton("Browse…")

        def browse() -> None:
            folder = QFileDialog.getExistingDirectory(self, title, edit.text())
            if folder:
                edit.setText(os.path.normpath(folder))
                edit.editingFinished.emit()

        button.clicked.connect(browse)
        row.addWidget(button)
        return box

    def extra_folders(self) -> list[str]:
        return [self.extra.item(i).text() for i in range(self.extra.count())]

    def _add_extra(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Also look for screenshots in")
        if folder and os.path.normpath(folder) not in self.extra_folders():
            self.extra.addItem(os.path.normpath(folder))
            self._update()

    def _remove_extra(self) -> None:
        for item in self.extra.selectedItems():
            self.extra.takeItem(self.extra.row(item))
        self._update()

    def _reload_accounts(self) -> None:
        self.account.blockSignals(True)
        self.account.clear()
        ids = self._steam.accounts(self.steam_path.text().strip()) if self.steam_path.text().strip() else []
        if len(ids) > 1:
            self.account.addItem("All accounts", "")
        for acct in ids:
            self.account.addItem(acct, acct)
        index = self.account.findData(self.settings.steam_account)
        self.account.setCurrentIndex(max(0, index))
        self.account.blockSignals(False)
        self._update()

    def _update(self) -> None:
        path = self.steam_path.text().strip()
        dest = self.dest.text().strip()
        self.plan = []
        self.games.clear()
        if (not path or self.account.count() == 0) and not self.extra_folders():
            self.summary.setText("<span style='color:#e5484d'>No Steam screenshots found there. "
                                 "Choose your Steam folder (the one that contains “userdata”).</span>")
            self.ok.setEnabled(False)
            self.ok.setText("Import")
            self.mark_btn.setEnabled(False)
            return
        shots = self._steam.find_screenshots(
            path if self.account.count() else "", self.account.currentData() or None,
            self.extra_folders(), self.settings.steam_game_names)
        self._look_up_names(shots)
        self.shots = shots
        rows = self._steam.per_game(shots)
        from PySide6.QtWidgets import QTreeWidgetItem

        for game, count, newest in rows:
            self.games.addTopLevelItem(QTreeWidgetItem(
                [game, str(count), dates.format_display(newest, "%m-%d-%Y %I:%M %p") if newest else ""]))
        games = len(rows)
        text = f"{len(shots)} screenshot{'s' if len(shots) != 1 else ''} from {games} game{'s' if games != 1 else ''}."
        if dest:
            from ..core.templates import match_any

            templates = self.settings.templates

            def date_of_name(name: str):  # type: ignore[no-untyped-def]
                found = match_any(templates, name)
                return found[1] if found else None

            # Imported before: in the log, or still in the folder (even if renamed or dated since).
            self.seen_in_dest = self._steam.found_in_dest(shots, dest, date_of_name)
            skip = self._steam.load_log(self.log_path()) | self.seen_in_dest
            self.plan = self._steam.plan_import(shots, dest, skip)
            done = len(shots) - len(self.plan)
            text += f" <b>{len(self.plan)} new</b> to import"
            text += f" ({done} imported before)." if done else "."
        else:
            text += " Choose where to save them."
        self.summary.setText(text)
        self.ok.setText(f"Import {len(self.plan)}" if dest else "Import")
        self.mark_btn.setEnabled(bool(self.plan))
        self.ok.setEnabled(bool(dest and self.plan))

    def _mark_older(self) -> None:
        """One-time catch-up: mark every screenshot taken before a chosen moment as imported."""
        from datetime import datetime

        from PySide6.QtCore import QDateTime
        from PySide6.QtWidgets import QDateTimeEdit

        pending = {id(shot) for shot, _ in self.plan}
        shots = [s for s in self.shots if s.taken and id(s) in pending]
        dlg = QDialog(self)
        dlg.setWindowTitle("Mark older ones as imported")
        layout = QVBoxLayout(dlg)
        text = QLabel("Screenshots taken <b>before</b> this date and time count as already imported "
                      "and won't be offered again:")
        text.setWordWrap(True)
        layout.addWidget(text)
        when = QDateTimeEdit()
        when.setCalendarPopup(True)
        when.setDisplayFormat("MM-dd-yyyy hh:mm AP")
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        when.setDateTime(QDateTime(today))
        layout.addWidget(when)
        count = QLabel()
        layout.addWidget(count)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Mark as imported")
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)

        def older() -> list:
            cutoff = when.dateTime().toPython()
            return [s for s in shots if s.taken < cutoff]

        def recount() -> None:
            n = len(older())
            count.setText(f"<b>{n}</b> will be marked as imported; <b>{len(self.plan) - n}</b> stay new.")

        when.dateTimeChanged.connect(lambda _dt: recount())
        recount()
        self._mark_dialog = dlg  # for tests
        if dlg.exec():
            self._steam.add_to_log(self.log_path(), {self._steam.shot_key(s) for s in older()})
            self._update()

    def log_path(self):  # type: ignore[no-untyped-def]
        """The list of screenshots imported before, next to the settings file."""
        return self.settings.path.parent / "steam_imported.txt"

    def _look_up_names(self, shots: list) -> None:
        """Name games that aren't installed on this PC (e.g. played on a Steam Deck) from the
        Steam store, in the background; the list refreshes when the names arrive."""
        missing = [a for a in self._steam.unnamed_app_ids(shots)
                   if a not in self._asked and a not in self.settings.steam_game_names]
        if not missing:
            return
        self._asked.update(missing)
        import threading

        relay, fetch = self._relay, self._steam.fetch_store_names

        def work() -> None:
            names = fetch(missing[:50])
            try:
                relay.done.emit(names)
            except RuntimeError:  # the dialog was closed meanwhile
                pass

        threading.Thread(target=work, daemon=True).start()

    def _got_names(self, names: dict) -> None:
        if not names:
            return
        self.settings.steam_game_names.update(names)
        self.settings.save()
        if any(names.values()):
            self._update()

    def _accept(self) -> None:
        s = self.settings
        s.steam_path = self.steam_path.text().strip()
        s.steam_account = self.account.currentData() or ""
        s.steam_dest = self.dest.text().strip()
        s.steam_extra_folders = self.extra_folders()
        s.steam_set_date = self.set_date.isChecked()
        s.steam_keyword = self.keyword.isChecked()
        self.accept()


class _ScanRelay(QObject):
    """Carries folder-scan results from the scanning thread back to the UI thread."""

    done = Signal(object, int)  # videos, generation


class VideoImportDialog(QDialog):
    """Pick folders (network folders too) to copy videos from, subfolders included,
    and the folder to put them in. Shows how many are new."""

    def __init__(self, settings, parent: QWidget | None = None):  # type: ignore[no-untyped-def]
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QFormLayout, QTreeWidget

        from ..core import folder_import

        super().__init__(parent)
        self._fi = folder_import
        self.settings = settings
        self.setWindowTitle("Import videos")
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        intro = QLabel("Brings the videos from these folders <b>and all their subfolders</b> straight into the "
                       "folder you choose. Videos you've already imported are skipped, so you can run it "
                       "whenever you like. Network folders work too (a mapped drive, or \\\\server\\share).")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        layout.addWidget(QLabel("<b>Get videos from:</b>"))
        row = QHBoxLayout()
        self.sources = QListWidget()
        self.sources.setMaximumHeight(72)
        for folder in settings.video_sources:
            self.sources.addItem(folder)
        row.addWidget(self.sources, 1)
        col = QVBoxLayout()
        add = QPushButton("Add folder…")
        add.clicked.connect(self._add_source)
        remove = QPushButton("Remove")
        remove.clicked.connect(self._remove_source)
        col.addWidget(add)
        col.addWidget(remove)
        col.addStretch(1)
        row.addLayout(col)
        layout.addLayout(row)

        form = QFormLayout()
        self.dest = QLineEdit(settings.video_dest)
        self.dest.setPlaceholderText(r"e.g. C:\Users\you\Pictures\Camera Roll")
        self.dest.textChanged.connect(lambda _t: self._rescan_timer.start())
        box = QWidget()
        dest_row = QHBoxLayout(box)
        dest_row.setContentsMargins(0, 0, 0, 0)
        dest_row.addWidget(self.dest, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_dest)
        dest_row.addWidget(browse)
        form.addRow("Save into:", box)
        layout.addLayout(form)

        self.move_box = QCheckBox("Move instead of copy (removes them from the original folders)")
        self.move_box.setToolTip("Files removed from a network folder don't go to a Recycle Bin.")
        self.move_box.setChecked(settings.video_move)
        layout.addWidget(self.move_box)

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.folders = QTreeWidget()
        self.folders.setHeaderLabels(["Folder", "New videos", "Size"])
        self.folders.setRootIsDecorated(False)
        self.folders.setMaximumHeight(150)
        self.folders.setColumnWidth(0, 320)
        layout.addWidget(self.folders)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok.setText("Import")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.videos: list = []
        self.plan: list = []
        self.scanning = False
        self._generation = 0
        self._relay = _ScanRelay(self)
        self._relay.done.connect(self._scanned)
        self._rescan_timer = QTimer(self)  # typing a path: scan once it stops changing
        self._rescan_timer.setSingleShot(True)
        self._rescan_timer.setInterval(400)
        self._rescan_timer.timeout.connect(self._scan)
        self._scan()

    # -- folders --

    def source_folders(self) -> list[str]:
        return [self.sources.item(i).text() for i in range(self.sources.count())]

    def log_path(self):  # type: ignore[no-untyped-def]
        return self.settings.path.parent / "video_imported.txt"

    def _add_source(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Get videos from (subfolders included)")
        if folder and os.path.normpath(folder) not in self.source_folders():
            self.sources.addItem(os.path.normpath(folder))
            self._scan()

    def _remove_source(self) -> None:
        for item in self.sources.selectedItems():
            self.sources.takeItem(self.sources.row(item))
        self._scan()

    def _browse_dest(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Save videos into", self.dest.text())
        if folder:
            self.dest.setText(os.path.normpath(folder))

    # -- scanning (in the background: network folders can be slow) --

    def _scan(self) -> None:
        self._generation += 1
        generation, relay = self._generation, self._relay
        folders, dest = self.source_folders(), self.dest.text().strip()
        self.videos, self.plan = [], []
        self.folders.clear()
        self.ok.setEnabled(False)
        if not folders:
            self.scanning = False
            self.summary.setText("Add the folder (or folders) to get videos from.")
            return
        self.scanning = True
        self.summary.setText("Looking for videos… (network folders can take a moment)")
        import threading

        find = self._fi.find_videos

        def work() -> None:
            videos = find(folders, dest, cancelled=lambda: generation != self._generation)
            try:
                relay.done.emit(videos, generation)
            except RuntimeError:  # the dialog was closed meanwhile
                pass

        threading.Thread(target=work, daemon=True).start()

    def _scanned(self, videos: list, generation: int) -> None:
        if generation != self._generation:
            return
        self.videos = videos
        self.scanning = False
        self._replan()

    def _replan(self) -> None:
        dest = self.dest.text().strip()
        self.folders.clear()
        n = len(self.videos)
        text = f"{n} video{'s' if n != 1 else ''} found."
        if not dest:
            self.plan = []
            self.summary.setText(text + " Choose where to save them.")
            self.ok.setEnabled(False)
            return
        self.plan = self._fi.plan_import(self.videos, dest, self._fi.load_log(self.log_path()))
        done = n - len(self.plan)
        size = sum(v.size for v, _ in self.plan)
        text += f" <b>{len(self.plan)} new</b> to import ({_size(size)})"
        text += f", {done} imported before." if done else "."
        self.summary.setText(text)
        by_folder: dict[str, list] = {}
        for video, _target in self.plan:
            by_folder.setdefault(os.path.dirname(video.path), []).append(video)
        from PySide6.QtWidgets import QTreeWidgetItem

        for folder, vids in sorted(by_folder.items()):
            item = QTreeWidgetItem([folder, str(len(vids)), _size(sum(v.size for v in vids))])
            item.setToolTip(0, folder)
            self.folders.addTopLevelItem(item)
        self.ok.setText(f"Import {len(self.plan)}")
        self.ok.setEnabled(bool(self.plan))

    def _accept(self) -> None:
        s = self.settings
        s.video_sources = self.source_folders()
        s.video_dest = self.dest.text().strip()
        s.video_move = self.move_box.isChecked()
        if s.video_move and QMessageBox.question(
                self, "Move videos",
                f"Move {len(self.plan)} videos? They'll be removed from the original folders "
                "(files on a network folder can't be restored from the Recycle Bin).") \
                != QMessageBox.StandardButton.Yes:
            return
        self.accept()


def _size(n: int) -> str:
    for unit in ("bytes", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "bytes" else f"{n:.1f} {unit}"
        n /= 1024  # type: ignore[assignment]
    return ""
