"""Sidebar panels: preview/info, color label, date taken, date from filename,
rename, and keyword buttons."""

from __future__ import annotations

import os
from datetime import datetime
from typing import TYPE_CHECKING, Protocol

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QMenu, QMessageBox, QPushButton, QSizePolicy, QToolButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..core import dates
from ..core.media import metadata_writable
from ..core.metadata import LABELS, date_args, keyword_args, label_args
from ..core.templates import match_any
from .flowlayout import FlowLayout
from .grid import LABEL_COLORS, Item

if TYPE_CHECKING:
    from ..core.settings import Settings

PREVIEW_ROWS = 300


class Controller(Protocol):
    settings: "Settings"
    exiftool_ok: bool

    def write_metadata(self, jobs: list[tuple[str, list[str]]], what: str) -> None: ...
    def rename_files(self, plan: dict[str, str]) -> None: ...
    def edit_templates(self) -> None: ...


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setProperty("hint", True)
    return label


def _repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def _writable(items: list[Item]) -> list[Item]:
    return [i for i in items if metadata_writable(i.path)]


# --------------------------------------------------------------------------
# Preview / info
# --------------------------------------------------------------------------

class InfoPanel(QWidget):
    def __init__(self, ctl: Controller):
        super().__init__()
        self.ctl = ctl
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(150)
        self.preview.setFrameShape(QFrame.Shape.StyledPanel)
        self.name = QLabel()
        self.name.setWordWrap(True)
        self.name.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.details = _hint("")
        layout.addWidget(self.preview)
        layout.addWidget(self.name)
        layout.addWidget(self.details)

    def refresh(self, items: list[Item]) -> None:
        fmt = self.ctl.settings.display_format
        if not items:
            self.preview.clear()
            self.preview.setText("Nothing selected")
            self.name.setText("")
            self.details.setText("")
            return
        if len(items) > 1:
            self.preview.clear()
            self.preview.setText(f"{len(items)} files selected")
            self.name.setText("")
            self.details.setText(f"{sum(i.size for i in items) / 1_048_576:.1f} MB total")
            return
        item = items[0]
        if item.thumb is not None:
            self.preview.setPixmap(item.thumb.scaled(
                300, 170, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
        else:
            self.preview.setText("No preview")
        self.name.setText(f"<b>{item.name}</b>")
        lines = []
        meta = item.meta
        if meta and meta.image_size:
            lines.append(meta.image_size)
        lines.append(f"{item.size / 1_048_576:.2f} MB")
        if meta and meta.file_created:
            lines.append(f"Windows created: {dates.format_display(meta.file_created, fmt)}")
        lines.append(f"Modified: {dates.format_display(datetime.fromtimestamp(item.mtime), fmt)}")
        self.details.setText("\n".join(lines))


# --------------------------------------------------------------------------
# Color labels
# --------------------------------------------------------------------------

class LabelPanel(QWidget):
    def __init__(self, ctl: Controller):
        super().__init__()
        self.ctl = ctl
        self.items: list[Item] = []
        row = QHBoxLayout(self)
        self.buttons: dict[str, QPushButton] = {}
        for n, label in enumerate(LABELS, start=1):
            btn = QPushButton()
            btn.setFixedSize(30, 20)
            btn.setToolTip(f"{label}  (Ctrl+{n})")
            btn.setCheckable(True)
            color = LABEL_COLORS[label].name()
            btn.setStyleSheet(
                f"QPushButton {{ background: {color}; border: 2px solid transparent; border-radius: 4px; }}"
                f"QPushButton:checked {{ border: 3px solid palette(text); }}")
            btn.clicked.connect(lambda _=False, name=label: self.apply(name))
            row.addWidget(btn)
            self.buttons[label] = btn
        clear = QPushButton("None")
        clear.setToolTip("Remove label  (Ctrl+0)")
        clear.clicked.connect(lambda: self.apply(""))
        row.addWidget(clear)

    def refresh(self, items: list[Item]) -> None:
        self.items = items
        labels = {i.meta.label for i in items if i.meta}
        for label, btn in self.buttons.items():
            btn.setChecked(labels == {label})
        self.setEnabled(self.ctl.exiftool_ok and bool(_writable(items)))

    def apply(self, label: str) -> None:
        targets = _writable(self.items)
        if not targets:
            return
        # Clicking the label every selected photo already has clears it.
        if label and all(i.meta and i.meta.label == label for i in targets):
            label = ""
        self.ctl.write_metadata([(i.path, label_args(label)) for i in targets],
                                f"label {label or 'cleared'}")


# --------------------------------------------------------------------------
# Date taken (typed, or from filename)
# --------------------------------------------------------------------------

class DatePanel(QWidget):
    def __init__(self, ctl: Controller):
        super().__init__()
        self.ctl = ctl
        self.items: list[Item] = []
        layout = QVBoxLayout(self)

        self.current = QLabel()
        self.current.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.current)

        row = QHBoxLayout()
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("Type a date, e.g. 6/14/24 6:32 pm")
        self.edit.textChanged.connect(self._update_parsed)
        self.edit.returnPressed.connect(self.apply_typed)
        self.apply_btn = QPushButton("Set")
        self.apply_btn.clicked.connect(self.apply_typed)
        row.addWidget(self.edit, 1)
        row.addWidget(self.apply_btn)
        layout.addLayout(row)
        self.parsed = _hint("")
        layout.addWidget(self.parsed)

        self.file_dates = QCheckBox("Also set Windows Created/Modified dates")
        self.file_dates.setChecked(ctl.settings.set_file_dates)
        self.file_dates.toggled.connect(self._toggle_file_dates)
        layout.addWidget(self.file_dates)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line)

        layout.addWidget(QLabel("<b>From filename</b>"))
        row = QHBoxLayout()
        self.template_combo = QComboBox()
        self.template_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.template_combo.currentIndexChanged.connect(lambda _i: self._update_filename_preview())
        edit_templates = QToolButton()
        edit_templates.setText("Edit…")
        edit_templates.clicked.connect(ctl.edit_templates)
        row.addWidget(self.template_combo, 1)
        row.addWidget(edit_templates)
        layout.addLayout(row)

        self.preview = QTreeWidget()
        self.preview.setHeaderLabels(["File", "New date taken"])
        self.preview.setRootIsDecorated(False)
        self.preview.setFixedHeight(60)
        self.preview.setColumnWidth(0, 150)
        layout.addWidget(self.preview)
        self.filename_btn = QPushButton("Set date from filename")
        self.filename_btn.clicked.connect(self.apply_filename)
        layout.addWidget(self.filename_btn)
        self._filename_plan: dict[str, datetime] = {}
        self.reload_templates()

    # -- state --

    def reload_templates(self) -> None:
        current = self.template_combo.currentText()
        self.template_combo.blockSignals(True)
        self.template_combo.clear()
        self.template_combo.addItem("Auto (try every template)")
        for template in self.ctl.settings.templates:
            self.template_combo.addItem(template.name)
        idx = self.template_combo.findText(current)
        self.template_combo.setCurrentIndex(max(0, idx))
        self.template_combo.blockSignals(False)
        self._update_filename_preview()

    def _toggle_file_dates(self, on: bool) -> None:
        self.ctl.settings.set_file_dates = on

    def refresh(self, items: list[Item]) -> None:
        self.items = items
        fmt = self.ctl.settings.display_format
        loaded = [i for i in items if i.meta is not None]
        values = {i.meta.date_taken for i in loaded}  # type: ignore[union-attr]
        if not items:
            text = "Select photos to see their date."
        elif len(loaded) < len(items):
            text = "Reading…"
        elif len(values) == 1:
            value = next(iter(values))
            if value is None:
                text = "<b>No date taken</b>"
            else:
                source = loaded[0].meta.date_source  # type: ignore[union-attr]
                text = f"<b>{dates.format_display(value, fmt)}</b>  <span style='color:gray'>({source})</span>"
        else:
            text = f"<b>Different dates</b> on {len(items)} files"
        self.current.setText(text)
        if len(items) == 1 and len(values) == 1 and next(iter(values)) is not None:
            self.edit.setText(dates.format_display(next(iter(values)), fmt))
        else:
            self.edit.clear()
        self._update_parsed()
        self._update_filename_preview()
        writable = bool(_writable(items)) and self.ctl.exiftool_ok
        for widget in (self.edit, self.apply_btn, self.filename_btn):
            widget.setEnabled(writable)

    def _update_parsed(self) -> None:
        text = self.edit.text().strip()
        if not text:
            self.parsed.setText("")
            return
        try:
            dt = dates.parse_loose(text)
        except ValueError:
            self.parsed.setText("<span style='color:#e5484d'>Can't read that date</span>")
            return
        self.parsed.setText(f"→ {dt:%A, %B} {dt.day}, {dt.year}  {dates.format_display(dt, '%I:%M:%S %p')}")

    def _templates(self):  # type: ignore[no-untyped-def]
        templates = self.ctl.settings.templates
        idx = self.template_combo.currentIndex()
        return templates if idx <= 0 else templates[idx - 1 : idx]

    def _update_filename_preview(self) -> None:
        self.preview.clear()
        self._filename_plan = {}
        templates = self._templates()
        fmt = self.ctl.settings.display_format
        rows = []
        for item in self.items:
            found = match_any(templates, item.name)
            if found:
                self._filename_plan[item.path] = found[1]
            if len(rows) < PREVIEW_ROWS:
                if found:
                    text = dates.format_display(found[1], fmt)
                    tip = f"Template: {found[0].name}"
                else:
                    text, tip = "no match — skipped", ""
                row = QTreeWidgetItem([item.name, text])
                row.setToolTip(0, item.name)
                row.setToolTip(1, tip)
                if not found:
                    row.setForeground(1, Qt.GlobalColor.gray)
                rows.append(row)
        self.preview.addTopLevelItems(rows)
        # Only as tall as needed (up to 6 rows), so the sidebar stays short.
        shown = max(1, min(6, self.preview.topLevelItemCount() + (1 if len(self.items) > PREVIEW_ROWS else 0)))
        row_h = self.preview.sizeHintForRow(0) if self.preview.topLevelItemCount() else 18
        self.preview.setFixedHeight(self.preview.header().sizeHint().height() + shown * max(row_h, 16) + 6)
        if len(self.items) > PREVIEW_ROWS:
            self.preview.addTopLevelItem(QTreeWidgetItem([f"…and {len(self.items) - PREVIEW_ROWS} more", ""]))
        n = len([p for p in self._filename_plan if metadata_writable(p)])
        self.filename_btn.setText(f"Set date from filename ({n} file{'s' if n != 1 else ''})")
        self.filename_btn.setEnabled(n > 0 and self.ctl.exiftool_ok)

    # -- actions --

    def _write(self, new_dates: dict[str, datetime], what: str) -> None:
        set_files = self.file_dates.isChecked()
        jobs = [(p, date_args(p, dt, set_files)) for p, dt in new_dates.items() if metadata_writable(p)]
        if jobs:
            self.ctl.write_metadata(jobs, what)

    def apply_typed(self) -> None:
        try:
            dt = dates.parse_loose(self.edit.text())
        except ValueError:
            self.parsed.setText("<span style='color:#e5484d'>Can't read that date</span>")
            return
        self._write({i.path: dt for i in self.items}, "date taken")

    def apply_filename(self) -> None:
        self._write(dict(self._filename_plan), "date from filename")


