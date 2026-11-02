"""Run slow work (ExifTool, file operations) off the UI thread."""

from __future__ import annotations

import traceback
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot


class _Relay(QObject):
    """Lives on the UI thread; delivers results there via a queued signal."""

    finished = Signal(object, object, object)  # callback, result, error

    def __init__(self) -> None:
        super().__init__()
        self.finished.connect(self._deliver)

    @Slot(object, object, object)
    def _deliver(self, callback: Callable[[Any, str | None], None], result: Any, error: str | None) -> None:
        if callback:
            callback(result, error)


class _Task(QRunnable):
    def __init__(self, relay: _Relay, fn: Callable[[], Any], callback: Callable[[Any, str | None], None] | None):
        super().__init__()
        self.relay, self.fn, self.callback = relay, fn, callback

    def run(self) -> None:
        try:
            result, error = self.fn(), None
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            result, error = None, str(exc) or exc.__class__.__name__
        self.relay.finished.emit(self.callback, result, error)


class Background:
    """Background(pool).run(fn, callback) -> callback(result, error) on the UI thread."""

    def __init__(self, threads: int = 1) -> None:
        self.pool = QThreadPool()
        self.pool.setMaxThreadCount(threads)
        self._relay = _Relay()

    def run(self, fn: Callable[[], Any], callback: Callable[[Any, str | None], None] | None = None) -> None:
        self.pool.start(_Task(self._relay, fn, callback))

    def wait(self, msecs: int = -1) -> bool:
        return self.pool.waitForDone(msecs)
