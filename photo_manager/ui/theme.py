"""Light / dark / system themes. Dark is a deep grey, not pure black."""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

THEMES = {"dark": "Dark", "light": "Light", "system": "Follow Windows"}

DARK = {
    "window": "#26282c",
    "base": "#1e2023",
    "alt": "#2c2f34",
    "button": "#33363c",
    "text": "#e4e6eb",
    "dim": "#9aa0a8",
    "mid": "#4a4e55",
    "highlight": "#3b6fc4",
    "link": "#7aa7ff",
}

_original_style: str | None = None

EXTRA_DARK_CSS = """
QToolTip { color: #e4e6eb; background-color: #33363c; border: 1px solid #4a4e55; }
QDockWidget::title { background: #2c2f34; padding: 4px; }
"""


def _dark_palette() -> QPalette:
    c = {k: QColor(v) for k, v in DARK.items()}
    p = QPalette()
    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
        p.setColor(group, QPalette.ColorRole.Window, c["window"])
        p.setColor(group, QPalette.ColorRole.WindowText, c["text"])
        p.setColor(group, QPalette.ColorRole.Base, c["base"])
        p.setColor(group, QPalette.ColorRole.AlternateBase, c["alt"])
        p.setColor(group, QPalette.ColorRole.ToolTipBase, c["button"])
        p.setColor(group, QPalette.ColorRole.ToolTipText, c["text"])
        p.setColor(group, QPalette.ColorRole.PlaceholderText, c["dim"])
        p.setColor(group, QPalette.ColorRole.Text, c["text"])
        p.setColor(group, QPalette.ColorRole.Button, c["button"])
        p.setColor(group, QPalette.ColorRole.ButtonText, c["text"])
        p.setColor(group, QPalette.ColorRole.BrightText, QColor("#ffffff"))
        p.setColor(group, QPalette.ColorRole.Highlight, c["highlight"])
        p.setColor(group, QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
        p.setColor(group, QPalette.ColorRole.Link, c["link"])
        p.setColor(group, QPalette.ColorRole.Mid, c["mid"])
        p.setColor(group, QPalette.ColorRole.Dark, QColor("#17181b"))
        p.setColor(group, QPalette.ColorRole.Light, QColor("#3d4047"))
        p.setColor(group, QPalette.ColorRole.Midlight, QColor("#383b41"))
        p.setColor(group, QPalette.ColorRole.Shadow, QColor("#0e0f11"))
    disabled = QPalette.ColorGroup.Disabled
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        p.setColor(disabled, role, QColor("#6b7078"))
    for role, key in ((QPalette.ColorRole.Window, "window"), (QPalette.ColorRole.Base, "base"),
                      (QPalette.ColorRole.Button, "button"), (QPalette.ColorRole.Mid, "mid")):
        p.setColor(disabled, role, c[key])
    p.setColor(disabled, QPalette.ColorRole.Highlight, QColor("#3a3d43"))
    return p


def apply_theme(theme: str, app: QApplication | None = None) -> None:
    global _original_style
    app = app or QApplication.instance()  # type: ignore[assignment]
    if app is None:
        return
    if _original_style is None:
        _original_style = app.style().name()
    if theme == "dark":
        app.setStyle("Fusion")
        app.setPalette(_dark_palette())
        app.setStyleSheet(EXTRA_DARK_CSS)
    elif theme == "light":
        app.setStyle("Fusion")
        app.setPalette(app.style().standardPalette())
        app.setStyleSheet("")
    else:
        app.setStyle(_original_style)
        app.setPalette(app.style().standardPalette())
        app.setStyleSheet("")