# --------------------------------------------------------------------------
# Rename by date
# --------------------------------------------------------------------------

RENAME_SOURCES = {
    "taken": "Date taken (EXIF DateTimeOriginal)",
    "created": "EXIF Create Date (digitized)",
    "file_created": "Windows Created date",
    "file_modified": "Windows Modified date",
}


def rename_date(item: Item, source: str) -> datetime | None:
    meta = item.meta
    if source == "file_modified":
        return datetime.fromtimestamp(item.mtime).replace(microsecond=0)
    if meta is None:
        return None
    if source == "created":
        return meta.create_date
    if source == "file_created":
        return meta.file_created
    return meta.date_taken


class RenamePanel(QWidget):
    def __init__(self, ctl: Controller):
        super().__init__()
        self.ctl = ctl
        self.items: list[Item] = []
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Date to use:"))
        self.source = QComboBox()
        for key, label in RENAME_SOURCES.items():
            self.source.addItem(label, key)
        self.source.setCurrentIndex(max(0, self.source.findData(ctl.settings.rename_source)))
        self.source.currentIndexChanged.connect(self._source_changed)
        layout.addWidget(self.source)
        layout.addWidget(QLabel("New name:"))
        self.pattern = QLineEdit(ctl.settings.rename_pattern)
        self.pattern.textChanged.connect(self._changed)
        layout.addWidget(self.pattern)
        layout.addWidget(_hint("{YYYY} {YY} {MM} {DD} {HH} {mm} {ss} · {hh} {AMPM} for 12-hour · "
                               "{name} = current name"))
        self.example = _hint("")
        layout.addWidget(self.example)
        self.button = QPushButton("Rename")
        self.button.clicked.connect(self.apply)
        layout.addWidget(self.button)

    def _source_changed(self) -> None:
        self.ctl.settings.rename_source = self.source.currentData()
        self.refresh(self.items)

    def _changed(self, text: str) -> None:
        self.ctl.settings.rename_pattern = text
        self.refresh(self.items)

    def _names(self) -> dict[str, str]:
        pattern = self.pattern.text().strip()
        if not pattern:
            return {}
        source = self.source.currentData()
        names = {}
        for item in self.items:
            dt = rename_date(item, source)
            if dt is not None:
                names[item.path] = dates.format_pattern(pattern, dt, os.path.splitext(item.name)[0])
        return names

    def refresh(self, items: list[Item]) -> None:
        self.items = items
        names = self._names()
        if names:
            first = next(iter(names))
            example = names[first] + os.path.splitext(first)[1]
            skipped = len(items) - len(names)
            text = f"{os.path.basename(first)}\n→ {example}"
            if skipped:
                text += f"\n{skipped} without that date will be skipped"
            self.example.setText(text)
        else:
            self.example.setText("Selected files don't have that date." if items else "")
        self.button.setText(f"Rename {len(names)} file{'s' if len(names) != 1 else ''}")
        self.button.setEnabled(bool(names))

    def apply(self) -> None:
        from ..core.fileops import plan_renames

        plan = plan_renames(self._names())
        if plan:
            self.ctl.rename_files(plan)


