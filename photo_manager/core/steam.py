"""Import Steam screenshots from the Steam folder on this PC.

Steam keeps every screenshot locally (uploaded or not) in
    <Steam>/userdata/<account id>/760/remote/<app id>/screenshots/
named like 20261104213012_1.jpg (the date and time it was taken, local time).
A "thumbnails" subfolder holds small copies, which are skipped.

Game names come from Steam's own app manifests (steamapps/appmanifest_<id>.acf)
in every Steam library folder listed in steamapps/libraryfolders.vdf. Games that
aren't installed on this PC (e.g. screenshots synced from a Steam Deck) can be named
from the Steam store (fetch_store_names); the caller keeps those names cached.
"""

from __future__ import annotations

import os
import json
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .fileops import unique_path

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".jxr", ".bmp", ".tif", ".tiff", ".heic"}
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


def fetch_store_names(app_ids: list[str], timeout: float = 5.0) -> dict[str, str]:
    """{app id: name} from the Steam store for games not installed here.

    An id the store doesn't know (e.g. a non-Steam game) maps to "" so it isn't asked
    again; an id that couldn't be checked (no internet) is left out."""
    import urllib.request

    found: dict[str, str] = {}
    for app_id in app_ids:
        url = f"https://store.steampowered.com/api/appdetails?appids={app_id}&filters=basic"
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8", "replace"))
        except (OSError, ValueError):
            continue
        entry = data.get(app_id) if isinstance(data, dict) else None
        if not isinstance(entry, dict):
            continue
        name = entry.get("data", {}).get("name", "") if entry.get("success") else ""
        found[app_id] = name if isinstance(name, str) else ""
    return found


def unnamed_app_ids(shots: list["Shot"]) -> list[str]:
    """App ids whose game name isn't known (shown as "App 12345")."""
    return sorted({s.app_id for s in shots if s.app_id.isdigit() and s.game == f"App {s.app_id}"})


# -- screenshots -----------------------------------------------------------------

def taken_from_name(name: str) -> datetime | None:
    match = _NAME.match(name)
    if not match:
        return None
    try:
        return datetime(*(int(g) for g in match.groups()))  # type: ignore[arg-type]
    except ValueError:
        return None


def parse_vdf(text: str) -> dict:
    """Steam's text VDF/ACF format: nested {"key": "value" | {...}}."""
    tokens = re.findall(r'"((?:[^"\\]|\\.)*)"|([{}])', text)
    root: dict = {}
    stack = [root]
    key: str | None = None
    for quoted, brace in tokens:
        if brace == "{":
            child: dict = {}
            if key is not None:
                stack[-1][key] = child
            stack.append(child)
            key = None
        elif brace == "}":
            if len(stack) > 1:
                stack.pop()
            key = None
        else:
            value = quoted.replace("\\\\", "\\").replace('\\"', '"')
            if key is None:
                key = value
            else:
                stack[-1][key] = value
                key = None
    return root


