"""Import videos from folders (e.g. a network share), including their subfolders.

Everything goes straight into one destination folder (no subfolders). What was imported
is remembered in a small log, so each run only brings in videos that are new since."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .fileops import unique_path
from .media import kind

# Folders NAS boxes and Windows keep for themselves (thumbnails, recycle bins).
SKIP_DIRS = {"@eadir", "#recycle", "#snapshot", "$recycle.bin", "system volume information", ".thumbnails"}


@dataclass
class Found:
    path: str
    size: int
    mtime: float


def file_key(name: str, size: int) -> str:
    """What identifies a video across imports: its name and size."""
    return f"{name.lower()}:{size}"


def find_videos(folders: list[str], exclude: str = "",
                cancelled: Callable[[], bool] | None = None) -> list[Found]:
    """Every video in folders and their subfolders, oldest first. exclude: a folder to leave
    out (the destination, if it's inside one of the folders)."""
    skip = os.path.normcase(os.path.normpath(exclude)) if exclude else ""
    found: list[Found] = []
    seen: set[str] = set()
    for folder in folders:
        for dirpath, dirnames, filenames in os.walk(folder, onerror=lambda _e: None):
            if cancelled and cancelled():
                return []
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and d.lower() not in SKIP_DIRS
                           and os.path.normcase(os.path.join(dirpath, d)) != skip]
            if skip and os.path.normcase(os.path.normpath(dirpath)) == skip:
                continue
            for name in filenames:
                if kind(name) != "video":
                    continue
                path = os.path.join(dirpath, name)
                key = os.path.normcase(os.path.normpath(path))
                if key in seen:
                    continue
                try:
                    st = os.stat(path)
                except OSError:
                    continue
                seen.add(key)
                found.append(Found(path, st.st_size, st.st_mtime))
    found.sort(key=lambda f: (f.mtime, f.path))
    return found


def plan_import(videos: list[Found], dest: str, skip: set[str] | None = None) -> list[tuple[Found, str]]:
    """[(video, destination path)] for videos not imported yet. Already imported: in skip
    (keys from file_key), or a file with the same name and size is in dest. A different
    video with the same name gets "_1" etc."""
    plan: list[tuple[Found, str]] = []
    taken: set[str] = set()
    for video in videos:
        name = os.path.basename(video.path)
        if skip and file_key(name, video.size) in skip:
            continue
        target = Path(dest) / name
        try:
            if target.exists() and target.stat().st_size == video.size:
                continue
        except OSError:
            continue
        final = unique_path(target, taken)
        taken.add(os.path.normcase(str(final)))
        plan.append((video, str(final)))
    return plan


def import_files(plan: list[tuple[Found, str]], move: bool = False,
                 progress: Callable[[int, int, str], None] | None = None,
                 cancelled: Callable[[], bool] | None = None,
                 ) -> tuple[list[tuple[Found, str]], list[tuple[str, str]]]:
    """Copy (or move) the planned videos. Returns (done, failures). cancelled() is checked
    between files, so a file is never left half-copied."""
    done: list[tuple[Found, str]] = []
    failures: list[tuple[str, str]] = []
    for n, (video, target) in enumerate(plan):
        if cancelled and cancelled():
            break
        if progress:
            progress(n, len(plan), os.path.basename(video.path))
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            if move:
                shutil.move(video.path, target)
            else:
                shutil.copy2(video.path, target)
            done.append((video, target))
        except OSError as exc:
            failures.append((video.path, str(exc)))
    return done, failures


def load_log(path: Path) -> set[str]:
    try:
        return {line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}
    except OSError:
        return set()


def add_to_log(path: Path, keys: set[str]) -> None:
    new = set(keys) - load_log(path)
    if not new:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.writelines(k + "\n" for k in sorted(new))
