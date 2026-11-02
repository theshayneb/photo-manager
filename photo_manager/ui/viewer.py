"""Full-window viewer: arrow keys to move, Delete to recycle, Esc to close."""

from __future__ import annotations

import os
from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent, QPixmap, QResizeEvent
from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout, QWidget

from ..core import thumbs
from .grid import pil_to_qimage


class Viewer(QDialog):
    navigate = Signal(int)        # -1 previous, +1 next
    delete_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Viewer")
        self.setStyleSheet("background:#111; color:#ddd;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.image = QLabel()
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setMinimumSize(200, 200)
        self.caption = QLabel()
        self.caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.caption.setStyleSheet("padding:4px;")
        layout.addWidget(self.image, 1)
        layout.addWidget(self.caption)
        self._pixmap: QPixmap | None = None
        self.path = ""

    def show_path(self, path: str, caption: str, kind: str, open_external: Callable[[str], None]) -> None:
        self.path = path
        self.caption.setText(caption + ("   —   Enter plays the video" if kind == "video" else ""))
        self.setWindowTitle(os.path.basename(path))
        self._open_external = open_external
        self._kind = kind
        self._pixmap = None
        screen = self.screen().availableGeometry() if self.screen() else None
        longest = max(screen.width(), screen.height()) if screen else 2560
        try:
            im = thumbs.video_frame(path, longest) if kind == "video" else thumbs.open_image(path, longest)
        except Exception:  # noqa: BLE001
            im = None
        if im is not None:
            self._pixmap = QPixmap.fromImage(pil_to_qimage(im))
            self._fit()
        else:
            self.image.setPixmap(QPixmap())
            self.image.setText("Can't show this file here — press Enter to open it.")

    def _fit(self) -> None:
        if self._pixmap is None:
            return
        self.image.setPixmap(self._pixmap.scaled(
            self.image.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._fit()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key in (Qt.Key.Key_Right, Qt.Key.Key_Down, Qt.Key.Key_Space, Qt.Key.Key_PageDown):
            self.navigate.emit(1)
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_Up, Qt.Key.Key_Backspace, Qt.Key.Key_PageUp):
            self.navigate.emit(-1)
        elif key == Qt.Key.Key_Delete:
            self.delete_requested.emit()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._open_external(self.path)
        elif key == Qt.Key.Key_F11:
            self.showNormal() if self.isFullScreen() else self.showFullScreen()
        else:
            super().keyPressEvent(event)
