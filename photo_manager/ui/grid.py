"""Thumbnail grid: model, painting and view."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image
from PySide6.QtCore import (
    QAbstractListModel, QModelIndex, QObject, QRect, QRunnable, QSize, Qt,
    QThreadPool, Signal,
)
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QAbstractItemView, QListView, QStyle, QStyledItemDelegate

from ..core import thumbs
from ..core.media import kind
from ..core.metadata import Meta

THUMB_PIXELS = 320  # generated once, scaled down for display

LABEL_COLORS = {
    "Red": QColor("#e5484d"),
    "Yellow": QColor("#f5c400"),
    "Green": QColor("#30a46c"),
    "Blue": QColor("#3e8ef7"),
    "Purple": QColor("#8e4ec6"),
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


class PhotoModel(QAbstractListModel):
    def __init__(self, cache_dir: Path | None = None, parent: QObject | None = None):
        super().__init__(parent)
        self.items: list[Item] = []
        self.folder = ""
        self.generation = 0
        self.sort_by = "name"
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
        self.beginResetModel()
        self.folder = folder
        self.items = items
        self._sort_items()
        self.endResetModel()

    def set_sort(self, sort_by: str) -> None:
        self.sort_by = sort_by
        self.layoutAboutToBeChanged.emit()
        self._sort_items()
        self.layoutChanged.emit()

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
        self._row_of = {os.path.normcase(i.path): r for r, i in enumerate(self.items)}

    # -- Qt model API -------------------------------------------------------

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self.items)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):  # type: ignore[override]
        if not index.isValid():
            return None
        item = self.items[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return item.name
        if role == Qt.ItemDataRole.ToolTipRole:
            return item.path
        if role == ItemRole:
            if item.thumb_state == "none":
                self._request_thumb(item)
            return item
        return None

    # -- updates -----------------------------------------------------------

    def row_of(self, path: str) -> int:
        return self._row_of.get(os.path.normcase(path), -1)

    def item(self, path: str) -> Item | None:
        row = self.row_of(path)
        return self.items[row] if row >= 0 else None

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
        item = self.items[row]
        if image is None or image.isNull():
            item.thumb_state = "failed"
        else:
            item.thumb = QPixmap.fromImage(image)
            item.thumb_state = "done"
        self._changed(row)

    def set_meta(self, metas: dict[str, Meta]) -> None:
        for path, meta in metas.items():
            row = self.row_of(path)
            if row >= 0:
                self.items[row].meta = meta
                self._changed(row)
        if self.sort_by == "date":
            self.set_sort("date")

    def refresh_file(self, path: str) -> None:
        """A file's contents changed (e.g. metadata written): refresh size/mtime."""
        item = self.item(path)
        if not item:
            return
        try:
            st = os.stat(path)
            item.size, item.mtime = st.st_size, st.st_mtime
        except OSError:
            pass

    def remove_paths(self, paths: list[str]) -> None:
        gone = {os.path.normcase(p) for p in paths}
        rows = sorted((r for p, r in self._row_of.items() if p in gone), reverse=True)
        for row in rows:
            self.beginRemoveRows(QModelIndex(), row, row)
            del self.items[row]
            self.endRemoveRows()
        self._row_of = {os.path.normcase(i.path): r for r, i in enumerate(self.items)}

    def rename_paths(self, renames: dict[str, str]) -> None:
        for old, new in renames.items():
            item = self.item(old)
            if item:
                item.path = new
        self.set_sort(self.sort_by)


class ThumbDelegate(QStyledItemDelegate):
    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.thumb_size = 160

    def sizeHint(self, option, index) -> QSize:  # type: ignore[override]
        return QSize(self.thumb_size + 16, self.thumb_size + 38)

    def paint(self, painter: QPainter, option, index) -> None:  # type: ignore[override]
        item: Item = index.data(ItemRole)
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

        label = item.meta.label if item.meta else ""
        color = LABEL_COLORS.get(label)
        if color is not None:
            pen = QPen(color, 4)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(target.adjusted(-2, -2, 2, 2), 3, 3)

        if item.kind == "video":
            badge = QRect(target.left() + 4, target.bottom() - 22, 26, 18)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 170))
            painter.drawRoundedRect(badge, 4, 4)
            painter.setPen(QColor("white"))
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, "▶")

        text_rect = QRect(rect.x() + 4, box.bottom() + 6, rect.width() - 8, 20)
        painter.setPen(palette.highlightedText().color() if selected else palette.text().color())
        font = QFont(option.font)
        painter.setFont(font)
        name = option.fontMetrics.elidedText(item.name, Qt.TextElideMode.ElideMiddle, text_rect.width())
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, name)
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
        self.setUniformItemSizes(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setLayoutMode(QListView.LayoutMode.Batched)
        self.setBatchSize(200)
        self.setSpacing(4)
        self.setMouseTracking(True)
        self.setWordWrap(False)

    def set_thumb_size(self, size: int) -> None:
        self.delegate.thumb_size = size
        self.setGridSize(QSize())  # let sizeHint drive the layout
        self.scheduleDelayedItemsLayout()
        self.viewport().update()

    def selected_paths(self) -> list[str]:
        model: PhotoModel = self.model()  # type: ignore[assignment]
        rows = sorted(i.row() for i in self.selectionModel().selectedIndexes())
        return [model.items[r].path for r in rows if r < len(model.items)]

    def current_path(self) -> str | None:
        idx = self.currentIndex()
        model: PhotoModel = self.model()  # type: ignore[assignment]
        return model.items[idx.row()].path if idx.isValid() and idx.row() < len(model.items) else None
