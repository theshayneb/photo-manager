"""Folder tree and Favorites list that accept photos dropped from the grid
(or from Explorer). Dropping moves the files; holding Ctrl copies them."""

from __future__ import annotations

import os

from PySide6.QtCore import QModelIndex, Qt, QTimer, Signal
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import QAbstractItemView, QListWidget, QTreeView

EXPAND_DELAY_MS = 700


def dropped_files(event) -> list[str]:  # type: ignore[no-untyped-def]
    mime = event.mimeData()
    if not mime.hasUrls():
        return []
    return [u.toLocalFile() for u in mime.urls() if u.isLocalFile() and os.path.isfile(u.toLocalFile())]


def wants_copy(event) -> bool:  # type: ignore[no-untyped-def]
    return bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)


class FolderTree(QTreeView):
    files_dropped = Signal(list, str, bool)  # paths, folder, copy

    def __init__(self, parent=None):  # type: ignore[no-untyped-def]
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self._hover = QModelIndex()
        self._saved_current = QModelIndex()
        self._expand_timer = QTimer(self)
        self._expand_timer.setSingleShot(True)
        self._expand_timer.timeout.connect(self._expand_hovered)

    def folder_at(self, pos) -> str:  # type: ignore[no-untyped-def]
        index = self.indexAt(pos)
        if not index.isValid():
            return ""
        path = self.model().filePath(index)  # type: ignore[attr-defined]
        return path if os.path.isdir(path) else ""

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if dropped_files(event):
            self._saved_current = self.currentIndex()
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        pos = event.position().toPoint()
        folder = self.folder_at(pos)
        if not folder:
            event.ignore()
            return
        index = self.indexAt(pos)
        if index != self._hover:
            self._hover = index
            self.setCurrentIndex(index)  # highlight the target folder
            self._expand_timer.start(EXPAND_DELAY_MS)
        event.setDropAction(Qt.DropAction.CopyAction if wants_copy(event) else Qt.DropAction.MoveAction)
        event.accept()

    def _expand_hovered(self) -> None:
        if self._hover.isValid():
            self.expand(self._hover)

    def dragLeaveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self._end_drag()
        super().dragLeaveEvent(event)

    def _end_drag(self) -> None:
        self._expand_timer.stop()
        self._hover = QModelIndex()
        if self._saved_current.isValid():
            self.setCurrentIndex(self._saved_current)
        else:
            self.clearSelection()

    def dropEvent(self, event: QDropEvent) -> None:
        folder = self.folder_at(event.position().toPoint())
        paths = dropped_files(event)
        copy = wants_copy(event)
        self._end_drag()
        if folder and paths:
            event.setDropAction(Qt.DropAction.CopyAction if copy else Qt.DropAction.MoveAction)
            event.accept()
            self.files_dropped.emit(paths, folder, copy)
        else:
            event.ignore()


class FavoritesList(QListWidget):
    """Drag inside the list to reorder favorites; drop photos on a favorite to move them there."""

    files_dropped = Signal(list, str, bool)

    def __init__(self, parent=None):  # type: ignore[no-untyped-def]
        super().__init__(parent)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setAcceptDrops(True)

    def _folder_at(self, pos) -> str:  # type: ignore[no-untyped-def]
        item = self.itemAt(pos)
        folder = item.data(Qt.ItemDataRole.UserRole) if item else ""
        return folder if folder and os.path.isdir(folder) else ""

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.source() is self:
            super().dragEnterEvent(event)
        elif dropped_files(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if event.source() is self:
            super().dragMoveEvent(event)
            return
        pos = event.position().toPoint()
        if not self._folder_at(pos):
            event.ignore()
            return
        self.setCurrentItem(self.itemAt(pos))
        event.setDropAction(Qt.DropAction.CopyAction if wants_copy(event) else Qt.DropAction.MoveAction)
        event.accept()

    def dropEvent(self, event: QDropEvent) -> None:
        if event.source() is self:
            super().dropEvent(event)
            return
        folder = self._folder_at(event.position().toPoint())
        paths = dropped_files(event)
        copy = wants_copy(event)
        self.clearSelection()
        if folder and paths:
            event.setDropAction(Qt.DropAction.CopyAction if copy else Qt.DropAction.MoveAction)
            event.accept()
            self.files_dropped.emit(paths, folder, copy)
        else:
            event.ignore()
