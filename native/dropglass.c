/*
 * SplitNIC DropGlass.dll
 * Native IDropTarget so Explorer can drop desktop .lnk files onto the GUI.
 *
 * A nearly-invisible layered child covers the window (so the HWND under the
 * cursor is always ours) and mouse clicks are forwarded to the Tk widgets
 * underneath. RegisterDragDrop is also applied to every existing child.
 *
 * tcc -shared -o DropGlass.dll dropglass.c -lkernel32 -luser32 -lshell32 -lgdi32
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shellapi.h>
#include <string.h>

#ifndef DROPEFFECT_NONE
#define DROPEFFECT_NONE 0
#define DROPEFFECT_COPY 1
#define DROPEFFECT_MOVE 2
#define DROPEFFECT_LINK 4
#endif
#ifndef CF_HDROP
#define CF_HDROP 15
#endif
#ifndef DVASPECT_CONTENT
#define DVASPECT_CONTENT 1
#endif
#ifndef TYMED_HGLOBAL
#define TYMED_HGLOBAL 1
#endif
#ifndef DRAGDROP_E_ALREADYREGISTERED
#define DRAGDROP_E_ALREADYREGISTERED ((HRESULT)0x80040101L)
#endif
#ifndef E_NOINTERFACE
#define E_NOINTERFACE ((HRESULT)0x80004002L)
#endif
#ifndef E_POINTER
#define E_POINTER ((HRESULT)0x80004003L)
#endif
#ifndef MOVEFILE_REPLACE_EXISTING
#define MOVEFILE_REPLACE_EXISTING 0x00000001
#endif

typedef struct _GUIDX {
    DWORD Data1;
    WORD Data2;
    WORD Data3;
    BYTE Data4[8];
} GUIDX;

static const GUIDX IID_IUnknown_ = {0x00000000, 0x0000, 0x0000, {0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46}};
static const GUIDX IID_IDropTarget_ = {0x00000122, 0x0000, 0x0000, {0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46}};

/* POINTL is in windef.h */

typedef struct _FORMATETC_ {
    WORD cfFormat;
    WORD pad;
    DWORD pad2;
    void *ptd;
    DWORD dwAspect;
    LONG lindex;
    DWORD tymed;
} FORMATETC_;

/* Force 8-byte packing like MSVC ole headers on x64 */
#pragma pack(push, 8)
typedef struct _FORMATETC8 {
    WORD cfFormat;
    BYTE pad[6];
    void *ptd;
    DWORD dwAspect;
    LONG lindex;
    DWORD tymed;
} FORMATETC8;

typedef struct _STGMEDIUM8 {
    DWORD tymed;
    void *hGlobal;
    void *pUnkForRelease;
} STGMEDIUM8;
#pragma pack(pop)

typedef HRESULT(__stdcall *PFN_QI)(void *, const GUIDX *, void **);
typedef ULONG(__stdcall *PFN_ADDREF)(void *);
typedef ULONG(__stdcall *PFN_RELEASE)(void *);
typedef HRESULT(__stdcall *PFN_DRAGENTER)(void *, void *, DWORD, POINTL, DWORD *);
typedef HRESULT(__stdcall *PFN_DRAGOVER)(void *, DWORD, POINTL, DWORD *);
typedef HRESULT(__stdcall *PFN_DRAGLEAVE)(void *);
typedef HRESULT(__stdcall *PFN_DROP)(void *, void *, DWORD, POINTL, DWORD *);

typedef struct _IDropTargetVtbl {
    PFN_QI QueryInterface;
    PFN_ADDREF AddRef;
    PFN_RELEASE Release;
    PFN_DRAGENTER DragEnter;
    PFN_DRAGOVER DragOver;
    PFN_DRAGLEAVE DragLeave;
    PFN_DROP Drop;
} IDropTargetVtbl;

typedef struct _DropTarget {
    IDropTargetVtbl *lpVtbl;
    LONG ref;
} DropTarget;

typedef HRESULT(__stdcall *PFN_OleInitialize)(void *);
typedef HRESULT(__stdcall *PFN_RegisterDragDrop)(HWND, void *);
typedef HRESULT(__stdcall *PFN_RevokeDragDrop)(HWND);
typedef void(__stdcall *PFN_ReleaseStgMedium)(STGMEDIUM8 *);

typedef void(__stdcall *DropCb)(const wchar_t *files, int x, int y, int kind);

