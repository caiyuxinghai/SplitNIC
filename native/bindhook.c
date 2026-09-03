/*
 * SplitNIC BindHook.dll (x64)
 *
 * IAT / delay-IAT / GetProcAddress hooks only — no instruction stealing.
 * Environment: SPLITNIC_BIND_IP, SPLITNIC_IFINDEX
 *
 * tcc -shared -o BindHook.dll bindhook.c -lkernel32
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#ifndef WINAPI
#define WINAPI __stdcall
#endif

#define IPPROTO_IP      0
#define IPPROTO_IPV6    41
#define IP_UNICAST_IF   31
#define IPV6_UNICAST_IF 31
#define AF_INET         2
#ifndef FILE_APPEND_DATA
#define FILE_APPEND_DATA 0x0004
#endif
#define TH32CS_SNAPMODULE   0x00000008
#define TH32CS_SNAPMODULE32 0x00000010
#define IMAGE_DIRECTORY_ENTRY_IMPORT 1
#define IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT 13
#ifndef IMAGE_ORDINAL_FLAG64
#define IMAGE_ORDINAL_FLAG64 0x8000000000000000ULL
#endif

typedef unsigned long long sock_t;
typedef unsigned long long ull_t;

typedef int (WINAPI *PFN_connect)(sock_t, const void *, int);
typedef int (WINAPI *PFN_WSAConnect)(sock_t, const void *, int, void *, void *, void *, void *);
typedef int (WINAPI *PFN_sendto)(sock_t, const char *, int, int, const void *, int);
typedef int (WINAPI *PFN_WSASendTo)(sock_t, void *, DWORD, DWORD *, DWORD, const void *, int, void *, void *);
typedef sock_t (WINAPI *PFN_socket)(int, int, int);
typedef sock_t (WINAPI *PFN_WSASocketW)(int, int, int, void *, DWORD, DWORD);
typedef int (WINAPI *PFN_bind)(sock_t, const void *, int);
typedef int (WINAPI *PFN_setsockopt)(sock_t, int, int, const char *, int);
typedef HMODULE (WINAPI *PFN_LLW)(LPCWSTR);
typedef HMODULE (WINAPI *PFN_LLEXW)(LPCWSTR, HANDLE, DWORD);
typedef FARPROC (WINAPI *PFN_GPA)(HMODULE, LPCSTR);

typedef struct {
    DWORD dwSize;
    DWORD th32ModuleID;
    DWORD th32ProcessID;
    DWORD GlblcntUsage;
    DWORD ProccntUsage;
    BYTE *modBaseAddr;
    DWORD modBaseSize;
    HMODULE hModule;
    WCHAR szModule[256];
    WCHAR szExePath[260];
} MODULEENTRY32W_MIN;

typedef HANDLE (WINAPI *PFN_CreateToolhelp32Snapshot)(DWORD, DWORD);
typedef BOOL (WINAPI *PFN_Module32FirstW)(HANDLE, MODULEENTRY32W_MIN *);
typedef BOOL (WINAPI *PFN_Module32NextW)(HANDLE, MODULEENTRY32W_MIN *);

typedef struct {
    short          sin_family;
    unsigned short sin_port;
    unsigned long  sin_addr;
    char           sin_zero[8];
} sockaddr_in_min;

static unsigned long g_bind_ip = 0;
static DWORD g_ifindex = 0;
static volatile LONG g_ready = 0;

static PFN_connect      orig_connect = 0;
static PFN_WSAConnect   orig_WSAConnect = 0;
static PFN_sendto       orig_sendto = 0;
static PFN_WSASendTo    orig_WSASendTo = 0;
static PFN_socket       orig_socket = 0;
static PFN_WSASocketW   orig_WSASocketW = 0;
static PFN_bind         real_bind = 0;
static PFN_setsockopt   real_setsockopt = 0;
static PFN_LLW          orig_LLW = 0;
static PFN_LLEXW        orig_LLEXW = 0;
static PFN_GPA          orig_GPA = 0;

static PFN_CreateToolhelp32Snapshot p_CreateSnap = 0;
static PFN_Module32FirstW p_ModFirst = 0;
static PFN_Module32NextW p_ModNext = 0;

static DWORD my_htonl(DWORD x)
{
    return ((x & 0xFF) << 24) | ((x & 0xFF00) << 8) |
           ((x & 0xFF0000) >> 8) | ((x >> 24) & 0xFF);
}

static void memzero(void *p, SIZE_T n)
{
    unsigned char *b = (unsigned char *)p;
    SIZE_T i;
    for (i = 0; i < n; i++) b[i] = 0;
}

static void log_line(const char *msg)
{
    char path[MAX_PATH];
    HANDLE h;
    DWORD w;
    DWORD n = GetTempPathA(MAX_PATH, path);
    if (n == 0 || n > MAX_PATH - 32) return;
    lstrcatA(path, "splitnic-bindhook.log");
    h = CreateFileA(path, FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE,
                    0, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, 0);
    if (h == INVALID_HANDLE_VALUE) return;
    WriteFile(h, msg, (DWORD)lstrlenA(msg), &w, 0);
    WriteFile(h, "\r\n", 2, &w, 0);
    CloseHandle(h);
}

static int name_is(LPCSTR a, const char *b)
{
    if (!a || (ull_t)a < 0x10000ULL) return 0;
    return lstrcmpA(a, b) == 0;
}

static int wname_has(LPCWSTR s, const WCHAR *needle)
{
    int nlen, slen, i, j;
    if (!s || !needle) return 0;
    slen = 0;
    while (s[slen]) slen++;
    nlen = 0;
    while (needle[nlen]) nlen++;
    if (nlen == 0 || slen < nlen) return 0;
    for (i = 0; i <= slen - nlen; i++) {
        for (j = 0; j < nlen; j++) {
            WCHAR a = s[i + j];
            WCHAR b = needle[j];
            if (a >= (WCHAR)'A' && a <= (WCHAR)'Z') a = (WCHAR)(a - (WCHAR)'A' + (WCHAR)'a');
            if (b >= (WCHAR)'A' && b <= (WCHAR)'Z') b = (WCHAR)(b - (WCHAR)'A' + (WCHAR)'a');
            if (a != b) break;
        }
        if (j == nlen) return 1;
    }
    return 0;
}

static void apply_iface(sock_t s)
{
    DWORD nbo;
    sockaddr_in_min local;
    if (!g_ready || !s || s == (sock_t)~0ULL) return;
    if (!real_setsockopt || !real_bind) return;
    nbo = my_htonl(g_ifindex);
    real_setsockopt(s, IPPROTO_IP, IP_UNICAST_IF, (const char *)&nbo, sizeof(nbo));
    real_setsockopt(s, IPPROTO_IPV6, IPV6_UNICAST_IF, (const char *)&g_ifindex, sizeof(g_ifindex));
    if (g_bind_ip != 0) {
        memzero(&local, sizeof(local));
        local.sin_family = AF_INET;
        local.sin_port = 0;
        local.sin_addr = g_bind_ip;
        real_bind(s, &local, sizeof(local));
    }
}

static int WINAPI hook_connect(sock_t s, const void *name, int namelen)
{
    apply_iface(s);
    return orig_connect(s, name, namelen);
}

static int WINAPI hook_WSAConnect(sock_t s, const void *name, int namelen,
                                  void *c, void *d, void *e, void *f)
{
    apply_iface(s);
    return orig_WSAConnect(s, name, namelen, c, d, e, f);
}

static int WINAPI hook_sendto(sock_t s, const char *buf, int len, int flags,
                              const void *to, int tolen)
{
    apply_iface(s);
    return orig_sendto(s, buf, len, flags, to, tolen);
}

static int WINAPI hook_WSASendTo(sock_t s, void *buf, DWORD count, DWORD *sent,
                                 DWORD flags, const void *to, int tolen,
                                 void *ov, void *cr)
{
    apply_iface(s);
    return orig_WSASendTo(s, buf, count, sent, flags, to, tolen, ov, cr);
}

static sock_t WINAPI hook_socket(int af, int type, int proto)
{
    sock_t s = orig_socket(af, type, proto);
    apply_iface(s);
    return s;
}

static sock_t WINAPI hook_WSASocketW(int af, int type, int proto, void *info,
                                     DWORD group, DWORD flags)
{
    sock_t s = orig_WSASocketW(af, type, proto, info, group, flags);
    apply_iface(s);
    return s;
}

static void *hook_for_ws_name(const char *name, void *real)
{
    if (name_is(name, "connect")) {
        if (!orig_connect) orig_connect = (PFN_connect)real;
        return (void *)hook_connect;
    }
    if (name_is(name, "WSAConnect")) {
        if (!orig_WSAConnect) orig_WSAConnect = (PFN_WSAConnect)real;
        return (void *)hook_WSAConnect;
    }
    if (name_is(name, "sendto")) {
        if (!orig_sendto) orig_sendto = (PFN_sendto)real;
        return (void *)hook_sendto;
    }
    if (name_is(name, "WSASendTo")) {
        if (!orig_WSASendTo) orig_WSASendTo = (PFN_WSASendTo)real;
        return (void *)hook_WSASendTo;
    }
    if (name_is(name, "socket")) {
        if (!orig_socket) orig_socket = (PFN_socket)real;
        return (void *)hook_socket;
    }
    if (name_is(name, "WSASocketW")) {
        if (!orig_WSASocketW) orig_WSASocketW = (PFN_WSASocketW)real;
        return (void *)hook_WSASocketW;
    }
    return 0;
}

static int dll_is_ws2(const char *n)
{
    if (!n) return 0;
    return lstrcmpiA(n, "ws2_32.dll") == 0 || lstrcmpiA(n, "wsock32.dll") == 0;
}

static int dll_is_k32(const char *n)
{
    if (!n) return 0;
    return lstrcmpiA(n, "kernel32.dll") == 0 || lstrcmpiA(n, "api-ms-win-core-libraryloader-l1-2-0.dll") == 0
        || lstrcmpiA(n, "api-ms-win-core-libraryloader-l1-1-0.dll") == 0
        || lstrcmpiA(n, "api-ms-win-core-libraryloader-l1-2-1.dll") == 0;
}

static int patch_slot(ull_t *slot, void *hook)
{
    DWORD oldp;
    if (!slot || !hook) return 0;
    if (*slot == (ull_t)hook) return 0;
    if (!VirtualProtect(slot, sizeof(ull_t), PAGE_EXECUTE_READWRITE, &oldp))
        return 0;
    *slot = (ull_t)hook;
    VirtualProtect(slot, sizeof(ull_t), oldp, &oldp);
    return 1;
}

static void patch_thunks(BYTE *base, DWORD oft_rva, DWORD ft_rva, int is_ws, int is_k32)
{
    ull_t *oft;
    ull_t *ft;
    if (!ft_rva) return;
    ft = (ull_t *)(base + ft_rva);
    oft = oft_rva ? (ull_t *)(base + oft_rva) : ft;
    for (; *ft; ft++, oft++) {
        const char *fname;
        void *hook = 0;
        if (*oft & IMAGE_ORDINAL_FLAG64) continue;
        fname = (const char *)(base + (DWORD)(*oft) + 2); /* skip Hint */
        if (is_ws) {
            hook = hook_for_ws_name(fname, (void *)(*ft));
        } else if (is_k32) {
            if (name_is(fname, "GetProcAddress")) {
                if (!orig_GPA) orig_GPA = (PFN_GPA)(*ft);
                hook = 0; /* set below after orig saved — need pointer to hook_GPA */
            } else if (name_is(fname, "LoadLibraryW")) {
                if (!orig_LLW) orig_LLW = (PFN_LLW)(*ft);
            } else if (name_is(fname, "LoadLibraryExW")) {
                if (!orig_LLEXW) orig_LLEXW = (PFN_LLEXW)(*ft);
            }
        }
        if (hook) patch_slot(ft, hook);
    }
}

