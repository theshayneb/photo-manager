"""A long-running ExifTool process (-stay_open) shared by the whole app.

Starting exiftool.exe takes a moment on Windows, so we start it once and
send it commands. Every call is serialised with a lock, so background
threads (metadata loading) and the UI (writes) can share one instance.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

# Applied to every command.
COMMON_ARGS = ["-charset", "filename=utf8", "-api", "QuickTimeUTC=1"]


class ExifToolError(RuntimeError):
    pass


def find_exiftool(custom: str | None = None) -> str | None:
    """Look for exiftool next to the app, in vendor/, then on PATH."""
    candidates: list[Path] = []
    if custom:
        candidates.append(Path(custom))
    names = ["exiftool.exe", "exiftool"] if os.name == "nt" else ["exiftool"]
    roots = []
    if getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).parent)
        roots.append(Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)))
    roots.append(Path(__file__).resolve().parents[2])  # repo root when run from source
    for root in roots:
        for sub in ("exiftool", "vendor/exiftool", ""):
            for name in names:
                candidates.append(root / sub / name)
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


class ExifTool:
    def __init__(self, command: list[str] | str):
        self._command = [command] if isinstance(command, str) else list(command)
        self._proc: subprocess.Popen[bytes] | None = None
        self._lock = threading.Lock()
        self._counter = 0

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        if self._proc and self._proc.poll() is None:
            return
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        self._proc = subprocess.Popen(
            [*self._command, "-stay_open", "True", "-@", "-", "-common_args", *COMMON_ARGS],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=flags,
        )

    def close(self) -> None:
        with self._lock:
            proc, self._proc = self._proc, None
            if not proc:
                return
            try:
                if proc.poll() is None and proc.stdin:
                    proc.stdin.write(b"-stay_open\nFalse\n")
                    proc.stdin.flush()
                proc.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                proc.kill()
                proc.wait(timeout=5)
            finally:
                for stream in (proc.stdin, proc.stdout, proc.stderr):
                    if stream:
                        try:
                            stream.close()
                        except OSError:
                            pass

    def __enter__(self) -> "ExifTool":
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- commands ----------------------------------------------------------

    def execute(self, *args: str) -> tuple[str, str]:
        """Run one ExifTool command. Returns (stdout, stderr)."""
        for arg in args:
            if "\n" in arg or "\r" in arg:
                raise ExifToolError("Arguments can't contain line breaks.")
        with self._lock:
            self.start()
            proc = self._proc
            assert proc and proc.stdin and proc.stdout and proc.stderr
            self._counter += 1
            marker = f"{{ready{self._counter}}}"
            lines = [*args, "-echo4", marker, f"-execute{self._counter}"]
            try:
                proc.stdin.write(("\n".join(lines) + "\n").encode("utf-8"))
                proc.stdin.flush()
                out = self._read_until(proc.stdout, marker)
                err = self._read_until(proc.stderr, marker)
            except (OSError, ExifToolError):
                proc.kill()
                self._proc = None
                raise
            return out, err

    @staticmethod
    def _read_until(stream, marker: str) -> str:  # type: ignore[no-untyped-def]
        chunks: list[str] = []
        while True:
            raw = stream.readline()
            if not raw:
                raise ExifToolError("ExifTool stopped unexpectedly.")
            line = raw.decode("utf-8", errors="replace")
            if line.rstrip("\r\n") == marker:
                return "".join(chunks)
            chunks.append(line)

    def read(self, paths: list[str], tags: list[str]) -> list[dict]:
        """Read tags for many files as JSON dicts (keys like "EXIF:DateTimeOriginal")."""
        if not paths:
            return []
        out, _err = self.execute("-j", "-G0", "-fast", *tags, *paths)
        if not out.strip():
            return []
        try:
            return json.loads(out)
        except json.JSONDecodeError as exc:
            raise ExifToolError(f"Couldn't read ExifTool output: {exc}") from exc

    def write(self, path: str, args: list[str]) -> str | None:
        """Write tags to one file. Returns an error message, or None on success."""
        out, err = self.execute("-overwrite_original", *args, path)
        errors = [ln.strip() for ln in err.splitlines() if ln.strip().startswith("Error")]
        if errors or "weren't updated due to errors" in out:
            return "; ".join(errors) or out.strip()
        return None