static PFN_OleInitialize pOleInitialize;
static PFN_RegisterDragDrop pRegisterDragDrop;
static PFN_RevokeDragDrop pRevokeDragDrop;
static PFN_ReleaseStgMedium pReleaseStgMedium;
static IDropTargetVtbl g_vtbl;
static DropCb g_cb;
static HWND g_parent;
static HWND g_glass;
static UINT g_timer;
static int g_ole_ok;
static wchar_t g_last_files[32768];
static DWORD g_last_over_tick;
static HWND g_registered[512];
static int g_nreg;

static int already_registered(HWND hwnd)
{
    int i;
    for (i = 0; i < g_nreg; i++) {
        if (g_registered[i] == hwnd)
            return 1;
        if (g_registered[i] && !IsWindow(g_registered[i]))
            g_registered[i] = 0;
    }
    return 0;
}

static void remember_hwnd(HWND hwnd)
{
    int i;
    for (i = 0; i < g_nreg; i++) {
        if (!g_registered[i]) {
            g_registered[i] = hwnd;
            return;
        }
    }
    if (g_nreg < 512)
        g_registered[g_nreg++] = hwnd;
}

static int guid_eq(const GUIDX *a, const GUIDX *b)
{
    if (!a || !b)
        return 0;
    return memcmp(a, b, 16) == 0;
}

static void dlog(const char *msg)
{
    wchar_t path[MAX_PATH];
    HANDLE h;
    DWORD n, written;
    char line[512];
    SYSTEMTIME st;
    GetTempPathW(MAX_PATH, path);
    lstrcatW(path, L"splitnic-drop.log");
    GetLocalTime(&st);
    wsprintfA(line, "%02d:%02d:%02d %s\r\n", st.wHour, st.wMinute, st.wSecond, msg);
    h = CreateFileW(path, FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE, 0, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, 0);
    if (h == INVALID_HANDLE_VALUE)
        return;
    n = (DWORD)lstrlenA(line);
    WriteFile(h, line, n, &written, 0);
    CloseHandle(h);
}

static int load_ole(void)
{
    HMODULE h;
    if (g_ole_ok)
        return 1;
    h = LoadLibraryW(L"ole32.dll");
    if (!h)
        return 0;
    pOleInitialize = (PFN_OleInitialize)GetProcAddress(h, "OleInitialize");
    pRegisterDragDrop = (PFN_RegisterDragDrop)GetProcAddress(h, "RegisterDragDrop");
    pRevokeDragDrop = (PFN_RevokeDragDrop)GetProcAddress(h, "RevokeDragDrop");
    pReleaseStgMedium = (PFN_ReleaseStgMedium)GetProcAddress(h, "ReleaseStgMedium");
    if (!pOleInitialize || !pRegisterDragDrop || !pRevokeDragDrop || !pReleaseStgMedium)
        return 0;
    if (FAILED(pOleInitialize(0)) && 0) /* S_FALSE is success */
        ;
    g_ole_ok = 1;
    return 1;
}

static DWORD pick_effect(DWORD allowed)
{
    if (allowed & DROPEFFECT_COPY)
        return DROPEFFECT_COPY;
    if (allowed & DROPEFFECT_LINK)
        return DROPEFFECT_LINK;
    if (allowed & DROPEFFECT_MOVE)
        return DROPEFFECT_MOVE;
    return DROPEFFECT_COPY;
}

static HRESULT extract_hdrop(void *pDataObj, wchar_t *out, int out_cch)
{
    void **vptr;
    void **vtbl;
    HRESULT(__stdcall * GetData)(void *, FORMATETC8 *, STGMEDIUM8 *);
    FORMATETC8 fmt;
    STGMEDIUM8 stg;
    HRESULT hr;
    UINT count, i, used;
    wchar_t buf[1024];

    out[0] = 0;
    if (!pDataObj)
        return E_POINTER;
    vptr = (void **)pDataObj;
    vtbl = (void **)*vptr;
    GetData = (HRESULT(__stdcall *)(void *, FORMATETC8 *, STGMEDIUM8 *))vtbl[3];
    ZeroMemory(&fmt, sizeof(fmt));
    fmt.cfFormat = CF_HDROP;
    fmt.ptd = 0;
    fmt.dwAspect = DVASPECT_CONTENT;
    fmt.lindex = -1;
    fmt.tymed = TYMED_HGLOBAL;
    ZeroMemory(&stg, sizeof(stg));
    hr = GetData(pDataObj, &fmt, &stg);
    if (FAILED(hr) || !stg.hGlobal)
        return hr;
    count = DragQueryFileW((HDROP)stg.hGlobal, 0xFFFFFFFF, 0, 0);
    used = 0;
    for (i = 0; i < count; i++) {
        UINT n = DragQueryFileW((HDROP)stg.hGlobal, i, buf, 1024);
        if (!n)
            continue;
        if (used && used + 1 < (UINT)out_cch)
            out[used++] = L'\n';
        if (used + n >= (UINT)out_cch)
            break;
        lstrcpynW(out + used, buf, out_cch - used);
        used += n;
    }
    if (pReleaseStgMedium)
        pReleaseStgMedium(&stg);
    return S_OK;
}

