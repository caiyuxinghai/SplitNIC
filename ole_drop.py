# -*- coding: utf-8 -*-
"""Native Windows OLE IDropTarget.

Explorer talks to the HWND under the cursor, not to Tk's idea of the widget.
CustomTkinter children each have their own HWND, so tkdnd on the toplevel
never sees the drag and Windows shows the blocked cursor.

This registers a real IDropTarget on the toplevel and every child HWND,
always answers DROPEFFECT_COPY, and extracts CF_HDROP (desktop .lnk included).
"""
from __future__ import print_function

import ctypes
from ctypes import wintypes as wt

ole32 = ctypes.WinDLL("ole32")
shell32 = ctypes.WinDLL("shell32")
user32 = ctypes.WinDLL("user32")
kernel32 = ctypes.WinDLL("kernel32")

S_OK = 0
E_NOINTERFACE = 0x80004002
E_POINTER = 0x80004003
DRAGDROP_E_ALREADYREGISTERED = 0x80040101
DRAGDROP_E_INVALIDHWND = 0x80040102
DROPEFFECT_NONE = 0
DROPEFFECT_COPY = 1
CF_HDROP = 15
TYMED_HGLOBAL = 1
DVASPECT_CONTENT = 1
GA_ROOT = 2
WM_DROPFILES = 0x0233
WM_COPYDATA = 0x004A
WM_COPYGLOBALDATA = 0x0049
MSGFLT_ADD = 1
MSGFLT_ALLOW = 1

HRESULT = ctypes.HRESULT
WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wt.DWORD),
        ("Data2", wt.WORD),
        ("Data3", wt.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def _guid(d1, d2, d3, d4):
    g = GUID()
    g.Data1 = d1
    g.Data2 = d2
    g.Data3 = d3
    g.Data4 = (ctypes.c_ubyte * 8)(*d4)
    return g


IID_IUnknown = _guid(0x00000000, 0x0000, 0x0000, (0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46))
IID_IDropTarget = _guid(0x00000122, 0x0000, 0x0000, (0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46))


def _guid_eq(a, b):
    if not a:
        return False
    g = ctypes.cast(a, ctypes.POINTER(GUID)).contents
    return (
        g.Data1 == b.Data1 and g.Data2 == b.Data2 and g.Data3 == b.Data3
        and bytes(g.Data4) == bytes(b.Data4)
    )


class POINTL(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
    _pack_ = 4


class FORMATETC(ctypes.Structure):
    _fields_ = [
        ("cfFormat", wt.WORD),
        ("ptd", ctypes.c_void_p),
        ("dwAspect", wt.DWORD),
        ("lindex", ctypes.c_long),
        ("tymed", wt.DWORD),
    ]


class STGMEDIUM(ctypes.Structure):
    _fields_ = [
        ("tymed", wt.DWORD),
        ("hGlobal", ctypes.c_void_p),
        ("pUnkForRelease", ctypes.c_void_p),
    ]


class IDropTargetVtbl(ctypes.Structure):
    pass


class DropTargetObj(ctypes.Structure):
    _fields_ = [("lpVtbl", ctypes.POINTER(IDropTargetVtbl))]


IDropTargetVtbl._fields_ = [
    ("QueryInterface", ctypes.WINFUNCTYPE(
        HRESULT, ctypes.c_void_p, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p))),
    ("AddRef", ctypes.WINFUNCTYPE(wt.ULONG, ctypes.c_void_p)),
    ("Release", ctypes.WINFUNCTYPE(wt.ULONG, ctypes.c_void_p)),
    ("DragEnter", ctypes.WINFUNCTYPE(
        HRESULT, ctypes.c_void_p, ctypes.c_void_p, wt.DWORD, POINTL, ctypes.POINTER(wt.DWORD))),
    ("DragOver", ctypes.WINFUNCTYPE(
        HRESULT, ctypes.c_void_p, wt.DWORD, POINTL, ctypes.POINTER(wt.DWORD))),
    ("DragLeave", ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p)),
    ("Drop", ctypes.WINFUNCTYPE(
        HRESULT, ctypes.c_void_p, ctypes.c_void_p, wt.DWORD, POINTL, ctypes.POINTER(wt.DWORD))),
]

