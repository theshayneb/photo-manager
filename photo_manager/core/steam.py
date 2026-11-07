"""Import Steam screenshots from the Steam folder on this PC.

Steam keeps every screenshot locally (uploaded or not) in
    <Steam>/userdata/<account id>/760/remote/<app id>/screenshots/
named like 20261104213012_1.jpg (the date and time it was taken, local time).
A "thumbnails" subfolder holds small copies, which are skipped.

Game names come from Steam's own app manifests (steamapps/appmanifest_<id>.acf)
in every Steam library folder listed in steamapps/libraryfolders.vdf.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .fileops import unique_path

IMAGE_EXTS = {".jpg", ".jpeg", ".png"}
_NAME = re.compile(r"^(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})")


@dataclass
class Shot:
    path: str
    app_id: str
    game: str
    taken: datetime | None


# -- finding Steam -------------------------------------------------------------

def find_steam() -> str | None:
    """The Steam install folder, from the registry on Windows, else common places."""
    candidates: list[str] = []
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                candidates.append(winreg.QueryValueEx(key, "SteamPath")[0])
        except OSError:
            pass
        for env in ("ProgramFiles(x86)", "ProgramFiles"):
            if os.environ.get(env):
                candidates.append(os.path.join(os.environ[env], "Steam"))
    else:
        home = Path.home()
        candidates += [str(home / ".steam" / "steam"), str(home / ".local" / "share" / "Steam")]
    for path in candidates:
        if path and os.path.isdir(os.path.join(path, "userdata")):
            return os.path.normpath(path)
    return None


def accounts(steam: str) -> list[str]:
    """Account folders (ids) under userdata that have screenshots."""
    root = Path(steam) / "userdata"
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if (p / "760" / "remote").is_dir())


# -- game names ------------------------------------------------------------------

def _library_folders(steam: str) -> list[Path]:
    folders = [Path(steam)]
    vdf = Path(steam) / "steamapps" / "libraryfolders.vdf"
    try:
        text = vdf.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return folders
    for match in re.finditer(r'"path"\s+"([^"]+)"', text):
        path = Path(match.group(1).replace("\\\\", "\\"))
        if path not in folders:
            folders.append(path)
    return folders


def game_names(steam: str) -> dict[str, str]:
    """{app id: game name} from every library's app manifests."""
    names: dict[str, str] = {}
    for library in _library_folders(steam):
        apps = library / "steamapps"
        if not apps.is_dir():
            continue
        for manifest in apps.glob("appmanifest_*.acf"):
            try:
                text = manifest.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            app = re.search(r'"appid"\s+"(\d+)"', text)
            name = re.search(r'"name"\s+"([^"]+)"', text)
            if app and name:
                names[app.group(1)] = name.group(1)
    return names


# -- screenshots -----------------------------------------------------------------

def taken_from_name(name: str) -> datetime | None:
    match = _NAME.match(name)
    if not match:
        return None
    try:
        return datetime(*(int(g) for g in match.groups()))  # type: ignore[arg-type]
    except ValueError:
        return None


def find_screenshots(steam: str, account: str | None = None) -> list[Shot]:
    """Every screenshot of one account (or all accounts), oldest first."""
    names = game_names(steam)
    ids = [account] if account else accounts(steam)
    shots: list[Shot] = []
    for acct in ids:
        remote = Path(steam) / "userdata" / acct / "760" / "remote"
        if not remote.is_dir():
            continue
        for app_dir in remote.iterdir():
            folder = app_dir / "screenshots"
            if not folder.is_dir():
                continue
            app_id = app_dir.name
            game = names.get(app_id, f"App {app_id}")
            for file in folder.iterdir():  # not recursive: skips the "thumbnails" folder
                if file.is_file() and file.suffix.lower() in IMAGE_EXTS:
                    shots.append(Shot(str(file), app_id, game, taken_from_name(file.name)))
    shots.sort(key=lambda s: (s.taken or datetime.max, s.path))
    return shots


def plan_import(shots: list[Shot], dest: str) -> list[tuple[Shot, str]]:
    """[(shot, destination path)] for the screenshots not imported yet. Everything goes
    straight into dest (no subfolders).

    A screenshot counts as already imported when a file with the same name and size
    is in dest. Same name but different size gets "_1" etc."""
    plan: list[tuple[Shot, str]] = []
    taken: set[str] = set()
    for shot in shots:
        target = Path(dest) / Path(shot.path).name
        try:
            if target.exists() and target.stat().st_size == os.path.getsize(shot.path):
                continue
        except OSError:
            continue
        final = unique_path(target, taken)
        taken.add(os.path.normcase(str(final)))
        plan.append((shot, str(final)))
    return plan


def import_shots(plan: list[tuple[Shot, str]]) -> tuple[list[tuple[Shot, str]], list[tuple[str, str]]]:
    """Copy the planned screenshots (Steam's own files are never changed)."""
    done: list[tuple[Shot, str]] = []
    failures: list[tuple[str, str]] = []
    for shot, target in plan:
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(shot.path, target)
            done.append((shot, target))
        except OSError as exc:
            failures.append((shot.path, str(exc)))
    return done, failures
