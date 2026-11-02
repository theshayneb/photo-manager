"""In-window preview (Shift+P) with a simple crop tool (C)."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..core import thumbs
from ..core.crop import ASPECT_RATIOS, can_crop, upright_size
from ..core.winthumb import shell_thumbnail
from .grid import paint_flags, paint_label_frame, paint_type_badge, pil_to_qimage
from .video import VideoView

HANDLE = 10  # px, grab distance for corners/edges


def load_display_pixmap(path: str, kind: str, longest: int) -> QPixmap | None:
    try:
        if kind == "video":
            im = shell_thumbnail(path, 1024) or thumbs.video_frame(path, longest)
        else:
            im = thumbs.open_image(path, longest)
    except Exception:  # noqa: BLE001
        im = None
    return QPixmap.fromImage(pil_to_qimage(im)) if im is not None else None


class CropCanvas(QWidget):
    """Shows a pixmap fitted to the widget; in crop mode, lets you drag a crop box.

    The crop box is kept in *image* coordinates of the full-size upright photo.
    """

    changed = Signal()
    clicked = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.pixmap: QPixmap | None = None
        self.full_size = (0, 0)       # upright size of the real photo
        self.cropping = False
        self.box = QRectF()           # crop box in full-size coordinates
        self.ratio: float | None = None
        self.message = ""
        self._drag: str | None = None  # "new" | "move" | corner/edge code
        self._drag_origin = QPointF()
        self._box_origin = QRectF()

    # -- geometry --

    def _target(self) -> QRectF:
        if not self.pixmap or self.pixmap.isNull():
            return QRectF()
        size = self.pixmap.size()
        size.scale(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        x = (self.width() - size.width()) / 2
        y = (self.height() - size.height()) / 2
        return QRectF(x, y, size.width(), size.height())

    def _scale(self) -> float:
        target = self._target()
        return target.width() / self.full_size[0] if self.full_size[0] else 1.0

    def _to_screen(self, r: QRectF) -> QRectF:
        t, s = self._target(), self._scale()
        return QRectF(t.x() + r.x() * s, t.y() + r.y() * s, r.width() * s, r.height() * s)

    def _to_image(self, p: QPointF) -> QPointF:
        t, s = self._target(), self._scale() or 1.0
        x = min(max((p.x() - t.x()) / s, 0), self.full_size[0])
        y = min(max((p.y() - t.y()) / s, 0), self.full_size[1])
        return QPointF(x, y)

    # -- state --

    def set_image(self, pixmap: QPixmap | None, full_size: tuple[int, int], message: str = "") -> None:
        self.pixmap = pixmap
        self.full_size = full_size if pixmap else (0, 0)
        self.message = message
        self.cropping = False
        self.box = QRectF()
        self.update()

    def start_crop(self, ratio: float | None) -> None:
        if not self.pixmap:
            return
        self.cropping = True
        self.set_ratio(ratio)

    def set_ratio(self, ratio: float | None) -> None:
        self.ratio = ratio
        w, h = self.full_size
        if ratio is None:
            self.box = QRectF(w * 0.1, h * 0.1, w * 0.8, h * 0.8) if self.box.isEmpty() else self.box
        else:
            bw, bh = w * 0.9, w * 0.9 / ratio
            if bh > h * 0.9:
                bh, bw = h * 0.9, h * 0.9 * ratio
            self.box = QRectF((w - bw) / 2, (h - bh) / 2, bw, bh)
        self.changed.emit()
        self.update()

    def stop_crop(self) -> None:
        self.cropping = False
        self._drag = None
        self.update()

    def crop_box(self) -> tuple[int, int, int, int]:
        b = self.box.normalized()
        return (round(b.left()), round(b.top()), round(b.right()), round(b.bottom()))

    # -- painting --

    def paintEvent(self, _event) -> None:  # type: ignore[no-untyped-def]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        target = self._target()
        if self.pixmap and not target.isEmpty():
            painter.drawPixmap(target, self.pixmap, QRectF(self.pixmap.rect()))
            if not self.cropping:
                self._paint_marks(painter, target)
        else:
            painter.setPen(self.palette().text().color())
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.message or "No preview")
        if self.cropping and not self.box.isEmpty():
            box = self._to_screen(self.box.normalized())
            shade = QPainterPath()
            shade.addRect(target)
            hole = QPainterPath()
            hole.addRect(box)
            painter.fillPath(shade.subtracted(hole), QColor(0, 0, 0, 150))
            painter.setPen(QPen(QColor("white"), 1, Qt.PenStyle.SolidLine))
            painter.drawRect(box)
            painter.setPen(QPen(QColor(255, 255, 255, 90), 1))
            for i in (1, 2):  # rule of thirds
                x = box.left() + box.width() * i / 3
                y = box.top() + box.height() * i / 3
                painter.drawLine(QPointF(x, box.top()), QPointF(x, box.bottom()))
                painter.drawLine(QPointF(box.left(), y), QPointF(box.right(), y))
            painter.setBrush(QColor("white"))
            painter.setPen(Qt.PenStyle.NoPen)
            for corner in (box.topLeft(), box.topRight(), box.bottomLeft(), box.bottomRight()):
                painter.drawRect(QRectF(corner.x() - 4, corner.y() - 4, 8, 8))
            w, h = self.crop_box()[2] - self.crop_box()[0], self.crop_box()[3] - self.crop_box()[1]
            painter.setPen(QColor("white"))
            painter.drawText(box.adjusted(6, 4, 0, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                             f"{w} × {h}")

    def set_marks(self, path: str, kind: str, meta, show_type: bool) -> None:  # type: ignore[no-untyped-def]
        """What to draw on top of the photo: type badge, ★/🔖 and the color-label frame."""
        self.mark_path, self.mark_kind, self.mark_meta, self.show_type = path, kind, meta, show_type
        self.update()

    def _paint_marks(self, painter: QPainter, target: QRectF) -> None:
        if not getattr(self, "mark_path", ""):
            return
        rect = target.toRect()
        scale = 1.6  # a bit bigger than in the grid
        # Inside the photo's edge, so it isn't cut off when the photo fills the pane.
        paint_label_frame(painter, rect.adjusted(5, 5, -5, -5), self.mark_meta, scale)
        paint_flags(painter, rect, self.mark_meta, scale)
        if self.show_type:
            paint_type_badge(painter, rect, self.mark_path, self.mark_kind, self.font(), scale)

    # -- mouse --

    def _hit(self, pos: QPointF) -> str | None:
        box = self._to_screen(self.box.normalized())
        near_l = abs(pos.x() - box.left()) <= HANDLE
        near_r = abs(pos.x() - box.right()) <= HANDLE
        near_t = abs(pos.y() - box.top()) <= HANDLE
        near_b = abs(pos.y() - box.bottom()) <= HANDLE
        inside_x = box.left() - HANDLE <= pos.x() <= box.right() + HANDLE
        inside_y = box.top() - HANDLE <= pos.y() <= box.bottom() + HANDLE
        code = ""
        if near_t and inside_x:
            code += "t"
        elif near_b and inside_x:
            code += "b"
        if near_l and inside_y:
            code += "l"
        elif near_r and inside_y:
            code += "r"
        if code:
            return code
        return "move" if box.contains(pos) else None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if not self.cropping:
            self.clicked.emit()
        if not self.cropping or event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        pos = event.position()
        self._drag = self._hit(pos) or "new"
        self._drag_origin = self._to_image(pos)
        self._box_origin = QRectF(self.box.normalized())
        if self._drag == "new":
            self.box = QRectF(self._drag_origin, self._drag_origin)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position()
        if not self.cropping:
            return
        if self._drag is None:
            hit = self._hit(pos)
            cursors = {"move": Qt.CursorShape.SizeAllCursor, "tl": Qt.CursorShape.SizeFDiagCursor,
                       "br": Qt.CursorShape.SizeFDiagCursor, "tr": Qt.CursorShape.SizeBDiagCursor,
                       "bl": Qt.CursorShape.SizeBDiagCursor, "t": Qt.CursorShape.SizeVerCursor,
                       "b": Qt.CursorShape.SizeVerCursor, "l": Qt.CursorShape.SizeHorCursor,
                       "r": Qt.CursorShape.SizeHorCursor}
            self.setCursor(cursors.get(hit or "", Qt.CursorShape.CrossCursor))
            return
        p = self._to_image(pos)
        w, h = self.full_size
        if self._drag == "move":
            r = QRectF(self._box_origin)
            r.translate(p - self._drag_origin)
            r.moveLeft(min(max(r.left(), 0), w - r.width()))
            r.moveTop(min(max(r.top(), 0), h - r.height()))
            self.box = r
        elif self._drag == "new":
            self.box = self._constrain(self._drag_origin, p)
        else:
            self.box = self._resize(QRectF(self._box_origin), self._drag, p)
        self.changed.emit()
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._drag is not None:
            self._drag = None
            self.box = self.box.normalized()
            self.update()
        super().mouseReleaseEvent(event)

    def _resize(self, r: QRectF, code: str, p: QPointF) -> QRectF:
        """Drag an edge ("t", "b", "l", "r") or corner ("tl", "br", ...) to p."""
        w, h = self.full_size
        if not self.ratio:
            left, top, right, bottom = r.left(), r.top(), r.right(), r.bottom()
            if "l" in code:
                left = p.x()
            if "r" in code:
                right = p.x()
            if "t" in code:
                top = p.y()
            if "b" in code:
                bottom = p.y()
            box = QRectF(QPointF(left, top), QPointF(right, bottom)).normalized()
            return box.intersected(QRectF(0, 0, w, h))
        # With a fixed ratio the opposite corner stays put and the box scales.
        anchor = QPointF(r.right() if "l" in code else r.left(), r.bottom() if "t" in code else r.top())
        if code in ("l", "r"):
            width = abs(p.x() - anchor.x())
            p = QPointF(p.x(), anchor.y() + width / self.ratio)
        elif code in ("t", "b"):
            height = abs(p.y() - anchor.y())
            p = QPointF(anchor.x() + height * self.ratio, p.y())
        return self._constrain(anchor, p)

    def _constrain(self, anchor: QPointF, p: QPointF) -> QRectF:
        """Box from anchor to p, honouring the aspect ratio and the image bounds."""
        w, h = self.full_size
        dx, dy = p.x() - anchor.x(), p.y() - anchor.y()
        if self.ratio:
            if abs(dx) / self.ratio >= abs(dy):
                dy = (abs(dx) / self.ratio) * (1 if dy >= 0 else -1)
            else:
                dx = (abs(dy) * self.ratio) * (1 if dx >= 0 else -1)
            # Shrink to fit inside the image, keeping the ratio.
            max_x = (w - anchor.x()) if dx >= 0 else anchor.x()
            max_y = (h - anchor.y()) if dy >= 0 else anchor.y()
            factor = min(1.0, max_x / abs(dx) if dx else 1.0, max_y / abs(dy) if dy else 1.0)
            dx, dy = dx * factor, dy * factor
        end = QPointF(min(max(anchor.x() + dx, 0), w), min(max(anchor.y() + dy, 0), h))
        return QRectF(anchor, end).normalized()


class ComparePane(QFrame):
    """One photo in compare mode: the image (with its marks) and a caption. Click to make it active."""

    clicked = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.path = ""
        self.setObjectName("comparePane")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)
        self.canvas = CropCanvas()
        self.canvas.clicked.connect(lambda: self.clicked.emit(self.path))
        self.caption = QLabel()
        self.caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Long names must not make the pane (and the window) wider; they're cut off instead.
        self.caption.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.canvas.setMinimumSize(80, 80)
        layout.addWidget(self.canvas, 1)
        layout.addWidget(self.caption)
        self.set_active(False)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self.clicked.emit(self.path)
        super().mousePressEvent(event)

    def set_active(self, active: bool) -> None:
        self.active = active
        self.setStyleSheet(
            "#comparePane { border: 3px solid palette(highlight); border-radius: 6px; }" if active else
            "#comparePane { border: 3px solid transparent; border-radius: 6px; }")


class PreviewPane(QWidget):
    """Fills the grid area. Shift+P/Esc close, ←/→ move, C crops, Delete recycles.

    With several photos it shows them side by side (compare mode): 2 or 3 in a row,
    4 as a 2×2 grid. Clicking a photo makes it the active one."""

    closed = Signal()
    navigate = Signal(int)
    delete_requested = Signal()
    crop_requested = Signal(str, tuple, bool)  # path, box, as_copy
    active_changed = Signal(str)  # compare mode: the photo that was clicked / arrowed to

    def __init__(self, settings, parent: QWidget | None = None):  # type: ignore[no-untyped-def]
        super().__init__(parent)
        self.settings = settings
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.path = ""
        self.kind = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 6)
        layout.setSpacing(4)

        top = QHBoxLayout()
        self.caption = QLabel()
        self.caption.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        top.addWidget(self.caption, 1)
        self.crop_btn = QPushButton("Crop (C)")
        self.crop_btn.clicked.connect(self.start_crop)
        top.addWidget(self.crop_btn)
        close = QPushButton("Close (Esc)")
        close.clicked.connect(self.closed.emit)
        top.addWidget(close)
        layout.addLayout(top)

        self.crop_bar = QWidget()
        bar = QHBoxLayout(self.crop_bar)
        bar.setContentsMargins(0, 0, 0, 0)
        bar.addWidget(QLabel("Aspect ratio:"))
        self.ratio = QComboBox()
        self.ratio.addItems(list(ASPECT_RATIOS))
        self.ratio.currentTextChanged.connect(lambda _t: self.canvas.set_ratio(self._ratio_value()))
        bar.addWidget(self.ratio)
        self.as_copy = QCheckBox("Save as a copy")
        self.as_copy.setToolTip("Unticked: the cropped photo replaces the original, "
                                "and the original goes to the Recycle Bin.")
        self.as_copy.setChecked(bool(getattr(settings, "crop_as_copy", False)))
        self.as_copy.toggled.connect(lambda on: setattr(settings, "crop_as_copy", on))
        bar.addWidget(self.as_copy)
        bar.addStretch(1)
        bar.addWidget(QLabel("Drag to draw · drag edges/corners to adjust"))
        apply = QPushButton("Save crop (Enter)")
        apply.clicked.connect(self.apply_crop)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.cancel_crop)
        bar.addWidget(apply)
        bar.addWidget(cancel)
        self.crop_bar.setVisible(False)
        layout.addWidget(self.crop_bar)

        self.canvas = CropCanvas()
        self.compare_host = QWidget()
        self.compare_grid = QGridLayout(self.compare_host)
        self.compare_grid.setContentsMargins(0, 0, 0, 0)
        self.compare_grid.setSpacing(6)
        self.panes: list[ComparePane] = []
        self.pages = QStackedWidget()
        self.pages.addWidget(self.canvas)
        self.pages.addWidget(self.compare_host)
        self.video = VideoView(settings)
        self.pages.addWidget(self.video)
        layout.addWidget(self.pages, 1)

    @property
    def cropping(self) -> bool:
        return self.canvas.cropping

    @property
    def comparing(self) -> bool:
        return self.pages.currentWidget() is self.compare_host

    @property
    def showing_video(self) -> bool:
        return self.pages.currentWidget() is self.video

    def stop_video(self) -> None:
        """Stop playback and release the file (before it's moved, renamed, deleted or edited)."""
        self.video.stop()

    # -- compare mode --

    def show_compare(self, items: list[tuple[str, str, object, str]], active: str, caption: str) -> None:
        """items: (path, kind, meta, caption) for 2-4 photos."""
        self.cancel_crop()
        self.stop_video()
        for pane in self.panes:  # take the old photos out right away (not just "later")
            self.compare_grid.removeWidget(pane)
            pane.hide()
            pane.setParent(None)
            pane.deleteLater()
        self.panes = []
        count = len(items)
        columns = 2 if count == 4 else count
        cell_w = max(400, self.width() // max(1, columns))
        cell_h = max(400, self.height() // (2 if count == 4 else 1))
        longest = max(1200, max(cell_w, cell_h) * 2)
        show_type = bool(getattr(self.settings, "type_badges", True))
        for n, (path, kind, meta, text) in enumerate(items):
            pane = ComparePane()
            pane.path = path
            pixmap = load_display_pixmap(path, kind, longest)
            full = (pixmap.width(), pixmap.height()) if pixmap else (0, 0)
            pane.canvas.set_image(pixmap, full, "" if pixmap else "Can't preview this file")
            pane.canvas.set_marks(path, kind, meta, show_type)
            pane.caption.setText(text)
            pane.clicked.connect(self._pane_clicked)
            self.compare_grid.addWidget(pane, n // columns, n % columns)
            self.panes.append(pane)
        for col in range(3):
            self.compare_grid.setColumnStretch(col, 1 if col < columns else 0)
        for row in range(2):
            self.compare_grid.setRowStretch(row, 1 if row < (2 if count == 4 else 1) else 0)
        self.pages.setCurrentWidget(self.compare_host)
        self.crop_btn.setEnabled(False)
        self.crop_btn.setToolTip("Crop works on one photo at a time")
        self.set_active(active, caption)

    def set_active(self, path: str, caption: str = "") -> None:
        self.path = path
        for pane in self.panes:
            pane.set_active(pane.path == path)
        if caption:
            self.caption.setText(caption)

    def _pane_clicked(self, path: str) -> None:
        if path and path != self.path:
            self.active_changed.emit(path)
        self.setFocus()

    def _step_active(self, delta: int) -> None:
        paths = [p.path for p in self.panes]
        if self.path in paths:
            target = paths[(paths.index(self.path) + delta) % len(paths)]
            self.active_changed.emit(target)

    def update_marks_for(self, path: str, meta, caption: str = "") -> None:  # type: ignore[no-untyped-def]
        show_type = bool(getattr(self.settings, "type_badges", True))
        for pane in self.panes:
            if pane.path == path:
                pane.canvas.set_marks(path, pane.canvas.mark_kind, meta, show_type)
                if caption:
                    pane.caption.setText(caption)

    def show_item(self, path: str, kind: str, caption: str, meta=None) -> None:  # type: ignore[no-untyped-def]
        self.stop_video()
        self.path, self.kind = path, kind
        self.caption.setText(caption)
        self.cancel_crop()
        if kind == "video" and self.video.available:
            longest = max(1280, max(self.width(), self.height()))
            self.video.load(path, poster=load_display_pixmap(path, "video", longest))
            self.pages.setCurrentWidget(self.video)
            self.crop_btn.setEnabled(False)
            self.crop_btn.setToolTip("Crop works on photos")
            self.update_marks(meta)
            return
        longest = max(2048, max(self.width(), self.height()) * 2)
        pixmap = load_display_pixmap(path, kind, longest)
        full = (0, 0)
        if pixmap is not None:
            full = (pixmap.width(), pixmap.height())
            if kind == "image":
                try:
                    full = upright_size(path)
                except Exception:  # noqa: BLE001
                    pass
        message = "" if pixmap else "Can't preview this file"
        self.canvas.set_image(pixmap, full, message)
        self.pages.setCurrentWidget(self.canvas)
        self.update_marks(meta)
        self.crop_btn.setToolTip("")
        self.crop_btn.setEnabled(kind == "image" and can_crop(path) and pixmap is not None)

    def update_marks(self, meta) -> None:  # type: ignore[no-untyped-def]
        """Redraw the badges/labels (e.g. after a label hotkey) without reloading the image."""
        show_type = bool(getattr(self.settings, "type_badges", True))
        self.canvas.set_marks(self.path, self.kind, meta, show_type)
        self.video.set_marks(self.path, self.kind, meta, show_type)

    def _ratio_value(self) -> float | None:
        value = ASPECT_RATIOS.get(self.ratio.currentText())
        if value == "original":
            w, h = self.canvas.full_size
            return w / h if h else None
        return value  # type: ignore[return-value]

    def start_crop(self) -> None:
        if not self.crop_btn.isEnabled():
            return
        self.crop_bar.setVisible(True)
        self.canvas.start_crop(self._ratio_value())
        self.setFocus()

    def cancel_crop(self) -> None:
        self.crop_bar.setVisible(False)
        self.canvas.stop_crop()

    def apply_crop(self) -> None:
        if not self.cropping:
            return
        box = self.canvas.crop_box()
        self.cancel_crop()
        self.crop_requested.emit(self.path, box, self.as_copy.isChecked())

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key, mods = event.key(), event.modifiers()
        if key == Qt.Key.Key_Escape:
            if self.cropping:
                self.cancel_crop()
            else:
                self.closed.emit()
        elif key == Qt.Key.Key_P and mods & Qt.KeyboardModifier.ShiftModifier:
            self.closed.emit()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.cropping:
            self.apply_crop()
        elif self.comparing and key in (Qt.Key.Key_Right, Qt.Key.Key_Down, Qt.Key.Key_Tab):
            self._step_active(1)
        elif self.comparing and key in (Qt.Key.Key_Left, Qt.Key.Key_Up, Qt.Key.Key_Backtab):
            self._step_active(-1)
        elif self.showing_video and key == Qt.Key.Key_Space:
            self.video.toggle_play()
        elif self.showing_video and key == Qt.Key.Key_M:
            self.video.toggle_mute()
        elif key == Qt.Key.Key_C and not self.cropping:
            self.start_crop()
        elif self.cropping:
            super().keyPressEvent(event)
        elif key in (Qt.Key.Key_Right, Qt.Key.Key_Down, Qt.Key.Key_Space, Qt.Key.Key_PageDown):
            self.navigate.emit(1)
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_Up, Qt.Key.Key_Backspace, Qt.Key.Key_PageUp):
            self.navigate.emit(-1)
        elif key == Qt.Key.Key_Delete:
            self.delete_requested.emit()
        else:
            super().keyPressEvent(event)