/* forward */
static FARPROC WINAPI hook_GPA(HMODULE m, LPCSTR name);
static HMODULE WINAPI hook_LLW(LPCWSTR n);
static HMODULE WINAPI hook_LLEXW(LPCWSTR n, HANDLE f, DWORD flags);
static void patch_module(HMODULE mod);
static void patch_all_modules(void);

static void patch_thunks_k32(BYTE *base, DWORD oft_rva, DWORD ft_rva)
{
    ull_t *oft;
    ull_t *ft;
    if (!ft_rva) return;
    ft = (ull_t *)(base + ft_rva);
    oft = oft_rva ? (ull_t *)(base + oft_rva) : ft;
    for (; *ft; ft++, oft++) {
        const char *fname;
        void *hook = 0;
        if (*oft & IMAGE_ORDINAL_FLAG64) continue;
        fname = (const char *)(base + (DWORD)(*oft) + 2);
        if (name_is(fname, "GetProcAddress")) {
            if (!orig_GPA) orig_GPA = (PFN_GPA)(*ft);
            hook = (void *)hook_GPA;
        } else if (name_is(fname, "LoadLibraryW")) {
            if (!orig_LLW) orig_LLW = (PFN_LLW)(*ft);
            hook = (void *)hook_LLW;
        } else if (name_is(fname, "LoadLibraryExW")) {
            if (!orig_LLEXW) orig_LLEXW = (PFN_LLEXW)(*ft);
            hook = (void *)hook_LLEXW;
        }
        if (hook) patch_slot(ft, hook);
    }
}