# --------------------------------------------------------------------------
# Keyword buttons
# --------------------------------------------------------------------------

class KeywordPanel(QWidget):

    def __init__(self, ctl: Controller):
        super().__init__()
        self.ctl = ctl
        self.items: list[Item] = []
        layout = QVBoxLayout(self)

        self.add_edit = QLineEdit()
        self.add_edit.setPlaceholderText("Click here to add keywords")
        self.add_edit.setToolTip("Adds to the selected files and to this set. Separate several with commas.")
        self.add_edit.returnPressed.connect(self._add_typed)
        layout.addWidget(self.add_edit)

        row = QHBoxLayout()
        self.set_combo = QComboBox()
        self.set_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.set_combo.currentTextChanged.connect(self._set_changed)
        menu_btn = QToolButton()
        menu_btn.setText("⋯")
        menu_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(menu_btn)
        menu.addAction("New set…", self._new_set)
        menu.addAction("Edit this set…", self._edit_set)
        menu.addAction("Delete set", self._delete_set)
        menu.addSeparator()
        menu.addAction("Add the selection's keywords to this set", self._adopt_keywords)
        menu.addAction("Sort this set A–Z", self._sort_set)
        menu_btn.setMenu(menu)
        row.addWidget(self.set_combo, 1)
        row.addWidget(menu_btn)
        layout.addLayout(row)

        self.grid_host = QWidget()
        self.grid = FlowLayout(self.grid_host, spacing=3)
        layout.addWidget(self.grid_host)

        self.other_title = _hint("Also on the selection (click to remove):")
        layout.addWidget(self.other_title)
        self.chips_host = QWidget()
        self.chips = FlowLayout(self.chips_host)
        layout.addWidget(self.chips_host)

        self.buttons: dict[str, QPushButton] = {}
        self._reload_sets()

    # -- sets --

    @property
    def keyword_set(self) -> list[str]:
        return self.ctl.settings.keyword_sets.setdefault(self.ctl.settings.current_keyword_set, [])

    def _reload_sets(self) -> None:
        self.set_combo.blockSignals(True)
        self.set_combo.clear()
        self.set_combo.addItems(list(self.ctl.settings.keyword_sets))
        self.set_combo.setCurrentText(self.ctl.settings.current_keyword_set)
        self.set_combo.blockSignals(False)
        self._build_buttons()

    def _set_changed(self, name: str) -> None:
        if name:
            self.ctl.settings.current_keyword_set = name
            self._build_buttons()

    def _new_set(self) -> None:
        name, ok = QInputDialog.getText(self, "New keyword set", "Name:")
        name = name.strip()
        if ok and name and name not in self.ctl.settings.keyword_sets:
            self.ctl.settings.keyword_sets[name] = []
            self.ctl.settings.current_keyword_set = name
            self._reload_sets()

    def _edit_set(self) -> None:
        from .dialogs import KeywordSetDialog

        old = self.ctl.settings.current_keyword_set
        sets = self.ctl.settings.keyword_sets
        dlg = KeywordSetDialog(old, list(sets.get(old, [])), [k for k in sets if k != old], self)
        if not dlg.exec():
            return
        name, keywords = dlg.result_value()
        self.ctl.settings.keyword_sets = {(name if k == old else k): (keywords if k == old else v)
                                          for k, v in sets.items()}
        self.ctl.settings.current_keyword_set = name
        self._reload_sets()

    def _delete_set(self) -> None:
        sets = self.ctl.settings.keyword_sets
        name = self.ctl.settings.current_keyword_set
        if len(sets) <= 1:
            QMessageBox.information(self, "Keyword sets", "You need at least one set.")
            return
        if QMessageBox.question(self, "Delete set", f"Delete the set “{name}”?\n"
                                "(Keywords already on photos are not touched.)") != QMessageBox.StandardButton.Yes:
            return
        del sets[name]
        self.ctl.settings.current_keyword_set = next(iter(sets))
        self._reload_sets()

    def _adopt_keywords(self) -> None:
        for kw in self._selection_counts():
            self._remember(kw)
        self._build_buttons()

    def _sort_set(self) -> None:
        self.keyword_set.sort(key=str.casefold)
        self._build_buttons()

    def _remember(self, keyword: str) -> str:
        """Add keyword to the current set if new; return its stored spelling."""
        for existing in self.keyword_set:
            if existing.casefold() == keyword.casefold():
                return existing
        self.keyword_set.append(keyword)
        return keyword

    def _forget(self, keyword: str) -> None:
        self.keyword_set[:] = [k for k in self.keyword_set if k != keyword]
        self._build_buttons()

    # -- buttons --

    def _build_buttons(self) -> None:
        self.grid.clear()
        self.buttons = {}
        for kw in self.keyword_set:
            btn = QPushButton(kw)
            btn.setProperty("keyword", True)
            btn.clicked.connect(lambda _=False, k=kw: self.toggle(k))
            btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            btn.customContextMenuRequested.connect(lambda _pos, k=kw, b=btn: self._button_menu(k, b))
            self.grid.addWidget(btn)
            self.buttons[kw.casefold()] = btn
        self.refresh(self.items)

    def _button_menu(self, keyword: str, button: QPushButton) -> None:
        menu = QMenu(self)
        menu.addAction(f"Remove “{keyword}” from this set", lambda: self._forget(keyword))
        menu.exec(button.mapToGlobal(button.rect().bottomLeft()))

    def _selection_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        spelling: dict[str, str] = {}
        for item in self.items:
            for kw in item.meta.keywords if item.meta else []:
                key = kw.casefold()
                spelling.setdefault(key, kw)
                counts[key] = counts.get(key, 0) + 1
        return {spelling[k]: v for k, v in counts.items()}

    def refresh(self, items: list[Item]) -> None:
        self.items = items
        counts = {k.casefold(): v for k, v in self._selection_counts().items()}
        total = len(items)
        for key, btn in self.buttons.items():
            n = counts.get(key, 0)
            state = "all" if total and n == total else "some" if n else "none"
            if btn.property("state") != state:
                btn.setProperty("state", state)
                _repolish(btn)
            btn.setToolTip(f"On {n} of {total} selected" if total else "")

        self.chips.clear()
        others = [kw for kw in self._selection_counts() if kw.casefold() not in self.buttons]
        for kw in sorted(others, key=str.casefold):
            chip = QPushButton(f"{kw}  ×")
            chip.setProperty("chip", True)
            chip.setToolTip(f"Remove “{kw}” from the selected files")
            chip.clicked.connect(lambda _=False, k=kw: self._write(remove=[k]))
            self.chips.addWidget(chip)
        self.other_title.setVisible(bool(others))
        self.chips_host.setVisible(bool(others))
        enabled = self.ctl.exiftool_ok and bool(_writable(items))
        self.grid_host.setEnabled(enabled)
        self.chips_host.setEnabled(enabled)
        self.add_edit.setEnabled(self.ctl.exiftool_ok)

    def toggle(self, keyword: str) -> None:
        targets = _writable(self.items)
        if not targets:
            return
        key = keyword.casefold()
        everyone_has = all(i.meta and key in {k.casefold() for k in i.meta.keywords} for i in targets)
        if everyone_has:
            self._write(remove=[keyword])
        else:
            self._write(add=[keyword])

    def _add_typed(self) -> None:
        words = [w.strip() for w in self.add_edit.text().split(",") if w.strip()]
        if not words:
            return
        stored = [self._remember(w) for w in words]
        self.add_edit.clear()
        self._build_buttons()
        if _writable(self.items):
            self._write(add=stored)

    def _write(self, add: list[str] = (), remove: list[str] = ()) -> None:  # type: ignore[assignment]
        targets = _writable(self.items)
        jobs = []
        for item in targets:
            # Remove every spelling variant the file actually has.
            have = item.meta.keywords if item.meta else []
            rm = [k for k in have if k.casefold() in {r.casefold() for r in remove}]
            jobs.append((item.path, keyword_args(item.path, add=list(add), remove=rm or list(remove))))
        what = f"added {', '.join(add)}" if add else f"removed {', '.join(remove)}"
        self.ctl.write_metadata(jobs, what)


