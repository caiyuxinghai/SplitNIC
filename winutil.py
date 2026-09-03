# -*- coding: utf-8 -*-
"""Windows helpers: single-instance, desktop shortcuts, autostart."""
from __future__ import print_function

import os
import sys
import ctypes
from ctypes import wintypes as wt

kernel32 = ctypes.windll.kernel32
user32 = ctypes.windll.user32
shell32 = ctypes.windll.shell32

ERROR_ALREADY_EXISTS = 183
CSIDL_DESKTOPDIRECTORY = 0x10
CSIDL_STARTUP = 0x07
CSIDL_PROGRAMS = 0x02
SW_RESTORE = 9
WINDOW_TITLE = "网口分流  SplitNIC"
MUTEX_NAME = "Local\\SplitNIC.SingleInstance.v2"

_mutex_handle = None


def is_frozen():
    return bool(getattr(sys, "frozen", False))


def app_dir():
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def pythonw_path():
    exe = os.path.abspath(sys.executable)
    if exe.lower().endswith("python.exe"):
        cand = exe[:-10] + "pythonw.exe"
        if os.path.isfile(cand):
            return cand
    return exe


def launch_target():
    """Return (target, arguments, workdir, icon) for a shortcut."""
    workdir = app_dir()
    icon = os.path.join(workdir, "assets", "icon.ico")
    if not os.path.isfile(icon):
        icon = ""
    if is_frozen():
        return sys.executable, "", workdir, icon
    script = os.path.join(workdir, "app.py")
    return pythonw_path(), '"%s"' % script, workdir, icon


def sh_folder(csidl):
    buf = ctypes.create_unicode_buffer(260)
    # SHGetFolderPathW(hwnd, csidl, token, flags, pszPath)
    hr = shell32.SHGetFolderPathW(None, int(csidl), None, 0, buf)
    if hr != 0:
        return ""
    return buf.value


def desktop_dirs():
    found = []
    seen = set()
    candidates = [
        sh_folder(CSIDL_DESKTOPDIRECTORY),
        os.path.join(os.path.expanduser("~"), "Desktop"),
        os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop"),
        os.environ.get("USERPROFILE", "") and os.path.join(os.environ["USERPROFILE"], "Desktop"),
        os.environ.get("USERPROFILE", "") and os.path.join(os.environ["USERPROFILE"], "OneDrive", "Desktop"),
    ]
    for p in candidates:
        if not p:
            continue
        ap = os.path.abspath(p)
        if ap in seen:
            continue
        seen.add(ap)
        if os.path.isdir(ap):
            found.append(ap)
    return found


def _write_lnk(lnk_path, target, args, workdir, icon, description):
    import subprocess
    # Escape for PowerShell single-quoted strings: ' -> ''
    def q(s):
        return (s or "").replace("'", "''")

    ps = (
        "$s = New-Object -ComObject WScript.Shell; "
        "$l = $s.CreateShortcut('%s'); "
        "$l.TargetPath = '%s'; "
        "$l.Arguments = '%s'; "
        "$l.WorkingDirectory = '%s'; "
        "$l.WindowStyle = 1; "
        "$l.Description = '%s'; "
        % (q(lnk_path), q(target), q(args), q(workdir), q(description))
    )
    if icon:
        ps += "$l.IconLocation = '%s'; " % q(icon)
    ps += "$l.Save();"
    subprocess.check_call(
        ["powershell", "-NoProfile", "-STA", "-Command", ps],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def set_lnk_run_as_admin(lnk_path):
    """Set the 'Run as administrator' flag on a .lnk (byte 0x15 bit 0x20)."""
    with open(lnk_path, "rb") as f:
        data = bytearray(f.read())
    if len(data) <= 0x15:
        return
    data[0x15] = data[0x15] | 0x20
    with open(lnk_path, "wb") as f:
        f.write(data)


def create_shortcut(lnk_path, run_as_admin=True):
    target, args, workdir, icon = launch_target()
    folder = os.path.dirname(lnk_path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder, exist_ok=True)
    _write_lnk(lnk_path, target, args, workdir, icon, "网口分流 SplitNIC — 按软件选择网卡")
    if run_as_admin:
        try:
            set_lnk_run_as_admin(lnk_path)
        except Exception:
            pass
    return lnk_path


def create_desktop_shortcuts(run_as_admin=True):
    created = []
    for desk in desktop_dirs():
        path = os.path.join(desk, "网口分流.lnk")
        create_shortcut(path, run_as_admin=run_as_admin)
        created.append(path)
    return created


def startup_lnk_path():
    folder = sh_folder(CSIDL_STARTUP)
    if not folder:
        folder = os.path.join(
            os.environ.get("APPDATA", ""),
            r"Microsoft\Windows\Start Menu\Programs\Startup",
        )
    return os.path.join(folder, "网口分流.lnk")


def set_start_with_windows(enabled):
    path = startup_lnk_path()
    if enabled:
        create_shortcut(path, run_as_admin=True)
        return path
    if os.path.isfile(path):
        os.remove(path)
    return None


def is_start_with_windows():
    return os.path.isfile(startup_lnk_path())


def bring_existing_to_front():
    hwnd = user32.FindWindowW(None, WINDOW_TITLE)
    if not hwnd:
        return False
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetForegroundWindow(hwnd)
    return True


def ensure_single_instance():
    """Return True if this is the first instance. Otherwise focus the other and return False."""
    global _mutex_handle
    kernel32.CreateMutexW.restype = wt.HANDLE
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.LPCWSTR]
    _mutex_handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        bring_existing_to_front()
        return False
    return True