static void patch_import_desc(BYTE *base, BYTE *imp, int delay)
{
    /* IMAGE_IMPORT_DESCRIPTOR: OFT 0, Name 12, FT 16
       DELAY: Attributes 0, Name 4, ModuleHandle 8, pIAT 12, pINT 16 */
    DWORD name_rva, oft, ft;
    const char *dll;
    int ws, k32;
    if (delay) {
        name_rva = *(DWORD *)(imp + 4);
        ft = *(DWORD *)(imp + 12);
        oft = *(DWORD *)(imp + 16);
    } else {
        oft = *(DWORD *)(imp + 0);
        name_rva = *(DWORD *)(imp + 12);
        ft = *(DWORD *)(imp + 16);
    }
    if (!name_rva) return;
    dll = (const char *)(base + name_rva);
    ws = dll_is_ws2(dll);
    k32 = dll_is_k32(dll);
    if (ws) patch_thunks(base, oft, ft, 1, 0);
    if (k32) patch_thunks_k32(base, oft, ft);
}

static void patch_module(HMODULE mod)
{
    BYTE *base = (BYTE *)mod;
    BYTE *nt;
    WORD magic;
    DWORD imp_rva, delay_rva;
    BYTE *desc;
    if (!base || *(WORD *)base != 0x5A4D) return;
    nt = base + *(DWORD *)(base + 0x3C);
    if (*(DWORD *)nt != 0x00004550) return;
    magic = *(WORD *)(nt + 24);
    if (magic != 0x20B) return; /* PE32+ only */
    imp_rva = *(DWORD *)(nt + 24 + 112 + 8 * IMAGE_DIRECTORY_ENTRY_IMPORT);
    delay_rva = *(DWORD *)(nt + 24 + 112 + 8 * IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT);
    if (imp_rva) {
        for (desc = base + imp_rva; *(DWORD *)(desc + 12) || *(DWORD *)(desc + 16); desc += 20)
            patch_import_desc(base, desc, 0);
    }
    if (delay_rva) {
        for (desc = base + delay_rva; *(DWORD *)(desc + 4); desc += 32)
            patch_import_desc(base, desc, 1);
    }
}

