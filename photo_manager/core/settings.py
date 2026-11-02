"""User settings, saved as JSON in %APPDATA%\\PhotoManager\\settings.json."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .dates import DEFAULT_DISPLAY_FORMAT
from .templates import DEFAULT_TEMPLATES, FilenameTemplate

APP_NAME = "PhotoManager"


def config_dir() -> Path:
    base = os.environ.get("APPDATA") or os.path.join(Path.home(), ".config")
    return Path(base) / APP_NAME


def cache_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.path.join(Path.home(), ".cache")
    return Path(base) / APP_NAME


def _default_keyword_sets() -> dict[str, list[str]]:
    return {
        "Shayne": [
            "me", "josh", "new york", "queens", "rego park", "manhattan",
            "brooklyn", "concert", "broadway", "museum", "screenshots",
        ],
    }


DEFAULT_LABEL_HOTKEYS = {
    "Red": "Ctrl+1", "Yellow": "Ctrl+2", "Green": "Ctrl+3", "Blue": "Ctrl+4", "Purple": "Ctrl+5",
    "None": "Ctrl+0", "Star": "Ctrl+S", "Bookmark": "Ctrl+B",
}

DEFAULT_RENAME_PATTERN = "{MM}-{DD}-{YYYY} {hh}-{mm}-{ss} {AMPM}"  # 08-15-2026 11-42-44 AM

DEFAULT_RENAME_PRESETS = [
    DEFAULT_RENAME_PATTERN,
    "{YYYY}-{MM}-{DD}_{HH}-{mm}-{ss}",
    "{YYYY}{MM}{DD}{HH}{mm}{ss}",
    "{YYYY}-{MM}-{DD} {name}",
]


@dataclass
class Settings:
    last_folder: str = ""
    display_format: str = DEFAULT_DISPLAY_FORMAT
    set_file_dates: bool = True
    rename_pattern: str = DEFAULT_RENAME_PATTERN
    confirm_delete: bool = True
    thumb_size: int = 160
    sort_by: str = "name"
    exiftool_path: str = ""
    keyword_sets: dict[str, list[str]] = field(default_factory=_default_keyword_sets)
    current_keyword_set: str = "Shayne"
    templates: list[FilenameTemplate] = field(
        default_factory=lambda: [FilenameTemplate(**t.to_dict()) for t in DEFAULT_TEMPLATES]
    )
    known_default_templates: list[str] = field(default_factory=list)
    rename_presets: list[str] = field(default_factory=lambda: list(DEFAULT_RENAME_PRESETS))
    recent_move_folders: list[str] = field(default_factory=list)
    favorites: list[str] = field(default_factory=list)
    rename_source: str = "taken"  # taken | created | file_created | file_modified
    theme: str = "dark"  # dark | light | system
    group_by: str = "none"  # none | day | week | month | label
    week_start: str = "sunday"  # sunday | monday
    thumb_info: list[str] = field(default_factory=lambda: ["date"])
    hidden_panels: list[str] = field(default_factory=list)
    collapsed_panels: list[str] = field(default_factory=list)
    crop_as_copy: bool = False
    label_hotkeys: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_LABEL_HOTKEYS))
    convert_target: str = "JPG"
    convert_quality: int = 92
    convert_recycle: bool = False
    highlight_misnamed: bool = True
    type_badges: bool = True
    migrations: list[str] = field(default_factory=list)
    window_geometry: str = ""
    window_state: str = ""

    path: Path = field(default_factory=lambda: config_dir() / "settings.json", repr=False)

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        settings = cls()
        if path:
            settings.path = path
        try:
            data = json.loads(settings.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return settings
        for key, value in data.items():
            if key == "path" or not hasattr(settings, key):
                continue
            if key == "templates":
                value = [FilenameTemplate.from_dict(t) for t in value if isinstance(t, dict)]
            default = getattr(settings, key)
            if type(default) is type(value) or key == "templates":
                setattr(settings, key, value)
        settings._add_new_default_templates()
        settings._migrate()
        for key, keys in DEFAULT_LABEL_HOTKEYS.items():  # labels added in later versions
            settings.label_hotkeys.setdefault(key, keys)
        if not settings.keyword_sets:
            settings.keyword_sets = {"Keywords": []}
        if settings.current_keyword_set not in settings.keyword_sets:
            settings.current_keyword_set = next(iter(settings.keyword_sets))
        return settings

    def _migrate(self) -> None:
        """One-time changes to existing settings when defaults change."""
        if "rename-us-format" not in self.migrations:
            # 0.5.0: the preferred rename format became "08-15-2026 11-42-44 AM".
            if self.rename_pattern == "{YYYY}-{MM}-{DD}_{HH}-{mm}-{ss}":
                self.rename_pattern = DEFAULT_RENAME_PATTERN
            self.rename_presets = [DEFAULT_RENAME_PATTERN] + [
                p for p in self.rename_presets if p != DEFAULT_RENAME_PATTERN]
            self.migrations.append("rename-us-format")

    def _add_new_default_templates(self) -> None:
        """Give existing users templates added in newer versions (once each)."""
        known = set(self.known_default_templates)
        have = {t.pattern for t in self.templates}
        for index, template in enumerate(DEFAULT_TEMPLATES):
            if template.pattern not in known and template.pattern not in have:
                self.templates.insert(min(index, len(self.templates)), FilenameTemplate(**template.to_dict()))
        self.known_default_templates = [t.pattern for t in DEFAULT_TEMPLATES]

    def save(self) -> None:
        data = asdict(self)
        data.pop("path", None)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)

    def remember_move_folder(self, folder: str) -> None:
        folders = [f for f in self.recent_move_folders if os.path.normcase(f) != os.path.normcase(folder)]
        self.recent_move_folders = [folder, *folders][:12]
