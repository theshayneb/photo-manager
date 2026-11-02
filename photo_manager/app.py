"""Start-up: settings, ExifTool, main window."""

from __future__ import annotations

import sys

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
        window = MainWindow(settings, et)
        window.close()
        result["ok"] = bool(result["exiftool"] and result["heic"])
    except Exception as exc:  # noqa: BLE001
        result["error"] = repr(exc)
        result["ok"] = False
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f)
    return 0 if result["ok"] else 1


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv)
    app = QApplication(argv)
    if "--self-test" in argv:
        return self_test(argv[argv.index("--self-test") + 1])
    app.setApplicationName("Photo Manager")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("PhotoManager")
    settings = Settings.load()
    apply_theme(settings.theme, app)
    window = MainWindow(settings, start_exiftool(settings))
    window.show()
    return app.exec()
