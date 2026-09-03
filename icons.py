# -*- coding: utf-8 -*-
"""Extract Windows file icons to PIL images."""
from __future__ import print_function

import os
import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
shell32 = ctypes.windll.shell32

SHGFI_ICON = 0x00000100
SHGFI_LARGEICON = 0x00000000
DI_NORMAL = 0x0003
DIB_RGB_COLORS = 0

_cache = {}


class SHFILEINFOW(ctypes.Structure):
    _fields_ = [
        ("hIcon", wintypes.HICON),
        ("iIcon", ctypes.c_int),
        ("dwAttributes", wintypes.DWORD),
        ("szDisplayName", wintypes.WCHAR * 260),
        ("szTypeName", wintypes.WCHAR * 80),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


def _hicon_to_pil(hicon, size=48):
    from PIL import Image

    hdc = user32.GetDC(0)
    hdc_mem = gdi32.CreateCompatibleDC(hdc)
    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = size
    bmi.bmiHeader.biHeight = -size
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = 0
    bits = ctypes.c_void_p()
    hbmp = gdi32.CreateDIBSection(hdc_mem, ctypes.byref(bmi), DIB_RGB_COLORS, ctypes.byref(bits), None, 0)
    old = gdi32.SelectObject(hdc_mem, hbmp)
    user32.DrawIconEx(hdc_mem, 0, 0, hicon, size, size, 0, None, DI_NORMAL)
    buflen = size * size * 4
    raw = ctypes.string_at(bits, buflen)
    gdi32.SelectObject(hdc_mem, old)
    gdi32.DeleteObject(hbmp)
    gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(0, hdc)
    img = Image.frombytes("RGBA", (size, size), raw, "raw", "BGRA")
    return img


def exe_icon(path, size=48):
    """Return a PIL RGBA image for a file's Windows icon, or None."""
    key = (os.path.normcase(os.path.abspath(path or "")), size)
    if key in _cache:
        return _cache[key]
    if not path or not os.path.isfile(path):
        _cache[key] = None
        return None
    info = SHFILEINFOW()
    shell32.SHGetFileInfoW.restype = ctypes.c_void_p
    flags = SHGFI_ICON | SHGFI_LARGEICON
    ok = shell32.SHGetFileInfoW(path, 0, ctypes.byref(info), ctypes.sizeof(info), flags)
    if not ok or not info.hIcon:
        _cache[key] = None
        return None
    try:
        img = _hicon_to_pil(info.hIcon, size=size)
    except Exception:
        img = None
    user32.DestroyIcon(info.hIcon)
    _cache[key] = img
    return img


def placeholder_icon(size=48, color=(91, 140, 255)):
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = max(4, size // 8)
    d.rounded_rectangle((pad, pad, size - pad, size - pad), radius=size // 6, fill=color + (230,))
    return img
