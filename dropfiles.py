# -*- coding: utf-8 -*-
"""Resolve dropped files (.lnk / .exe) without flashing extra windows."""
from __future__ import print_function

import os
import re
import struct
import subprocess

CREATE_NO_WINDOW = 0x08000000


def run_hidden(args, timeout=8):
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0
    return subprocess.check_output(
        args,
        stderr=subprocess.DEVNULL,
        timeout=timeout,
        startupinfo=si,
        creationflags=CREATE_NO_WINDOW,
    )


def _parse_lnk_binary(path):
    try:
        with open(path, "rb") as f:
            data = f.read()
    except Exception:
        return ""
    if len(data) < 0x4C or data[:4] != b"L\x00\x00\x00":
        return ""
    flags = struct.unpack_from("<I", data, 0x14)[0]
    pos = 0x4C
    try:
        if flags & 0x01:
            idlist_size = struct.unpack_from("<H", data, pos)[0]
            pos += 2 + idlist_size
        if flags & 0x02 and pos + 20 <= len(data):
            local_off = struct.unpack_from("<I", data, pos + 16)[0]
            header_size = struct.unpack_from("<I", data, pos + 4)[0]
            uni_off = 0
            if header_size >= 36 and pos + 32 <= len(data):
                uni_off = struct.unpack_from("<I", data, pos + 28)[0]
            if uni_off and pos + uni_off + 2 <= len(data):
                start = pos + uni_off
                end = data.find(b"\x00\x00", start)
                if end > start:
                    return data[start:end + 1].decode("utf-16le", "ignore").rstrip("\x00")
            if local_off and pos + local_off < len(data):
                start = pos + local_off
                end = data.find(b"\x00", start)
                if end > start:
                    return data[start:end].decode("mbcs", "ignore")
    except Exception:
        pass
    ascii_pat = re.compile(rb"[A-Za-z]:\\(?:[^\\\x00:*?\"<>|]+\\)*[^\\\x00:*?\"<>|]+\.[eE][xX][eE]")
    m = ascii_pat.search(data)
    if m:
        return m.group().decode("mbcs", "ignore")
    uni_pat = re.compile(
        "(?:[A-Za-z]:\\\\(?:[^\\\\/:*?\"<>|\\x00]+\\\\)*[^\\\\/:*?\"<>|\\x00]+\\.[eE][xX][eE])".encode("utf-16le")
    )
    m = uni_pat.search(data)
    if m:
        return m.group().decode("utf-16le", "ignore")
    return ""


def resolve_lnk(path):
    if not path:
        return ""
    path = os.path.abspath(path)
    if not path.lower().endswith(".lnk"):
        return path
    target = _parse_lnk_binary(path)
    if target and os.path.isfile(target):
        return target
    try:
        raw = run_hidden([
            "powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command",
            "$s=New-Object -ComObject WScript.Shell; $s.CreateShortcut('%s').TargetPath" % path.replace("'", "''"),
        ], timeout=6)
        target = raw.decode("utf-8", "ignore").strip()
        if target:
            return target
    except Exception:
        pass
    return path


def files_from_drop(paths):
    out = []
    seen = set()
    for raw in paths or []:
        p = (raw or "").strip().strip("{}")
        if not p:
            continue
        p = resolve_lnk(p)
        if not p or not os.path.isfile(p):
            continue
        if not p.lower().endswith(".exe"):
            continue
        key = os.path.normcase(os.path.abspath(p))
        if key in seen:
            continue
        seen.add(key)
        out.append(os.path.abspath(p))
    return out


def bind_drop(widget, handler):
    """Register Windows file drop on a Tk/CTk widget if tkdnd is loaded."""
    try:
        from tkinterdnd2 import DND_FILES
    except Exception:
        return False
    ok = False
    candidates = [widget]
    for attr in ("_canvas", "canvas", "_textbox"):
        inner = getattr(widget, attr, None)
        if inner is not None:
            candidates.append(inner)
    for w in candidates:
        try:
            w.drop_target_register(DND_FILES)
            w.dnd_bind("<<Drop>>", handler)
            ok = True
        except Exception:
            try:
                w.tk.call("tkdnd::drop_target", "register", w._w, DND_FILES)
                w.bind("<<Drop>>", handler)
                ok = True
            except Exception:
                continue
    return ok
