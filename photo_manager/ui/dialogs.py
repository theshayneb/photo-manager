"""Template editor and the Move-to-folder picker."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QPushButton, QTableWidget, QTableWidgetItem,
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
