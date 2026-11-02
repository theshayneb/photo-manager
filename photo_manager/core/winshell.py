"""Small Windows shell helpers: "Open with…" and the Properties dialog."""

from __future__ import annotations

import os
import subprocess
import sys


def open_with(path: str) -> bool:
    """Show Windows' "Open with" chooser for path."""
    if sys.platform != "win32":
        return False
    subprocess.Popen(["rundll32.exe", "shell32.dll,OpenAs_RunDLL", os.path.normpath(path)])
    return True


def show_properties(path: str) -> bool:
    """Open Explorer's Properties dialog for path."""
    if sys.platform != "win32":
        return False
    import ctypes
    from ctypes import wintypes

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD), ("fMask", wintypes.ULONG), ("hwnd", wintypes.HWND),
            ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR),
            ("lpParameters", wintypes.LPCWSTR), ("lpDirectory", wintypes.LPCWSTR),
            ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE), ("lpIDList", ctypes.c_void_p),
            ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY), ("dwHotKey", wintypes.DWORD),
            ("hIconOrMonitor", wintypes.HANDLE), ("hProcess", wintypes.HANDLE),
        ]

    info = SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x0000000C  # SEE_MASK_INVOKEIDLIST
    info.lpVerb = "properties"
    info.lpFile = os.path.normpath(path)
    info.nShow = 5  # SW_SHOW
    shell32 = ctypes.WinDLL("shell32")
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(SHELLEXECUTEINFOW)]
    shell32.ShellExecuteExW.restype = wintypes.BOOL
    return bool(shell32.ShellExecuteExW(ctypes.byref(info)))
