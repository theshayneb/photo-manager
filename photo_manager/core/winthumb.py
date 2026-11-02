"""Windows Explorer thumbnails (IShellItemImageFactory) via ctypes.

Gives video thumbnails on Windows 11 without ffmpeg, using whatever codecs
Windows itself has. Returns None on other platforms or when Windows has no
thumbnail for the file.
"""

from __future__ import annotations

import sys
import uuid

from PIL import Image

if sys.platform == "win32":
    import ctypes
    from ctypes import POINTER, byref, c_void_p, wintypes

    class _GUID(ctypes.Structure):
        _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                    ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]

    class _SIZE(ctypes.Structure):
        _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]

    class _BITMAP(ctypes.Structure):
        _fields_ = [("bmType", ctypes.c_long), ("bmWidth", ctypes.c_long), ("bmHeight", ctypes.c_long),
                    ("bmWidthBytes", ctypes.c_long), ("bmPlanes", wintypes.WORD),
                    ("bmBitsPixel", wintypes.WORD), ("bmBits", c_void_p)]

    class _BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD),
                    ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD),
                    ("biXPelsPerMeter", ctypes.c_long), ("biYPelsPerMeter", ctypes.c_long),
                    ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]

    _ole32 = ctypes.WinDLL("ole32")
    _shell32 = ctypes.WinDLL("shell32")
    _gdi32 = ctypes.WinDLL("gdi32")
    _user32 = ctypes.WinDLL("user32")

    _ole32.CoInitializeEx.argtypes = [c_void_p, wintypes.DWORD]
    _ole32.CoInitializeEx.restype = ctypes.c_long
    _ole32.CoUninitialize.argtypes = []
    _ole32.CoUninitialize.restype = None
    _shell32.SHCreateItemFromParsingName.argtypes = [wintypes.LPCWSTR, c_void_p, POINTER(_GUID), POINTER(c_void_p)]
    _shell32.SHCreateItemFromParsingName.restype = ctypes.c_long
    _gdi32.GetObjectW.argtypes = [wintypes.HANDLE, ctypes.c_int, c_void_p]
    _gdi32.GetObjectW.restype = ctypes.c_int
    _gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, c_void_p,
                                 POINTER(_BITMAPINFOHEADER), wintypes.UINT]
    _gdi32.GetDIBits.restype = ctypes.c_int
    _gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
    _user32.GetDC.argtypes = [wintypes.HWND]
    _user32.GetDC.restype = wintypes.HDC
    _user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]

    _IID_FACTORY = _GUID.from_buffer_copy(uuid.UUID("bcc18b79-ba16-442f-80c4-8a59c30c463b").bytes_le)
    _SIIGBF_BIGGERSIZEOK = 0x1
    _SIIGBF_THUMBNAILONLY = 0x8
    _GetImage = ctypes.WINFUNCTYPE(ctypes.c_long, c_void_p, _SIZE, ctypes.c_int, POINTER(wintypes.HBITMAP))
    _Release = ctypes.WINFUNCTYPE(ctypes.c_ulong, c_void_p)

    _RPC_E_CHANGED_MODE = -2147417850  # 0x80010106: thread already uses another COM mode

    def _hbitmap_to_image(hbmp: wintypes.HBITMAP) -> Image.Image | None:
        bm = _BITMAP()
        if not _gdi32.GetObjectW(hbmp, ctypes.sizeof(bm), byref(bm)):
            return None
        width, height = bm.bmWidth, abs(bm.bmHeight)
        if width <= 0 or height <= 0:
            return None
        header = _BITMAPINFOHEADER()
        header.biSize = ctypes.sizeof(header)
        header.biWidth = width
        header.biHeight = -height  # top-down rows
        header.biPlanes = 1
        header.biBitCount = 32
        buf = ctypes.create_string_buffer(width * height * 4)
        hdc = _user32.GetDC(None)
        try:
            lines = _gdi32.GetDIBits(hdc, hbmp, 0, height, buf, byref(header), 0)
        finally:
            _user32.ReleaseDC(None, hdc)
        if lines != height:
            return None
        im = Image.frombuffer("RGBA", (width, height), buf.raw, "raw", "BGRA", 0, 1)
        if im.getchannel("A").getextrema() == (0, 0):  # no alpha information
            im = im.convert("RGB")
        return im.copy()

    def shell_thumbnail(path: str, size: int) -> Image.Image | None:
        # COM is switched on and off around every call. Leaving it on in worker threads
        # made Windows' thumbnail components crash when the process exited.
        hr = _ole32.CoInitializeEx(None, 0x2)  # apartment threaded
        try:
            return _shell_thumbnail(path, size)
        finally:
            if hr != _RPC_E_CHANGED_MODE:  # S_OK or S_FALSE must be balanced
                _ole32.CoUninitialize()

    def _shell_thumbnail(path: str, size: int) -> Image.Image | None:
        factory = c_void_p()
        hr = _shell32.SHCreateItemFromParsingName(path, None, byref(_IID_FACTORY), byref(factory))
        if hr < 0 or not factory.value:
            return None
        vtable = ctypes.cast(factory, POINTER(POINTER(c_void_p)))[0]
        hbmp = wintypes.HBITMAP()
        try:
            hr = _GetImage(vtable[3])(factory, _SIZE(size, size),
                                      _SIIGBF_BIGGERSIZEOK | _SIIGBF_THUMBNAILONLY, byref(hbmp))
        finally:
            _Release(vtable[2])(factory)
        if hr < 0 or not hbmp.value:
            return None
        try:
            im = _hbitmap_to_image(hbmp)
        finally:
            _gdi32.DeleteObject(hbmp)
        if im is not None:
            im.thumbnail((size, size), Image.Resampling.LANCZOS)
        return im

else:

    def shell_thumbnail(path: str, size: int) -> Image.Image | None:  # noqa: ARG001
        return None
