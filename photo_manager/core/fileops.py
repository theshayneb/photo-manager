"""Delete (to the Recycle Bin), move and rename files without overwriting anything."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from send2trash import send2trash


def unique_path(target: Path, taken: set[str] | None = None) -> Path:
    """Return target, or target with _1, _2 ... added if that name is used."""
    taken = taken or set()

    def used(p: Path) -> bool:
        return p.exists() or os.path.normcase(str(p)) in taken

    if not used(target):
        return target
    n = 1
    while True:
        candidate = target.with_name(f"{target.stem}_{n}{target.suffix}")
        if not used(candidate):
            return candidate
        n += 1


def recycle(paths: list[str]) -> list[tuple[str, str]]:
    """Send files to the Recycle Bin. Returns [(path, error)] for failures."""
    failures = []
    for path in paths:
        try:
            send2trash(path)
        except OSError as exc:
            failures.append((path, str(exc)))
    return failures


def move(paths: list[str], folder: str) -> tuple[dict[str, str], list[tuple[str, str]]]:
    """Move files into folder. Returns ({old: new}, [(path, error)])."""
    moved: dict[str, str] = {}
    failures = []
    dest_dir = Path(folder)
    for path in paths:
        src = Path(path)
        if os.path.normcase(str(src.parent)) == os.path.normcase(str(dest_dir)):
            continue
        try:
            dest = unique_path(dest_dir / src.name)
            move_one(str(src), str(dest))
            moved[path] = str(dest)
        except OSError as exc:
            failures.append((path, friendly_error(exc)))
    return moved, failures


IN_USE_RETRY_SECONDS = 3.0


def _is_in_use(exc: OSError) -> bool:
    # Windows: 32 = sharing violation, 33 = lock violation, 5 = access denied (often a brief lock)
    return getattr(exc, "winerror", None) in (5, 32, 33) or isinstance(exc, PermissionError)


def _is_other_drive(exc: OSError) -> bool:
    import errno

    return exc.errno == errno.EXDEV or getattr(exc, "winerror", None) == 17


def move_one(src: str, dest: str, retry_seconds: float | None = None) -> None:
    """Move one file. A file that's briefly in use (e.g. a video that just stopped playing)
    is retried for a few seconds. Copy-then-delete is only used across drives, and if the
    original can't be deleted the copy is removed again, so a file never ends up in two places."""
    import time

    if retry_seconds is None:
        retry_seconds = IN_USE_RETRY_SECONDS
    deadline = time.monotonic() + retry_seconds
    while True:
        try:
            os.rename(src, dest)
            return
        except OSError as exc:
            if _is_other_drive(exc):
                break
            if _is_in_use(exc) and time.monotonic() < deadline:
                time.sleep(0.25)
                continue
            raise
    # Different drive: copy, then delete the original (retrying if it's briefly in use).
    shutil.copy2(src, dest)
    while True:
        try:
            os.remove(src)
            return
        except OSError as exc:
            if _is_in_use(exc) and time.monotonic() < deadline:
                time.sleep(0.25)
                continue
            try:
                os.remove(dest)  # don't leave a second copy behind
            except OSError:
                pass
            raise


def friendly_error(exc: OSError) -> str:
    if _is_in_use(exc):
        return "the file is in use by another program (close it there and try again)"
    return str(exc)


def copy(paths: list[str], folder: str) -> tuple[dict[str, str], list[tuple[str, str]]]:
    """Copy files into folder (never overwriting). Returns ({old: new}, [(path, error)])."""
    copied: dict[str, str] = {}
    failures = []
    for path in paths:
        try:
            dest = unique_path(Path(folder) / Path(path).name)
            shutil.copy2(path, dest)
            copied[path] = str(dest)
        except OSError as exc:
            failures.append((path, str(exc)))
    return copied, failures


INVALID_NAME_CHARS = set('<>:"/\\|?*')


def check_new_name(path: str, new_name: str) -> str | None:
    """Problem with renaming path to new_name (in the same folder), or None if fine."""
    name = new_name.strip()
    if not name or name in (".", ".."):
        return "Please type a name."
    bad = sorted({c for c in name if c in INVALID_NAME_CHARS or ord(c) < 32})
    if bad:
        return "A file name can't contain " + " ".join(bad)
    if name.endswith((".", " ")):
        return "A file name can't end with a dot or a space."
    target = Path(path).with_name(name)
    if target.exists() and os.path.normcase(str(target)) != os.path.normcase(path):
        return f"“{name}” already exists in this folder."
    return None


def plan_renames(new_names: dict[str, str]) -> dict[str, str]:
    """Turn {path: new base name (no extension)} into {path: unique new path}."""
    plan: dict[str, str] = {}
    taken: set[str] = set()
    for path, base in new_names.items():
        src = Path(path)
        target = src.with_name(base + src.suffix)
        if os.path.normcase(str(target)) == os.path.normcase(str(src)):
            continue
        dest = unique_path(target, taken)
        taken.add(os.path.normcase(str(dest)))
        plan[path] = str(dest)
    return plan


def rename(plan: dict[str, str]) -> tuple[dict[str, str], list[tuple[str, str]]]:
    done: dict[str, str] = {}
    failures = []
    for src, dest in plan.items():
        try:
            same_file = os.path.normcase(src) == os.path.normcase(dest)  # e.g. only the case changes
            if Path(dest).exists() and not same_file:
                raise FileExistsError(f"{dest} already exists")
            os.rename(src, dest)
            done[src] = dest
        except OSError as exc:
            failures.append((src, str(exc)))
    return done, failures
