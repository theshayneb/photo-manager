"""Thumbnail grid: model (with optional group headers), painting and view."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from PIL import Image
from PySide6.QtCore import (
    QAbstractListModel, QModelIndex, QObject, QRect, QRunnable, QSize, Qt,
    QThreadPool, Signal,
)
from PySide6.QtGui import QColor, QFont, QImage, QMouseEvent, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QAbstractItemView, QListView, QStyle, QStyledItemDelegate

from ..core import dates, thumbs
from ..core.media import kind
from ..core.metadata import LABELS, Meta

THUMB_PIXELS = 320  # generated once, scaled down for display
INFO_LINE = 16
HEADER_HEIGHT = 34

LABEL_COLORS = {
    "Red": QColor("#e5484d"),
    "Yellow": QColor("#f5c400"),
    "Green": QColor("#30a46c"),
    "Blue": QColor("#3e8ef7"),
    "Purple": QColor("#8e4ec6"),
}

GROUPS = {
    "none": "No grouping",
    "day": "Day taken",
    "week": "Week taken",
    "month": "Month taken",
    "label": "Color label",
}

# Extra lines that can be shown under each filename.
INFO_FIELDS = {
    "date": "Date taken",
    "size": "Dimensions",
    "filesize": "File size",
    "keywords": "Keywords",
}

ItemRole = Qt.ItemDataRole.UserRole + 1


@dataclass
class Item:
    path: str
    kind: str
    size: int
    mtime: float
    meta: Meta | None = None
    thumb: QPixmap | None = None
    thumb_state: str = "none"  # none | pending | done | failed
    extra: dict = field(default_factory=dict)

    @property
    def name(self) -> str:
        return os.path.basename(self.path)


@dataclass
class GroupHeader:
    title: str
    paths: list[str]


def pil_to_qimage(im: Image.Image) -> QImage:
    if im.mode != "RGBA":
        im = im.convert("RGBA")
    data = im.tobytes("raw", "RGBA")
    return QImage(data, im.width, im.height, im.width * 4, QImage.Format.Format_RGBA8888).copy()


class _ThumbSignals(QObject):
    ready = Signal(str, int, object)  # path, generation, QImage | None


class _ThumbTask(QRunnable):
    def __init__(self, signals: _ThumbSignals, path: str, generation: int, cache_dir: Path | None):
        super().__init__()
        self.signals, self.path, self.generation, self.cache_dir = signals, path, generation, cache_dir

    def run(self) -> None:
        im = thumbs.thumbnail(self.path, THUMB_PIXELS, self.cache_dir)
        self.signals.ready.emit(self.path, self.generation, pil_to_qimage(im) if im else None)


def _natural_key(name: str) -> list:
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", name.casefold())]


def group_key(item: Item, group_by: str, week_start: str) -> tuple[tuple, str]:
    """(sort key, header title) for an item under a grouping mode."""
    meta = item.meta
    if group_by == "label":
        label = meta.label if meta else ""
        if label in LABELS:
            return (LABELS.index(label),), label
        return (len(LABELS),), "No label"
    dt = meta.date_taken if meta else None
    if dt is None:
        return ((1,), "No date taken")
    if group_by == "day":
        return ((0, dt.year, dt.month, dt.day), f"{dt:%A, %B} {dt.day}, {dt.year}")
    if group_by == "month":
        return ((0, dt.year, dt.month), f"{dt:%B %Y}")
    # week
    offset = (dt.weekday() + 1) % 7 if week_start == "sunday" else dt.weekday()
    start = (dt - timedelta(days=offset)).date()
    end = start + timedelta(days=6)
    year, number = week_number(start, week_start)
    title = (f"Week {number}  ·  {start:%a, %b} {start.day}  –  {end:%a, %b} {end.day}, {end.year}")
    return ((0, start.toordinal()), title)


def week_number(week_start_day: date, week_start: str) -> tuple[int, int]:
    """(year, week number) for a week beginning on week_start_day.

    Monday weeks use ISO 8601 numbering. Sunday weeks use the US convention:
    week 1 is the week containing January 1.
    """
    if week_start == "monday":
        iso = week_start_day.isocalendar()
        return iso[0], iso[1]
    year = (week_start_day + timedelta(days=6)).year  # the week belongs to the year it ends in
    jan1 = date(year, 1, 1)
    first = jan1 - timedelta(days=(jan1.weekday() + 1) % 7)
    return year, (week_start_day - first).days // 7 + 1


class PhotoModel(QAbstractListModel):
    """Rows are photos, plus a header row before each group when grouping is on."""

    def __init__(self, cache_dir: Path | None = None, parent: QObject | None = None):
        super().__init__(parent)
        self.items: list[Item] = []          # photos in display order
        self.rows: list[Item | GroupHeader] = []
        self.folder = ""
        self.generation = 0
        self.sort_by = "name"
        self.group_by = "none"
        self.week_start = "sunday"
        self.cache_dir = cache_dir
        self._row_of: dict[str, int] = {}
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(max(2, min(6, (os.cpu_count() or 4) - 1)))
        self._signals = _ThumbSignals()
        self._signals.ready.connect(self._on_thumb)

    # -- loading -----------------------------------------------------------

    def load_folder(self, folder: str) -> None:
        self._pool.clear()
        self.generation += 1
        items: list[Item] = []
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    try:
                        if not entry.is_file():
                            continue
                        k = kind(entry.name)
                        if not k:
                            continue
                        st = entry.stat()
                    except OSError:
                        continue
                    items.append(Item(entry.path, k, st.st_size, st.st_mtime))
        except OSError:
            items = []
        self.folder = folder
        self.items = items
        self.regroup()

    def regroup(self) -> None:
        """Re-sort and rebuild group headers (resets the view; callers restore selection)."""
        self.beginResetModel()
        self._sort_items()
        rows: list[Item | GroupHeader] = []
        if self.group_by in GROUPS and self.group_by != "none":
            groups: dict[tuple, tuple[str, list[Item]]] = {}
            for item in self.items:
                key, title = group_key(item, self.group_by, self.week_start)
                groups.setdefault(key, (title, []))[1].append(item)
            ordered: list[Item] = []
            for key in sorted(groups):
                title, members = groups[key]
                rows.append(GroupHeader(title, [m.path for m in members]))
                rows.extend(members)
                ordered.extend(members)
            self.items = ordered
        else:
            rows = list(self.items)
        self.rows = rows
        self._row_of = {os.path.normcase(r.path): n for n, r in enumerate(rows) if isinstance(r, Item)}
        self.endResetModel()

    @property
    def grouped(self) -> bool:
        return self.group_by != "none"

    def needs_regroup_for_meta(self) -> bool:
        return self.sort_by == "date" or self.group_by not in ("none",)

    def _sort_items(self) -> None:
        if self.sort_by == "date":
            far = 1e18
            self.items.sort(key=lambda i: (
                i.meta.date_taken.timestamp() if i.meta and i.meta.date_taken else far,
                _natural_key(i.name)))
        elif self.sort_by == "modified":
            self.items.sort(key=lambda i: (i.mtime, _natural_key(i.name)))
        elif self.sort_by == "size":
            self.items.sort(key=lambda i: (i.size, _natural_key(i.name)))
        else:
            self.items.sort(key=lambda i: _natural_key(i.name))

    # -- Qt model API -------------------------------------------------------

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self.rows)

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if index.isValid() and isinstance(self.rows[index.row()], GroupHeader):
            return Qt.ItemFlag.NoItemFlags
        return super().flags(index)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):  # type: ignore[override]
        if not index.isValid() or index.row() >= len(self.rows):
            return None
        row = self.rows[index.row()]
        if isinstance(row, GroupHeader):
            if role == ItemRole:
                return row
            if role == Qt.ItemDataRole.DisplayRole:
                return row.title
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return row.name
        if role == Qt.ItemDataRole.ToolTipRole:
            return row.path
        if role == ItemRole:
            if row.thumb_state == "none":
                self._request_thumb(row)
            return row
        return None

    # -- lookups -----------------------------------------------------------

    def row_of(self, path: str) -> int:
        return self._row_of.get(os.path.normcase(path), -1)

    def item(self, path: str) -> Item | None:
        row = self.row_of(path)
        return self.rows[row] if row >= 0 else None  # type: ignore[return-value]

    def item_at(self, row: int) -> Item | None:
        if 0 <= row < len(self.rows):
            r = self.rows[row]
            return r if isinstance(r, Item) else None
        return None

    def header_at(self, row: int) -> GroupHeader | None:
        if 0 <= row < len(self.rows):
            r = self.rows[row]
            return r if isinstance(r, GroupHeader) else None
        return None

    def first_item_row(self) -> int:
        return self.row_of(self.items[0].path) if self.items else -1

    def neighbour(self, path: str, delta: int) -> Item | None:
        """The photo delta steps away in display order (skipping headers)."""
        keys = [os.path.normcase(i.path) for i in self.items]
        try:
            pos = keys.index(os.path.normcase(path))
        except ValueError:
            return None
        target = pos + delta
        return self.items[target] if 0 <= target < len(self.items) else None

    # -- updates -----------------------------------------------------------

    def _changed(self, row: int) -> None:
        idx = self.index(row)
        self.dataChanged.emit(idx, idx)

    def _request_thumb(self, item: Item) -> None:
        item.thumb_state = "pending"
        self._pool.start(_ThumbTask(self._signals, item.path, self.generation, self.cache_dir))

    def _on_thumb(self, path: str, generation: int, image: QImage | None) -> None:
        if generation != self.generation:
            return
        row = self.row_of(path)
        if row < 0:
            return
        item = self.rows[row]
        assert isinstance(item, Item)
        if image is None or image.isNull():
            item.thumb_state = "failed"
        else:
            item.thumb = QPixmap.fromImage(image)
            item.thumb_state = "done"
        self._changed(row)

    def set_meta(self, metas: dict[str, Meta]) -> None:
        """Store metadata. Callers should regroup() afterwards if needs_regroup_for_meta()."""
        for path, meta in metas.items():
            row = self.row_of(path)
            if row >= 0:
                self.rows[row].meta = meta  # type: ignore[union-attr]
                self._changed(row)

    def refresh_file(self, path: str) -> None:
        item = self.item(path)
        if not item:
            return
        try:
            st = os.stat(path)
            item.size, item.mtime = st.st_size, st.st_mtime
        except OSError:
            pass

    def add_path(self, path: str) -> Item | None:
        """Add a new file (e.g. a cropped copy). Callers regroup() afterwards."""
        k = kind(path)
        if not k or self.item(path):
            return None
        try:
            st = os.stat(path)
        except OSError:
            return None
        item = Item(path, k, st.st_size, st.st_mtime)
        self.items.append(item)
        return item

    def reload_thumb(self, path: str) -> None:
        """The image itself changed (e.g. cropped): drop the thumbnail so it's remade."""
        item = self.item(path)
        if item:
            item.thumb, item.thumb_state = None, "none"
            self._changed(self.row_of(path))

    def remove_paths(self, paths: list[str]) -> None:
        gone = {os.path.normcase(p) for p in paths}
        self.items = [i for i in self.items if os.path.normcase(i.path) not in gone]
        self.regroup()

    def rename_paths(self, renames: dict[str, str]) -> None:
        for old, new in renames.items():
            item = self.item(old)
            if item:
                item.path = new
        self.regroup()