static ULONG __stdcall DT_AddRef(void *this);
static ULONG __stdcall DT_Release(void *this);

static HRESULT __stdcall DT_QI(void *this, const GUIDX *riid, void **ppv)
{
    char msg[96];
    DWORD id = riid ? riid->Data1 : 0;
    wsprintfA(msg, "QI iid=%08X", (unsigned)id);
    dlog(msg);
    if (!ppv)
        return E_POINTER;
    if (guid_eq(riid, &IID_IUnknown_) || guid_eq(riid, &IID_IDropTarget_) || id == 0x00000122 || id == 0) {
        *ppv = this;
        DT_AddRef(this);
        return S_OK;
    }
    *ppv = 0;
    return E_NOINTERFACE;
}

static ULONG __stdcall DT_AddRef(void *this)
{
    DropTarget *t = (DropTarget *)this;
    return (ULONG)InterlockedIncrement(&t->ref);
}

static ULONG __stdcall DT_Release(void *this)
{
    DropTarget *t = (DropTarget *)this;
    LONG n = InterlockedDecrement(&t->ref);
    return (ULONG)(n < 0 ? 0 : n);
}

static void write_inbox(const wchar_t *kind, int x, int y, const wchar_t *files)
{
    wchar_t dir[MAX_PATH], path[MAX_PATH], tmp[MAX_PATH];
    HANDLE h;
    DWORD written;
    wchar_t header[128];
    if (!GetEnvironmentVariableW(L"APPDATA", dir, MAX_PATH))
        return;
    lstrcatW(dir, L"\\SplitNIC");
    CreateDirectoryW(dir, 0);
    lstrcpyW(path, dir);
    lstrcatW(path, L"\\drop-inbox.txt");
    lstrcpyW(tmp, dir);
    lstrcatW(tmp, L"\\drop-inbox.tmp");
    h = CreateFileW(tmp, GENERIC_WRITE, 0, 0, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, 0);
    if (h == INVALID_HANDLE_VALUE)
        return;
    wsprintfW(header, L"%s\n%d\n%d\n", kind, x, y);
    WriteFile(h, header, (DWORD)(lstrlenW(header) * sizeof(wchar_t)), &written, 0);
    if (files && files[0])
        WriteFile(h, files, (DWORD)(lstrlenW(files) * sizeof(wchar_t)), &written, 0);
    CloseHandle(h);
    MoveFileExW(tmp, path, MOVEFILE_REPLACE_EXISTING);
}

static HRESULT __stdcall DT_DragEnter(void *this, void *pDataObj, DWORD keys, POINTL pt, DWORD *effect)
{
    (void)this;
    (void)keys;
    (void)pDataObj;
    if (effect)
        *effect = pick_effect(*effect ? *effect : 0xFFFFFFFF);
    dlog("DragEnter");
    write_inbox(L"OVER", (int)pt.x, (int)pt.y, L"");
    return S_OK;
}

static HRESULT __stdcall DT_DragOver(void *this, DWORD keys, POINTL pt, DWORD *effect)
{
    (void)this;
    (void)keys;
    if (effect)
        *effect = pick_effect(*effect ? *effect : 0xFFFFFFFF);
    {
        DWORD now = GetTickCount();
        if (now - g_last_over_tick > 40) {
            g_last_over_tick = now;
            write_inbox(L"OVER", (int)pt.x, (int)pt.y, L"");
        }
    }
    return S_OK;
}