static void patch_all_modules(void)
{
    HANDLE snap;
    MODULEENTRY32W_MIN me;
    if (!p_CreateSnap || !p_ModFirst || !p_ModNext) return;
    snap = p_CreateSnap(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, GetCurrentProcessId());
    if (snap == INVALID_HANDLE_VALUE) return;
    memzero(&me, sizeof(me));
    me.dwSize = sizeof(me);
    if (p_ModFirst(snap, &me)) {
        do {
            patch_module(me.hModule);
        } while (p_ModNext(snap, &me));
    }
    CloseHandle(snap);
}

static void resolve_ws(HMODULE ws)
{
    if (!ws) return;
    if (!real_bind) real_bind = (PFN_bind)GetProcAddress(ws, "bind");
    if (!real_setsockopt) real_setsockopt = (PFN_setsockopt)GetProcAddress(ws, "setsockopt");
    if (!orig_connect) orig_connect = (PFN_connect)GetProcAddress(ws, "connect");
    if (!orig_WSAConnect) orig_WSAConnect = (PFN_WSAConnect)GetProcAddress(ws, "WSAConnect");
    if (!orig_sendto) orig_sendto = (PFN_sendto)GetProcAddress(ws, "sendto");
    if (!orig_WSASendTo) orig_WSASendTo = (PFN_WSASendTo)GetProcAddress(ws, "WSASendTo");
    if (!orig_socket) orig_socket = (PFN_socket)GetProcAddress(ws, "socket");
    if (!orig_WSASocketW) orig_WSASocketW = (PFN_WSASocketW)GetProcAddress(ws, "WSASocketW");
}

static FARPROC WINAPI hook_GPA(HMODULE m, LPCSTR name)
{
    FARPROC p;
    void *h;
    if (!orig_GPA) return 0;
    p = orig_GPA(m, name);
    if (!p) return p;
    h = hook_for_ws_name(name, (void *)p);
    if (h) return (FARPROC)h;
    return p;
}