class Section(QWidget):
    """A sidebar panel with a clickable header that collapses it."""

    def __init__(self, key: str, title: str, body: QWidget, collapsed: bool):
        super().__init__()
        self.key = key
        self.body = body
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 6)
        layout.setSpacing(2)
        self.header = QToolButton()
        self.header.setText(title)
        self.header.setCheckable(True)
        self.header.setChecked(not collapsed)
        self.header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.header.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.header.setProperty("section", True)
        self.header.toggled.connect(self._toggled)
        layout.addWidget(self.header)
        if body.layout() is not None:
            body.layout().setContentsMargins(4, 2, 4, 2)
            body.layout().setSpacing(4)
        layout.addWidget(body)
        self._toggled(not collapsed)

    def _toggled(self, open_: bool) -> None:
        self.header.setArrowType(Qt.ArrowType.DownArrow if open_ else Qt.ArrowType.RightArrow)
        self.body.setVisible(open_)

    @property
    def collapsed(self) -> bool:
        return not self.header.isChecked()


PANELS = {
    "info": "Preview",
    "labels": "Color label",
    "keywords": "Keywords",
    "dates": "Date taken",
    "rename": "Rename",
}


class Sidebar(QWidget):
    def __init__(self, ctl: Controller):
        super().__init__()
        self.ctl = ctl
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        self.warning = QLabel()
        self.warning.setWordWrap(True)
        self.warning.setStyleSheet("background:#5c2b00;color:white;padding:6px;border-radius:4px;")
        self.warning.setVisible(False)
        layout.addWidget(self.warning)
        self.info = InfoPanel(ctl)
        self.labels = LabelPanel(ctl)
        self.keywords = KeywordPanel(ctl)
        self.dates = DatePanel(ctl)
        self.rename = RenamePanel(ctl)
        self.sections: dict[str, Section] = {}
        collapsed = set(ctl.settings.collapsed_panels)
        for key, title in PANELS.items():
            section = Section(key, title, getattr(self, key), key in collapsed)
            section.header.toggled.connect(lambda _on: self._remember())
            section.setVisible(key not in ctl.settings.hidden_panels)
            self.sections[key] = section
            layout.addWidget(section)
        layout.addStretch(1)

    def _remember(self) -> None:
        self.ctl.settings.collapsed_panels = [k for k, s in self.sections.items() if s.collapsed]

    def set_panel_visible(self, key: str, visible: bool) -> None:
        self.sections[key].setVisible(visible)
        hidden = [k for k, s in self.sections.items() if s.isHidden()]
        self.ctl.settings.hidden_panels = hidden

    def refresh(self, items: list[Item]) -> None:
        for panel in (self.info, self.labels, self.keywords, self.dates, self.rename):
            panel.refresh(items)