def _indexed_files(steam: str, account: str) -> list[tuple[str, str]]:
    """[(app id, file path)] from Steam's screenshot index (760/screenshots.vdf).

    This also covers screenshots a game saved itself and added to Steam's library,
    which can live outside the usual folder."""
    base = Path(steam) / "userdata" / account / "760"
    try:
        data = parse_vdf((base / "screenshots.vdf").read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return []
    top = next((v for k, v in data.items() if k.lower() == "screenshots" and isinstance(v, dict)), {})
    found = []
    for app_id, entries in top.items():
        if not isinstance(entries, dict) or not app_id.isdigit():
            continue
        for entry in entries.values():
            if not isinstance(entry, dict) or not entry.get("filename"):
                continue
            name = entry["filename"].replace("/", os.sep).replace("\\", os.sep)
            path = Path(name) if os.path.isabs(name) or re.match(r"^[A-Za-z]:", name) else base / "remote" / name
            found.append((app_id, str(path)))
    return found


def find_screenshots(steam: str, account: str | None = None,
                     extra_folders: list[str] | None = None,
                     known_names: dict[str, str] | None = None) -> list[Shot]:
    """Every screenshot of one account (or all accounts), oldest first.

    Looks in Steam's screenshot folders, in Steam's own screenshot index, and in any
    extra folders (with their subfolders). The same screenshot found twice is listed once.
    An extra folder can be a copy of another device's 760/remote folder (e.g. synced from
    a Steam Deck): files in <app id>/screenshots/ get that game's name.
    known_names: extra {app id: name}, e.g. cached names from the Steam store."""
    names = {k: v for k, v in (known_names or {}).items() if v}
    names.update(game_names(steam) if steam else {})
    ids = ([account] if account else accounts(steam)) if steam else []
    shots: list[Shot] = []
    seen: set[str] = set()

    def add(path: str, app_id: str, game: str) -> None:
        key = os.path.normcase(os.path.normpath(path))
        if key in seen or Path(path).suffix.lower() not in IMAGE_EXTS or not os.path.isfile(path):
            return
        seen.add(key)
        shots.append(Shot(path, app_id, game, taken_from_name(os.path.basename(path))))

    for acct in ids:
        remote = Path(steam) / "userdata" / acct / "760" / "remote"
        if remote.is_dir():
            for app_dir in remote.iterdir():
                folder = app_dir / "screenshots"
                if folder.is_dir():
                    for file in folder.iterdir():  # not recursive: skips the "thumbnails" folder
                        add(str(file), app_dir.name, names.get(app_dir.name, f"App {app_dir.name}"))
        for app_id, path in _indexed_files(steam, acct):
            add(path, app_id, names.get(app_id, f"App {app_id}"))
    for folder in extra_folders or []:
        for dirpath, dirnames, filenames in os.walk(folder):
            dirnames[:] = [d for d in dirnames if d.lower() != "thumbnails"]
            here, parent = os.path.basename(dirpath), os.path.basename(os.path.dirname(dirpath))
            if here.lower() == "screenshots" and parent.isdigit():  # <app id>/screenshots, Steam's layout
                app_id, game = parent, names.get(parent, f"App {parent}")
            elif os.path.normcase(dirpath) != os.path.normcase(folder):
                app_id, game = "", here
            else:
                app_id, game = "", "Other"
            for filename in filenames:
                add(os.path.join(dirpath, filename), app_id, game)
    # A screenshot saved in two places (e.g. Steam's copy + an uncompressed copy) is one screenshot:
    # keep one per file name stem, preferring the bigger (better quality) file.
    best: dict[str, Shot] = {}
    for shot in shots:
        stem = os.path.splitext(os.path.basename(shot.path))[0].lower()
        if not _NAME.match(stem):  # not a Steam-style name: never merged
            best[shot.path] = shot
            continue
        current = best.get(stem)
        if current is None:
            best[stem] = shot
            continue
        bigger = shot if os.path.getsize(shot.path) > os.path.getsize(current.path) else current
        other = current if bigger is shot else shot
        if bigger.game == "Other" and other.game != "Other":  # keep the real game name
            bigger = Shot(bigger.path, other.app_id, other.game, bigger.taken)
        best[stem] = bigger
    result = list(best.values())
    result.sort(key=lambda s: (s.taken or datetime.max, s.path))
    return result


def per_game(shots: list[Shot]) -> list[tuple[str, int, datetime | None]]:
    """[(game, count, newest)] sorted by newest first, to show what was found."""
    games: dict[str, list[Shot]] = {}
    for shot in shots:
        games.setdefault(shot.game, []).append(shot)
    rows = [(g, len(s), max((x.taken for x in s if x.taken), default=None)) for g, s in games.items()]
    rows.sort(key=lambda r: r[2] or datetime.min, reverse=True)
    return rows


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