ole32.OleInitialize.argtypes = [ctypes.c_void_p]
ole32.OleInitialize.restype = HRESULT
ole32.RegisterDragDrop.argtypes = [wt.HWND, ctypes.c_void_p]
ole32.RegisterDragDrop.restype = HRESULT
ole32.RevokeDragDrop.argtypes = [wt.HWND]
ole32.RevokeDragDrop.restype = HRESULT
ole32.ReleaseStgMedium.argtypes = [ctypes.POINTER(STGMEDIUM)]
shell32.DragQueryFileW.argtypes = [wt.HANDLE, wt.UINT, wt.LPWSTR, wt.UINT]
shell32.DragQueryFileW.restype = wt.UINT
shell32.DragAcceptFiles.argtypes = [wt.HWND, wt.BOOL]
user32.GetAncestor.argtypes = [wt.HWND, wt.UINT]
user32.GetAncestor.restype = wt.HWND
user32.IsWindow.argtypes = [wt.HWND]
user32.IsWindow.restype = wt.BOOL
user32.EnumChildWindows.argtypes = [wt.HWND, WNDENUMPROC, wt.LPARAM]
user32.EnumChildWindows.restype = wt.BOOL
user32.ChangeWindowMessageFilter.argtypes = [wt.UINT, wt.DWORD]
user32.ChangeWindowMessageFilter.restype = wt.BOOL
try:
    user32.ChangeWindowMessageFilterEx.argtypes = [wt.HWND, wt.UINT, wt.DWORD, ctypes.c_void_p]
    user32.ChangeWindowMessageFilterEx.restype = wt.BOOL
except Exception:
    pass

_ole_ready = False
_by_this = {}


def _this_addr(this):
    if this is None:
        return 0
    if isinstance(this, int):
        return this
    return ctypes.cast(this, ctypes.c_void_p).value or 0


def _set_copy(pdwEffect):
    if pdwEffect:
        pdwEffect[0] = DROPEFFECT_COPY


def _QueryInterface(this, riid, ppv):
    if not ppv:
        return E_POINTER
    if _guid_eq(riid, IID_IUnknown) or _guid_eq(riid, IID_IDropTarget):
        ppv[0] = _this_addr(this)
        _AddRef(this)
        return S_OK
    ppv[0] = None
    return ctypes.c_long(E_NOINTERFACE).value


def _AddRef(this):
    obj = _by_this.get(_this_addr(this))
    if obj is None:
        return 1
    obj.ref += 1
    return obj.ref


def _Release(this):
    obj = _by_this.get(_this_addr(this))
    if obj is None:
        return 0
    obj.ref = max(0, obj.ref - 1)
    return obj.ref


def _schedule(obj, fn, *args):
    if obj is None or fn is None:
        return
    root = obj.root
    payload = args

    def go(cb=fn, a=payload):
        try:
            cb(*a)
        except Exception:
            pass

    try:
        root.after(0, go)
    except Exception:
        go()


def _DragEnter(this, pDataObj, grfKeyState, pt, pdwEffect):
    _set_copy(pdwEffect)
    obj = _by_this.get(_this_addr(this))
    _schedule(obj, obj.on_over if obj else None, int(pt.x), int(pt.y))
    return S_OK


def _DragOver(this, grfKeyState, pt, pdwEffect):
    _set_copy(pdwEffect)
    obj = _by_this.get(_this_addr(this))
    _schedule(obj, obj.on_over if obj else None, int(pt.x), int(pt.y))
    return S_OK


def _DragLeave(this):
    obj = _by_this.get(_this_addr(this))
    _schedule(obj, obj.on_leave if obj else None)
    return S_OK


def _Drop(this, pDataObj, grfKeyState, pt, pdwEffect):
    _set_copy(pdwEffect)
    files = extract_files(pDataObj)
    x, y = int(pt.x), int(pt.y)
    obj = _by_this.get(_this_addr(this))
    _schedule(obj, obj.on_drop if obj else None, files, x, y)
    return S_OK


_fn_qi = ctypes.WINFUNCTYPE(
    HRESULT, ctypes.c_void_p, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)
)(_QueryInterface)
_fn_addref = ctypes.WINFUNCTYPE(wt.ULONG, ctypes.c_void_p)(_AddRef)
_fn_release = ctypes.WINFUNCTYPE(wt.ULONG, ctypes.c_void_p)(_Release)
_fn_enter = ctypes.WINFUNCTYPE(
    HRESULT, ctypes.c_void_p, ctypes.c_void_p, wt.DWORD, POINTL, ctypes.POINTER(wt.DWORD)
)(_DragEnter)
_fn_over = ctypes.WINFUNCTYPE(
    HRESULT, ctypes.c_void_p, wt.DWORD, POINTL, ctypes.POINTER(wt.DWORD)
)(_DragOver)
_fn_leave = ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p)(_DragLeave)
_fn_drop = ctypes.WINFUNCTYPE(
    HRESULT, ctypes.c_void_p, ctypes.c_void_p, wt.DWORD, POINTL, ctypes.POINTER(wt.DWORD)
)(_Drop)
_VTBL = IDropTargetVtbl(_fn_qi, _fn_addref, _fn_release, _fn_enter, _fn_over, _fn_leave, _fn_drop)


def _idata_getdata(pDataObj, fmt, stg):
    vptr = ctypes.cast(pDataObj, ctypes.POINTER(ctypes.c_void_p))
    vtbl = ctypes.cast(vptr[0], ctypes.POINTER(ctypes.c_void_p))
    fn = ctypes.WINFUNCTYPE(
        HRESULT,
        ctypes.c_void_p,
        ctypes.POINTER(FORMATETC),
        ctypes.POINTER(STGMEDIUM),
    )(vtbl[3])
    return fn(pDataObj, ctypes.byref(fmt), ctypes.byref(stg))