class ThumbDelegate(QStyledItemDelegate):
    def __init__(self, view: "ThumbGrid"):
        super().__init__(view)
        self.view = view
        self.thumb_size = 160
        self.info_fields: list[str] = ["date"]
        self.display_format = dates.DEFAULT_DISPLAY_FORMAT

    def sizeHint(self, option, index) -> QSize:  # type: ignore[override]
        row = index.data(ItemRole)
        if isinstance(row, GroupHeader):
            width = self.view.viewport().width() - 2 * self.view.spacing() - 2
            return QSize(max(width, 100), HEADER_HEIGHT)
        return QSize(self.thumb_size + 16, self.thumb_size + 38 + INFO_LINE * len(self.info_fields))

    def _info_lines(self, item: Item) -> list[str]:
        meta = item.meta
        lines = []
        for f in self.info_fields:
            if f == "date":
                if meta is None:
                    lines.append("…")
                else:
                    lines.append(dates.format_display(meta.date_taken, self.display_format) or "no date taken")
            elif f == "size":
                lines.append(meta.image_size if meta and meta.image_size else "")
            elif f == "filesize":
                mb = item.size / 1_048_576
                lines.append(f"{mb:.1f} MB" if mb >= 0.1 else f"{item.size // 1024} KB")
            elif f == "keywords":
                lines.append(", ".join(meta.keywords) if meta else "")
        return lines

    def paint(self, painter: QPainter, option, index) -> None:  # type: ignore[override]
        row = index.data(ItemRole)
        if isinstance(row, GroupHeader):
            self._paint_header(painter, option, row)
            return
        item: Item = row
        if item is None:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect: QRect = option.rect.adjusted(3, 3, -3, -3)
        palette = option.palette
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        if selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(palette.highlight().color())
            painter.drawRoundedRect(rect, 6, 6)
        elif option.state & QStyle.StateFlag.State_MouseOver:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(palette.alternateBase().color())
            painter.drawRoundedRect(rect, 6, 6)

        size = self.thumb_size
        box = QRect(rect.x() + (rect.width() - size) // 2, rect.y() + 5, size, size)
        if item.thumb is not None:
            scaled = item.thumb.size().scaled(box.size(), Qt.AspectRatioMode.KeepAspectRatio)
            target = QRect(0, 0, scaled.width(), scaled.height())
            target.moveCenter(box.center())
            painter.drawPixmap(target, item.thumb)
        else:
            painter.setPen(palette.mid().color())
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(box.adjusted(8, 8, -8, -8), 4, 4)
            painter.setPen(palette.text().color())
            text = {"pending": "…", "failed": "no preview"}.get(item.thumb_state, "")
            if item.kind == "video" and item.thumb_state == "failed":
                text = "video"
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)
            target = box

        color = LABEL_COLORS.get(item.meta.label if item.meta else "")
        if color is not None:
            painter.setPen(QPen(color, 4))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(target.adjusted(-2, -2, 2, 2), 3, 3)

        if item.kind == "video":
            badge = QRect(target.left() + 4, target.bottom() - 22, 26, 18)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 170))
            painter.drawRoundedRect(badge, 4, 4)
            painter.setPen(QColor("white"))
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, "▶")

        text_color = palette.highlightedText().color() if selected else palette.text().color()
        text_rect = QRect(rect.x() + 4, box.bottom() + 6, rect.width() - 8, 20)
        painter.setPen(text_color)
        painter.setFont(QFont(option.font))
        name = option.fontMetrics.elidedText(item.name, Qt.TextElideMode.ElideMiddle, text_rect.width())
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, name)

        lines = self._info_lines(item)
        if lines:
            small = QFont(option.font)
            small.setPointSizeF(max(7.0, option.font.pointSizeF() - 1))
            painter.setFont(small)
            dim = QColor(text_color)
            dim.setAlphaF(0.72)
            painter.setPen(dim)
            y = text_rect.top() + 19
            metrics = painter.fontMetrics()
            for line in lines:
                r = QRect(text_rect.x(), y, text_rect.width(), INFO_LINE)
                painter.drawText(r, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                                 metrics.elidedText(line, Qt.TextElideMode.ElideRight, r.width()))
                y += INFO_LINE
        painter.restore()

    def _paint_header(self, painter: QPainter, option, header: GroupHeader) -> None:
        painter.save()
        rect = option.rect.adjusted(4, 2, -4, -2)
        # Headers are "disabled" items (not selectable); draw them in normal colours.
        text_color = option.palette.color(QPalette.ColorGroup.Active, QPalette.ColorRole.Text)
        mid_color = option.palette.color(QPalette.ColorGroup.Active, QPalette.ColorRole.Mid)
        font = QFont(option.font)
        font.setBold(True)
        font.setPointSizeF(option.font.pointSizeF() + 1)
        painter.setFont(font)
        painter.setPen(text_color)
        title = header.title
        count = f"  ·  {len(header.paths)}"
        painter.drawText(rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, title)
        width = painter.fontMetrics().horizontalAdvance(title)
        painter.setFont(QFont(option.font))
        dim = QColor(text_color)
        dim.setAlphaF(0.6)
        painter.setPen(dim)
        painter.drawText(rect.adjusted(width, 0, 0, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, count)
        painter.setPen(QPen(mid_color, 1))
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        painter.restore()


class ThumbGrid(QListView):
    def __init__(self, model: PhotoModel, parent=None):  # type: ignore[no-untyped-def]
        super().__init__(parent)
        self.setModel(model)
        self.delegate = ThumbDelegate(self)
        self.setItemDelegate(self.delegate)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setUniformItemSizes(False)  # group headers are full width
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setLayoutMode(QListView.LayoutMode.Batched)
        self.setBatchSize(300)
        self.setSpacing(4)
        self.setMouseTracking(True)
        self.setWordWrap(False)
        # Smooth scrolling: the default (a whole row per wheel step) jumps too far.
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._update_scroll_step()

    def updateGeometries(self) -> None:
        super().updateGeometries()  # Qt resets the step here; put ours back
        self._update_scroll_step()

    def _update_scroll_step(self) -> None:
        # One wheel notch scrolls 3 steps; make that about a third of a row.
        row = self.delegate.thumb_size + 38 + INFO_LINE * len(self.delegate.info_fields)
        self.verticalScrollBar().setSingleStep(max(10, row // 9))

    def photo_model(self) -> PhotoModel:
        return self.model()  # type: ignore[return-value]

    def set_thumb_size(self, size: int) -> None:
        self.delegate.thumb_size = size
        self._update_scroll_step()
        self.relayout()

    def set_info_fields(self, fields: list[str]) -> None:
        self.delegate.info_fields = [f for f in INFO_FIELDS if f in fields]
        self._update_scroll_step()
        self.relayout()

    def relayout(self) -> None:
        self.scheduleDelayedItemsLayout()
        self.viewport().update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        index = self.indexAt(event.position().toPoint())
        header = self.photo_model().header_at(index.row()) if index.isValid() else None
        if header is not None and event.button() == Qt.MouseButton.LeftButton:
            self.select_paths(header.paths, add=bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier))
            return
        super().mousePressEvent(event)

    def select_paths(self, paths: list[str], add: bool = False, current: str | None = None) -> None:
        model = self.photo_model()
        sel = self.selectionModel()
        if not add:
            sel.clearSelection()
        first = None
        for path in paths:
            row = model.row_of(path)
            if row >= 0:
                sel.select(model.index(row), sel.SelectionFlag.Select)
                first = first if first is not None else row
        target = model.row_of(current) if current else first
        if target is not None and target >= 0:
            sel.setCurrentIndex(model.index(target), sel.SelectionFlag.NoUpdate)

    def selected_paths(self) -> list[str]:
        model = self.photo_model()
        rows = sorted(i.row() for i in self.selectionModel().selectedIndexes())
        return [item.path for item in (model.item_at(r) for r in rows) if item]

    def current_path(self) -> str | None:
        item = self.photo_model().item_at(self.currentIndex().row())
        return item.path if item else None