static HMODULE WINAPI hook_LLW(LPCWSTR n)
{
    HMODULE m;
    if (!orig_LLW) return 0;
    m = orig_LLW(n);
    if (m && n && (wname_has(n, L"ws2_32") || wname_has(n, L"wsock32"))) {
        resolve_ws(m);
        patch_all_modules();
    }
    return m;
}

static HMODULE WINAPI hook_LLEXW(LPCWSTR n, HANDLE f, DWORD flags)
{
    HMODULE m;
    if (!orig_LLEXW) return 0;
    m = orig_LLEXW(n, f, flags);
    if (m && n && (wname_has(n, L"ws2_32") || wname_has(n, L"wsock32"))) {
        resolve_ws(m);
        patch_all_modules();
    }
    return m;
}

static unsigned long parse_ipv4_manual(const char *s)
{
    unsigned int parts[4];
    int idx = 0;
    unsigned int cur = 0;
    const char *p;
    if (!s) return 0;
    parts[0] = parts[1] = parts[2] = parts[3] = 0;
    for (p = s; ; p++) {
        if (*p >= '0' && *p <= '9') {
            cur = cur * 10 + (unsigned int)(*p - '0');
            if (cur > 255) return 0;
        } else if (*p == '.' || *p == 0) {
            if (idx >= 4) return 0;
            parts[idx++] = cur;
            cur = 0;
            if (*p == 0) break;
        } else {
            return 0;
        }
    }
    if (idx != 4) return 0;
    return (parts[0]) | (parts[1] << 8) | (parts[2] << 16) | (parts[3] << 24);
}

static DWORD parse_dword(const char *s)
{
    DWORD v = 0;
    if (!s) return 0;
    while (*s >= '0' && *s <= '9') {
        v = v * 10 + (DWORD)(*s - '0');
        s++;
    }
    return v;
}

static void init_config(void)
{
    char ip[64];
    char idx[32];
    DWORD n;
    ip[0] = 0;
    idx[0] = 0;
    n = GetEnvironmentVariableA("SPLITNIC_BIND_IP", ip, sizeof(ip));
    if (n == 0 || n >= sizeof(ip)) {
        log_line("SPLITNIC_BIND_IP missing");
        return;
    }
    n = GetEnvironmentVariableA("SPLITNIC_IFINDEX", idx, sizeof(idx));
    if (n == 0 || n >= sizeof(idx)) {
        log_line("SPLITNIC_IFINDEX missing");
        return;
    }
    g_bind_ip = parse_ipv4_manual(ip);
    g_ifindex = parse_dword(idx);
    if (g_bind_ip == 0 || g_ifindex == 0) {
        log_line("invalid bind ip or ifindex");
        return;
    }
    g_ready = 1;
    log_line("bindhook config ok");
}

static DWORD WINAPI hook_thread(LPVOID unused)
{
    int i;
    HMODULE ws;
    (void)unused;
    Sleep(10);
    for (i = 0; i < 400; i++) {
        ws = GetModuleHandleA("ws2_32.dll");
        if (!ws) ws = GetModuleHandleA("wsock32.dll");
        if (ws) {
            resolve_ws(ws);
            patch_all_modules();
            log_line("iat hooks installed");
            break;
        }
        patch_all_modules();
        Sleep(25);
    }
    for (;;) {
        Sleep(1500);
        patch_all_modules();
    }
    return 0;
}

BOOL WINAPI DllMain(HINSTANCE h, DWORD reason, LPVOID reserved)
{
    HMODULE k32;
    (void)reserved;
    if (reason != DLL_PROCESS_ATTACH) return TRUE;
    DisableThreadLibraryCalls(h);
    init_config();
    if (!g_ready) return TRUE;

    k32 = GetModuleHandleA("kernel32.dll");
    if (k32) {
        p_CreateSnap = (PFN_CreateToolhelp32Snapshot)GetProcAddress(k32, "CreateToolhelp32Snapshot");
        p_ModFirst = (PFN_Module32FirstW)GetProcAddress(k32, "Module32FirstW");
        p_ModNext = (PFN_Module32NextW)GetProcAddress(k32, "Module32NextW");
        if (!orig_GPA) orig_GPA = (PFN_GPA)GetProcAddress(k32, "GetProcAddress");
        if (!orig_LLW) orig_LLW = (PFN_LLW)GetProcAddress(k32, "LoadLibraryW");
        if (!orig_LLEXW) orig_LLEXW = (PFN_LLEXW)GetProcAddress(k32, "LoadLibraryExW");
    }
    patch_all_modules();
    CreateThread(0, 0, hook_thread, 0, 0, 0);
    return TRUE;
}