def extract_files(pDataObj):
    out = []
    if not pDataObj:
        return out
    fmt = FORMATETC()
    fmt.cfFormat = CF_HDROP
    fmt.ptd = None
    fmt.dwAspect = DVASPECT_CONTENT
    fmt.lindex = -1
    fmt.tymed = TYMED_HGLOBAL
    stg = STGMEDIUM()
    hr = _idata_getdata(pDataObj, fmt, stg)
    if hr != S_OK or not stg.hGlobal:
        return out
    try:
        count = shell32.DragQueryFileW(stg.hGlobal, 0xFFFFFFFF, None, 0)
        buf = ctypes.create_unicode_buffer(1024)
        for i in range(int(count)):
            n = shell32.DragQueryFileW(stg.hGlobal, i, buf, 1024)
            if n:
                out.append(buf.value)
    finally:
        try:
            ole32.ReleaseStgMedium(ctypes.byref(stg))
        except Exception:
            pass
    return out


def allow_uipi(hwnd=None):
    """Let WM_DROPFILES / WM_COPYGLOBALDATA through UIPI when elevated."""
    for msg in (WM_DROPFILES, WM_COPYDATA, WM_COPYGLOBALDATA):
        try:
            user32.ChangeWindowMessageFilter(msg, MSGFLT_ADD)
        except Exception:
            pass
        if hwnd:
            try:
                user32.ChangeWindowMessageFilterEx(hwnd, msg, MSGFLT_ALLOW, None)
            except Exception:
                pass


def ole_init():
    global _ole_ready
    if _ole_ready:
        return True
    hr = int(ole32.OleInitialize(None) or 0)
    # S_OK or S_FALSE (already initialized)
    if hr not in (0, 1):
        return False
    _ole_ready = True
    allow_uipi()
    return True


def root_hwnd(widget):
    try:
        hwnd = int(widget.winfo_id())
    except Exception:
        return 0
    if not hwnd:
        return 0
    anc = user32.GetAncestor(hwnd, GA_ROOT)
    return int(anc or hwnd)


def enum_hwnds(hwnd):
    found = []
    if hwnd and user32.IsWindow(hwnd):
        found.append(int(hwnd))

    def _cb(child, lparam):
        found.append(int(child))
        return True

    cb = WNDENUMPROC(_cb)
    try:
        user32.EnumChildWindows(hwnd, cb, 0)
    except Exception:
        pass
    # keep callback alive for the duration of the call only
    return found, cb


class _Target(object):
    def __init__(self, root, on_drop, on_over, on_leave):
        self.ref = 1
        self.root = root
        self.on_drop = on_drop
        self.on_over = on_over
        self.on_leave = on_leave
        self.obj = DropTargetObj()
        self.obj.lpVtbl = ctypes.pointer(_VTBL)
        self.addr = ctypes.addressof(self.obj)
        _by_this[self.addr] = self

    def pointer(self):
        return ctypes.c_void_p(self.addr)


class OleDropSite(object):
    def __init__(self, root, on_drop, on_over=None, on_leave=None):
        self.root = root
        self.on_drop = on_drop
        self.on_over = on_over
        self.on_leave = on_leave
        self._targets = []
        self._hwnds = set()
        self._enum_cb = None
        self.last_error = ""

    def install(self):
        """Register IDropTarget on every HWND. Safe to call again after layout."""
        if not ole_init():
            self.last_error = "OleInitialize failed"
            return 0
        try:
            hwnd = root_hwnd(self.root)
        except Exception as exc:
            self.last_error = str(exc)
            return 0
        if not hwnd:
            self.last_error = "no hwnd"
            return 0
        hwnds, self._enum_cb = enum_hwnds(hwnd)
        for old in list(self._hwnds):
            if not user32.IsWindow(old):
                self._hwnds.discard(old)
        added = 0
        for h in hwnds:
            if h in self._hwnds:
                continue
            if not user32.IsWindow(h):
                continue
            allow_uipi(h)
            try:
                shell32.DragAcceptFiles(h, True)
            except Exception:
                pass
            target = _Target(self.root, self.on_drop, self.on_over, self.on_leave)
            hr = int(ole32.RegisterDragDrop(h, target.pointer()) or 0)
            if hr & 0xFFFFFFFF == DRAGDROP_E_ALREADYREGISTERED:
                ole32.RevokeDragDrop(h)
                hr = int(ole32.RegisterDragDrop(h, target.pointer()) or 0)
            if hr in (0, 1):
                self._targets.append(target)
                self._hwnds.add(h)
                added += 1
            else:
                self.last_error = "RegisterDragDrop hwnd=%s hr=0x%08X" % (h, hr & 0xFFFFFFFF)
        return added

    def registered_count(self):
        return len(self._hwnds)