static HRESULT __stdcall DT_DragLeave(void *this)
{
    (void)this;
    dlog("DragLeave");
    write_inbox(L"LEAVE", 0, 0, L"");
    return S_OK;
}

static HRESULT __stdcall DT_Drop(void *this, void *pDataObj, DWORD keys, POINTL pt, DWORD *effect)
{
    (void)this;
    (void)keys;
    extract_hdrop(pDataObj, g_last_files, 32768);
    if (effect)
        *effect = pick_effect(*effect ? *effect : 0xFFFFFFFF);
    dlog("Drop");
    write_inbox(L"DROP", (int)pt.x, (int)pt.y, g_last_files);
    return S_OK;
}

static DropTarget *make_target(void)
{
    DropTarget *t = (DropTarget *)HeapAlloc(GetProcessHeap(), HEAP_ZERO_MEMORY, sizeof(DropTarget));
    if (!t)
        return 0;
    t->lpVtbl = &g_vtbl;
    t->ref = 1;
    return t;
}

static int register_hwnd(HWND hwnd)
{
    DropTarget *t;
    HRESULT hr;
    char msg[128];
    if (!hwnd || !IsWindow(hwnd) || !pRegisterDragDrop)
        return 0;
    if (already_registered(hwnd))
        return 0;
    t = make_target();
    if (!t)
        return 0;
    hr = pRegisterDragDrop(hwnd, t);
    if (hr == DRAGDROP_E_ALREADYREGISTERED) {
        pRevokeDragDrop(hwnd);
        hr = pRegisterDragDrop(hwnd, t);
    }
    wsprintfA(msg, "Register hwnd=%p hr=0x%08X", hwnd, (unsigned)hr);
    dlog(msg);
    if (hr < 0) {
        HeapFree(GetProcessHeap(), 0, t);
        return 0;
    }
    remember_hwnd(hwnd);
    return 1;
}

static BOOL CALLBACK enum_cb(HWND hwnd, LPARAM lp)
{
    int *n = (int *)lp;
    if (register_hwnd(hwnd))
        (*n)++;
    return TRUE;
}

static HWND hit_under_glass(HWND glass, POINT screen)
{
    HWND parent = GetParent(glass);
    HWND h, hit = parent;
    HWND inner;
    POINT cl;
    h = GetTopWindow(parent);
    while (h) {
        if (h != glass && IsWindowVisible(h)) {
            RECT r;
            GetWindowRect(h, &r);
            if (PtInRect(&r, screen)) {
                hit = h;
                break;
            }
        }
        h = GetWindow(h, GW_HWNDNEXT);
    }
    for (;;) {
        cl = screen;
        ScreenToClient(hit, &cl);
        inner = ChildWindowFromPointEx(hit, cl, CWP_SKIPINVISIBLE | CWP_SKIPDISABLED);
        if (!inner || inner == hit)
            break;
        hit = inner;
    }
    return hit;
}

static LRESULT forward_mouse(HWND glass, UINT msg, WPARAM wParam, LPARAM lParam)
{
    POINT client, screen;
    HWND hit;
    client.x = (short)LOWORD(lParam);
    client.y = (short)HIWORD(lParam);
    screen = client;
    ClientToScreen(glass, &screen);
    hit = hit_under_glass(glass, screen);
    if (hit && hit != glass) {
        POINT c = screen;
        ScreenToClient(hit, &c);
        return SendMessageW(hit, msg, wParam, MAKELPARAM((short)c.x, (short)c.y));
    }
    return 0;
}

static LRESULT CALLBACK glass_proc(HWND hwnd, UINT msg, WPARAM wParam, LPARAM lParam)
{
    switch (msg) {
    case WM_NCHITTEST:
        return HTCLIENT;
    case WM_ERASEBKGND:
        return 1;
    case WM_PAINT: {
        PAINTSTRUCT ps;
        BeginPaint(hwnd, &ps);
        EndPaint(hwnd, &ps);
        return 0;
    }
    case WM_LBUTTONDOWN:
    case WM_LBUTTONUP:
    case WM_LBUTTONDBLCLK:
    case WM_RBUTTONDOWN:
    case WM_RBUTTONUP:
    case WM_RBUTTONDBLCLK:
    case WM_MBUTTONDOWN:
    case WM_MBUTTONUP:
    case WM_MOUSEMOVE:
    case WM_MOUSEWHEEL:
        return forward_mouse(hwnd, msg, wParam, lParam);
    case WM_SETCURSOR: {
        POINT p;
        HWND hit;
        GetCursorPos(&p);
        hit = hit_under_glass(hwnd, p);
        if (hit && hit != hwnd)
            return SendMessageW(hit, msg, wParam, lParam);
        break;
    }
    case WM_TIMER:
        if (g_parent && IsWindow(g_parent) && g_glass) {
            RECT rc;
            GetClientRect(g_parent, &rc);
            MoveWindow(g_glass, 0, 0, rc.right - rc.left, rc.bottom - rc.top, TRUE);
            SetWindowPos(g_glass, HWND_TOP, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE);
        }
        return 0;
    }
    return DefWindowProcW(hwnd, msg, wParam, lParam);
}

