"""Video playback for the big preview.

Every video starts MUTED. Auto-play is a remembered setting. The player is
always stopped and its file released before leaving a video, so Windows
can move/delete/rename it straight away.
"""

from __future__ import annotations

from PySide6.QtCore import QRect, QRectF, QSizeF, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from .grid import paint_flags, paint_label_frame, paint_type_badge

try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink

    HAVE_MULTIMEDIA = True
except ImportError:  # pragma: no cover - Qt built without multimedia
    HAVE_MULTIMEDIA = False


def _fmt(ms: int) -> str:
    seconds = max(0, ms) // 1000
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


class _VideoScreen(QWidget):
    """Paints the current video frame (or the still thumbnail before playback starts),
    fitted to the widget, with the type badge, ★/🔖 and color-label frame on top."""

    clicked = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.frame = QImage()     # latest decoded frame
        self.poster = QPixmap()   # shown until the first frame arrives
        self.marks: tuple = ("", "", None, True)  # path, kind, meta, show_type

    def set_poster(self, pixmap: QPixmap | None) -> None:
        self.poster = pixmap or QPixmap()
        self.frame = QImage()
        self.update()

    def set_frame(self, image: QImage) -> None:
        if not image.isNull():
            self.frame = image
            self.update()

    def clear(self) -> None:
        self.frame = QImage()
        self.poster = QPixmap()
        self.update()

    def picture_rect(self) -> QRect:
        if not self.frame.isNull():
            size = QSizeF(self.frame.size())
        elif not self.poster.isNull():
            size = QSizeF(self.poster.size())
        else:
            return QRect()
        area = QRectF(self.rect())
        size.scale(area.size(), Qt.AspectRatioMode.KeepAspectRatio)
        rect = QRectF(0, 0, size.width(), size.height())
        rect.moveCenter(area.center())
        return rect.toRect()

    def paintEvent(self, _event) -> None:  # type: ignore[no-untyped-def]
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("black"))
        target = self.picture_rect()
        if target.isEmpty():
            return
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if not self.frame.isNull():
            painter.drawImage(target, self.frame)
        else:
            painter.drawPixmap(target, self.poster)
        path, kind, meta, show_type = self.marks
        if path:
            scale = 1.6
            paint_label_frame(painter, target.adjusted(5, 5, -5, -5), meta, scale)
            paint_flags(painter, target, meta, scale)
            if show_type:
                paint_type_badge(painter, target, path, kind, self.font(), scale)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class VideoView(QWidget):
    """Video + controls: play/pause, seek, time, mute, auto-play."""

    def __init__(self, settings, parent: QWidget | None = None):  # type: ignore[no-untyped-def]
        super().__init__(parent)
        self.settings = settings
        self.path = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # The player is created BEFORE the picture area: Qt deletes children in creation
        # order, and the player must go first or it calls into a destroyed video item.
        self.player = QMediaPlayer(self) if HAVE_MULTIMEDIA else None
        self.audio = QAudioOutput(self) if HAVE_MULTIMEDIA else None
        self.sink = QVideoSink(self) if HAVE_MULTIMEDIA else None

        self.video = _VideoScreen()
        self.video.clicked.connect(self.toggle_play)
        layout.addWidget(self.video, 1)

        bar = QHBoxLayout()
        self.play_btn = QPushButton("▶")
        self.play_btn.setFixedWidth(40)
        self.play_btn.setToolTip("Play / pause (Space)")
        self.play_btn.clicked.connect(self.toggle_play)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.sliderMoved.connect(self._seek)
        self.time = QLabel("0:00 / 0:00")
        self.mute_btn = QPushButton("🔇")
        self.mute_btn.setFixedWidth(40)
        self.mute_btn.setToolTip("Sound on / off (M). Videos always start muted.")
        self.mute_btn.clicked.connect(self.toggle_mute)
        self.autoplay = QCheckBox("Auto-play")
        self.autoplay.setToolTip("Start playing as soon as a video is shown (remembered)")
        self.autoplay.setChecked(bool(getattr(settings, "video_autoplay", False)))
        self.autoplay.toggled.connect(lambda on: setattr(settings, "video_autoplay", on))
        for widget in (self.play_btn, self.slider, self.time, self.mute_btn, self.autoplay):
            bar.addWidget(widget, 1 if widget is self.slider else 0)
        layout.addLayout(bar)

        if self.player is not None:
            self.player.setAudioOutput(self.audio)
            self.player.setVideoSink(self.sink)
            self.sink.videoFrameChanged.connect(self._frame)
            self.player.positionChanged.connect(self._position)
            self.player.durationChanged.connect(self._duration)
            self.player.playbackStateChanged.connect(self._state)
            self.player.mediaStatusChanged.connect(self._status)

    @property
    def available(self) -> bool:
        return self.player is not None

    def shutdown(self) -> None:
        """Stop and detach the player from the picture (called when the app closes)."""
        self.stop()
        if self.player is not None:
            self.sink.videoFrameChanged.disconnect(self._frame)
            self.player.setVideoSink(None)
            self.player.setAudioOutput(None)

    # -- loading --

    def set_marks(self, path: str, kind: str, meta, show_type: bool) -> None:  # type: ignore[no-untyped-def]
        self.video.marks = (path, kind, meta, show_type)
        self.video.update()

    def load(self, path: str, poster: QPixmap | None = None) -> None:
        self.stop()
        self.path = path
        self.video.set_poster(poster)  # still frame until playback starts
        if not self.player:
            return
        self.audio.setMuted(True)  # always start muted
        self._update_mute()
        self.player.setSource(QUrl.fromLocalFile(path))
        if self.autoplay.isChecked():
            self.player.play()

    def stop(self) -> None:
        """Stop and release the file (so it can be moved/deleted)."""
        if self.player:
            self.player.stop()
            self.player.setSource(QUrl())
        self.path = ""
        self.video.clear()
        self.slider.setRange(0, 0)
        self.time.setText("0:00 / 0:00")
        self.play_btn.setText("▶")

    # -- controls --

    def is_playing(self) -> bool:
        return bool(self.player) and self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    def toggle_play(self) -> None:
        if not self.player or not self.path:
            return
        if self.is_playing():
            self.player.pause()
        else:
            self.player.play()

    def toggle_mute(self) -> None:
        if self.audio:
            self.audio.setMuted(not self.audio.isMuted())
            self._update_mute()

    def is_muted(self) -> bool:
        return bool(self.audio) and self.audio.isMuted()

    def _update_mute(self) -> None:
        self.mute_btn.setText("🔇" if self.is_muted() else "🔊")

    def _seek(self, position: int) -> None:
        if self.player:
            self.player.setPosition(position)

    def _position(self, position: int) -> None:
        if not self.slider.isSliderDown():
            self.slider.setValue(position)
        self.time.setText(f"{_fmt(position)} / {_fmt(self.slider.maximum())}")

    def _duration(self, duration: int) -> None:
        self.slider.setRange(0, max(0, duration))
        self.time.setText(f"{_fmt(self.slider.value())} / {_fmt(duration)}")

    def _state(self, _state) -> None:  # type: ignore[no-untyped-def]
        playing = self.is_playing()
        self.play_btn.setText("⏸" if playing else "▶")


    def _frame(self, frame) -> None:  # type: ignore[no-untyped-def]
        if self.path and frame.isValid():
            self.video.set_frame(frame.toImage())

    def _status(self, status) -> None:  # type: ignore[no-untyped-def]
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.play_btn.setText("▶")
