"""Start-up: settings, ExifTool, main window."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from . import __version__
from .core.exiftool import ExifTool, ExifToolError, find_exiftool
from .core.settings import Settings
from .ui.main_window import MainWindow
from .ui.theme import apply_theme


def start_exiftool(settings: Settings) -> ExifTool | None:
    path = find_exiftool(settings.exiftool_path or None)
    if not path:
        return None
    et = ExifTool(path)
    try:
        et.execute("-ver")
    except (OSError, ExifToolError):
        et.close()
        return None
    return et


def self_test(out_path: str) -> int:
    """Used by CI on the built exe: check that ExifTool and image plugins load."""
    import json

    from PIL import Image, features

    from .core import thumbs  # noqa: F401  (registers the HEIC opener)

    result: dict[str, object] = {}
    try:
        settings = Settings()
        et = start_exiftool(settings)
        result["exiftool"] = et.execute("-ver")[0].strip() if et else None
        result["heic"] = ".heic" in Image.registered_extensions()
        result["avif"] = bool(features.check("avif"))
        result["icon"] = ICON.exists()
        if sys.platform == "win32":
            from .core.winthumb import shell_thumbnail

            result["shell_thumbnail"] = shell_thumbnail(str(ICON), 64) is not None
        from PySide6.QtMultimedia import QMediaPlayer

        result["video"] = QMediaPlayer().isAvailable()
        window = MainWindow(settings, et)
        window.close()
        result["ok"] = bool(result["exiftool"] and result["heic"] and result["icon"] and result["video"])
    except Exception as exc:  # noqa: BLE001
        result["error"] = repr(exc)
        result["ok"] = False
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f)
    return 0 if result["ok"] else 1


def install_error_handler() -> None:
    """Show unexpected errors instead of failing silently (the exe has no console)."""
    import traceback
    from datetime import datetime

    from PySide6.QtWidgets import QMessageBox

    from .core.settings import cache_dir

    log = cache_dir() / "errors.log"
    showing = False

    def hook(exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        nonlocal showing
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        try:
            log.parent.mkdir(parents=True, exist_ok=True)
            with open(log, "a", encoding="utf-8") as f:
                f.write(f"--- {datetime.now():%Y-%m-%d %H:%M:%S} (v{__version__})\n{text}\n")
        except OSError:
            pass
        sys.__excepthook__(exc_type, exc, tb)
        if showing or QApplication.instance() is None:
            return
        showing = True
        try:
            QMessageBox.warning(None, "Photo Manager — something went wrong",
                                f"{exc_type.__name__}: {exc}\n\nDetails were saved to:\n{log}")
        finally:
            showing = False

    sys.excepthook = hook


ICON = Path(__file__).resolve().parent / "assets" / "icon.png"


def set_app_icon(app: QApplication) -> None:
    if sys.platform == "win32":
        # Its own taskbar identity, so Windows shows our icon rather than Python's.
        import ctypes

        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PhotoManager.PhotoManager")
        except (AttributeError, OSError):
            pass
    if ICON.exists():
        app.setWindowIcon(QIcon(str(ICON)))


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv)
    app = QApplication(argv)
    set_app_icon(app)
    if "--self-test" in argv:
        return self_test(argv[argv.index("--self-test") + 1])
    app.setApplicationName("Photo Manager")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("PhotoManager")
    install_error_handler()
    settings = Settings.load()
    apply_theme(settings.theme, app)
    window = MainWindow(settings, start_exiftool(settings))
    window.show()
    return app.exec()