static ATOM register_class(void)
{
    WNDCLASSEXW wc;
    static ATOM atom;
    if (atom)
        return atom;
    ZeroMemory(&wc, sizeof(wc));
    wc.cbSize = sizeof(wc);
    wc.lpfnWndProc = glass_proc;
    wc.hInstance = GetModuleHandleW(0);
    wc.lpszClassName = L"SplitNICDropGlass";
    wc.hCursor = LoadCursor(0, IDC_ARROW);
    wc.hbrBackground = (HBRUSH)GetStockObject(NULL_BRUSH);
    atom = RegisterClassExW(&wc);
    return atom;
}

static HWND create_glass(HWND parent)
{
    RECT rc;
    HWND glass;
    if (!register_class())
        return 0;
    GetClientRect(parent, &rc);
    glass = CreateWindowExW(
        WS_EX_LAYERED,
        L"SplitNICDropGlass",
        L"",
        WS_CHILD | WS_VISIBLE,
        0, 0, rc.right - rc.left, rc.bottom - rc.top,
        parent, 0, GetModuleHandleW(0), 0);
    if (!glass)
        return 0;
    {
        typedef BOOL(WINAPI *PFN_SLWA)(HWND, COLORREF, BYTE, DWORD);
        PFN_SLWA slwa = (PFN_SLWA)GetProcAddress(GetModuleHandleW(L"user32.dll"), "SetLayeredWindowAttributes");
        if (slwa)
            slwa(glass, 0, 12, LWA_ALPHA);
    }
    SetWindowPos(glass, HWND_TOP, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE);
    return glass;
}

__declspec(dllexport) int __stdcall SplitNIC_DropInstall(HWND parent, DropCb cb)
{
    int n = 0;
    char msg[128];
    g_cb = cb;
    g_parent = parent;
    if (!parent || !IsWindow(parent))
        return 0;
    if (!load_ole()) {
        dlog("OleInitialize/load failed");
        return 0;
    }
    g_vtbl.QueryInterface = DT_QI;
    g_vtbl.AddRef = DT_AddRef;
    g_vtbl.Release = DT_Release;
    g_vtbl.DragEnter = DT_DragEnter;
    g_vtbl.DragOver = DT_DragOver;
    g_vtbl.DragLeave = DT_DragLeave;
    g_vtbl.Drop = DT_Drop;

    if (register_hwnd(parent))
        n++;
    EnumChildWindows(parent, enum_cb, (LPARAM)&n);

    if (!g_glass || !IsWindow(g_glass)) {
        g_glass = create_glass(parent);
        if (g_glass && register_hwnd(g_glass))
            n++;
        if (g_glass)
            g_timer = SetTimer(g_glass, 1, 250, 0);
    }
    wsprintfA(msg, "Install parent=%p glass=%p registered=%d", parent, g_glass, n);
    dlog(msg);
    return n;
}

__declspec(dllexport) int __stdcall SplitNIC_DropRefresh(void)
{
    int n = 0;
    if (!g_parent || !IsWindow(g_parent))
        return 0;
    if (register_hwnd(g_parent))
        n++;
    EnumChildWindows(g_parent, enum_cb, (LPARAM)&n);
    if (g_glass && IsWindow(g_glass)) {
        RECT rc;
        GetClientRect(g_parent, &rc);
        MoveWindow(g_glass, 0, 0, rc.right - rc.left, rc.bottom - rc.top, TRUE);
        SetWindowPos(g_glass, HWND_TOP, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE);
        if (register_hwnd(g_glass))
            n++;
    }
    return n;
}
