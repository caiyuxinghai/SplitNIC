# -*- coding: utf-8 -*-
"""Native Windows WM_DROPFILES hook so desktop icons can be dropped on CTk."""
from __future__ import print_function

import os
import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32
shell32 = ctypes.windll.shell32
kernel32 = ctypes.windll.kernel32

WM_DROPFILES = 0x0233
GWLP_WNDPROC = -4
GMEM_MOVEABLE = 0x0002

LRESULT = ctypes.c_int64
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]
shell32.DragQueryFileW.argtypes = [wintypes.HANDLE, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]
shell32.DragQueryFileW.restype = wintypes.UINT
shell32.DragQueryPoint.argtypes = [wintypes.HANDLE, ctypes.POINTER(POINT)]
shell32.DragFinish.argtypes = [wintypes.HANDLE]
user32.CallWindowProcW.restype = LRESULT
user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.SetWindowLongPtrW.restype = ctypes.c_void_p
user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(POINT)]


def resolve_lnk(path):
    """Turn a .lnk into its target path. Leaves other files unchanged."""
    if not path:
        return ""
    path = os.path.abspath(path)
    if not path.lower().endswith(".lnk"):
        return path
    try:
        import win32com.client
        target = win32com.client.Dispatch("WScript.Shell").CreateShortcut(path).TargetPath
        if target:
            return target
    except Exception:
        pass
    try:
        import subprocess
        ps = (
            "$s = New-Object -ComObject WScript.Shell; "
            "$l = $s.CreateShortcut('%s'); "
            "$t = $l.TargetPath; "
            "if (-not $t) { $t = $l.FullName }; "
            "Write-Output $t" % path.replace("'", "''")
        )
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-STA", "-Command", ps],
            stderr=subprocess.DEVNULL,
        )
        target = out.decode("utf-8", "ignore").strip()
        if target:
            return target
    except Exception:
        pass
    return path


def files_from_drop(paths):
    """Accept .exe and desktop .lnk that point to .exe."""
    out = []
    for raw in paths:
        p = resolve_lnk(raw)
        if p and os.path.isfile(p) and p.lower().endswith(".exe"):
            out.append(p)
    return out


class FileDropHook(object):
    def __init__(self, hwnd, callback):
        self.hwnd = int(hwnd)
        self.callback = callback
        self._old_ptr = None
        self._cb = WNDPROC(self._wndproc)
        shell32.DragAcceptFiles(self.hwnd, True)
        self._old_ptr = user32.SetWindowLongPtrW(
            self.hwnd, GWLP_WNDPROC, ctypes.cast(self._cb, ctypes.c_void_p).value
        )

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_DROPFILES:
            try:
                self._handle_drop(wparam)
            except Exception:
                pass
            return 0
        if self._old_ptr:
            return user32.CallWindowProcW(self._old_ptr, hwnd, msg, wparam, lparam)
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _handle_drop(self, hdrop):
        count = shell32.DragQueryFileW(hdrop, 0xFFFFFFFF, None, 0)
        paths = []
        buf = ctypes.create_unicode_buffer(1024)
        for i in range(count):
            n = shell32.DragQueryFileW(hdrop, i, buf, 1024)
            if n:
                paths.append(buf.value)
        pt = POINT()
        shell32.DragQueryPoint(hdrop, ctypes.byref(pt))
        shell32.DragFinish(hdrop)
        screen = POINT(pt.x, pt.y)
        user32.ClientToScreen(self.hwnd, ctypes.byref(screen))
        exes = files_from_drop(paths)
        self.callback(exes, screen.x, screen.y, paths)


def _root_hwnd(tk_widget):
    hwnd = int(tk_widget.winfo_id())
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    root = user32.GetAncestor(hwnd, 2)  # GA_ROOT
    return int(root or hwnd)


def install_drop(tk_widget, callback):
    """Enable desktop-icon drop on a Tk/CTk window. Keep the return value alive."""
    tk_widget.update_idletasks()
    hwnd = _root_hwnd(tk_widget)
    return FileDropHook(hwnd, callback)
