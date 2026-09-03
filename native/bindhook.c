/*
 * SplitNIC BindHook.dll  (x64)
 *
 * Environment:
 *   SPLITNIC_BIND_IP    IPv4 dotted address
 *   SPLITNIC_IFINDEX    interface index
 *
 * tcc -shared -o BindHook.dll bindhook.c -lkernel32 -lntdll
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#ifndef NTAPI
#define NTAPI __stdcall
#endif
#ifndef WINAPI
#define WINAPI __stdcall
#endif

#define IPPROTO_IP      0
#define IPPROTO_IPV6    41
#define IP_UNICAST_IF   31
#define IPV6_UNICAST_IF 31
#define AF_INET         2
#define AF_INET6        23
#define HOOK_STEAL      12
#define FILE_APPEND_DATA 0x0004

typedef long NTSTATUS;

typedef struct _UNICODE_STRING {
    USHORT Length;
    USHORT MaximumLength;
    PWSTR  Buffer;
} UNICODE_STRING;

typedef unsigned long long sock_t;

typedef NTSTATUS (NTAPI *PFN_LdrLoadDll)(PWSTR, PULONG, UNICODE_STRING *, HANDLE *);
typedef int (WINAPI *PFN_connect)(sock_t, const void *, int);
typedef int (WINAPI *PFN_WSAConnect)(sock_t, const void *, int, void *, void *, void *, void *);
typedef int (WINAPI *PFN_sendto)(sock_t, const char *, int, int, const void *, int);
typedef int (WINAPI *PFN_WSASendTo)(sock_t, void *, DWORD, DWORD *, DWORD, const void *, int, void *, void *);
typedef sock_t (WINAPI *PFN_socket)(int, int, int);
typedef sock_t (WINAPI *PFN_WSASocketW)(int, int, int, void *, DWORD, DWORD);
typedef int (WINAPI *PFN_bind)(sock_t, const void *, int);
typedef int (WINAPI *PFN_setsockopt)(sock_t, int, int, const char *, int);

typedef struct {
    short          sin_family;
    unsigned short sin_port;
    unsigned long  sin_addr;
    char           sin_zero[8];
} sockaddr_in_min;

typedef struct {
    void *target;
    unsigned char stolen[HOOK_STEAL];
    unsigned char trampoline[32];
    int installed;
} hook_t;

static unsigned long g_bind_ip = 0;
static DWORD g_ifindex = 0;
static volatile LONG g_ws_hooked = 0;
static volatile LONG g_ready = 0;

static hook_t g_hk_ldr;
static hook_t g_hk_connect;
static hook_t g_hk_wsaconnect;
static hook_t g_hk_sendto;
static hook_t g_hk_wsasendto;
static hook_t g_hk_socket;
static hook_t g_hk_wsasocket;

static PFN_LdrLoadDll   orig_LdrLoadDll = 0;
static PFN_connect      orig_connect = 0;
static PFN_WSAConnect   orig_WSAConnect = 0;
static PFN_sendto       orig_sendto = 0;
static PFN_WSASendTo    orig_WSASendTo = 0;
static PFN_socket       orig_socket = 0;
static PFN_WSASocketW   orig_WSASocketW = 0;
static PFN_bind         real_bind = 0;
static PFN_setsockopt   real_setsockopt = 0;

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

static int wstr_has(const UNICODE_STRING *s, const WCHAR *needle)
{
    int nlen, slen, i, j;
    if (!s || !s->Buffer || !needle) return 0;
    slen = s->Length / (int)sizeof(WCHAR);
    nlen = 0;
    while (needle[nlen]) nlen++;
    if (nlen == 0 || slen < nlen) return 0;
    for (i = 0; i <= slen - nlen; i++) {
        for (j = 0; j < nlen; j++) {
            WCHAR a = s->Buffer[i + j];
            WCHAR b = needle[j];
            if (a >= (WCHAR)'A' && a <= (WCHAR)'Z') a = (WCHAR)(a - (WCHAR)'A' + (WCHAR)'a');
            if (b >= (WCHAR)'A' && b <= (WCHAR)'Z') b = (WCHAR)(b - (WCHAR)'A' + (WCHAR)'a');
            if (a != b) break;
        }
        if (j == nlen) return 1;
    }
    return 0;
}

static int install_inline(hook_t *hk, void *target, void *detour, void **orig_out)
{
    DWORD oldp;
    unsigned char *tr;
    unsigned char jmp[HOOK_STEAL];
    void *back;
    int i;

    if (!target || !detour) return 0;
    hk->target = target;
    tr = hk->trampoline;

    if (!VirtualProtect(target, HOOK_STEAL, PAGE_EXECUTE_READWRITE, &oldp))
        return 0;
    for (i = 0; i < HOOK_STEAL; i++)
        hk->stolen[i] = ((unsigned char *)target)[i];

    for (i = 0; i < HOOK_STEAL; i++)
        tr[i] = hk->stolen[i];
    tr[HOOK_STEAL + 0] = 0x48;
    tr[HOOK_STEAL + 1] = 0xB8;
    back = (unsigned char *)target + HOOK_STEAL;
    *(void **)(tr + HOOK_STEAL + 2) = back;
    tr[HOOK_STEAL + 10] = 0xFF;
    tr[HOOK_STEAL + 11] = 0xE0;

    VirtualProtect(tr, 32, PAGE_EXECUTE_READWRITE, &oldp);

    jmp[0] = 0x48;
    jmp[1] = 0xB8;
    *(void **)(jmp + 2) = detour;
    jmp[10] = 0xFF;
    jmp[11] = 0xE0;
    for (i = 0; i < HOOK_STEAL; i++)
        ((unsigned char *)target)[i] = jmp[i];

    VirtualProtect(target, HOOK_STEAL, oldp, &oldp);
    FlushInstructionCache(GetCurrentProcess(), target, HOOK_STEAL);
    FlushInstructionCache(GetCurrentProcess(), tr, 32);

    *orig_out = (void *)tr;
    hk->installed = 1;
    return 1;
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

static void install_ws_hooks(HMODULE ws)
{
    void *p;
    if (!ws) return;
    if (InterlockedCompareExchange(&g_ws_hooked, 1, 0) != 0) return;

    real_bind = (PFN_bind)GetProcAddress(ws, "bind");
    real_setsockopt = (PFN_setsockopt)GetProcAddress(ws, "setsockopt");

    p = GetProcAddress(ws, "connect");
    if (p) install_inline(&g_hk_connect, p, (void *)hook_connect, (void **)&orig_connect);

    p = GetProcAddress(ws, "WSAConnect");
    if (p) install_inline(&g_hk_wsaconnect, p, (void *)hook_WSAConnect, (void **)&orig_WSAConnect);

    p = GetProcAddress(ws, "sendto");
    if (p) install_inline(&g_hk_sendto, p, (void *)hook_sendto, (void **)&orig_sendto);

    p = GetProcAddress(ws, "WSASendTo");
    if (p) install_inline(&g_hk_wsasendto, p, (void *)hook_WSASendTo, (void **)&orig_WSASendTo);

    p = GetProcAddress(ws, "socket");
    if (p) install_inline(&g_hk_socket, p, (void *)hook_socket, (void **)&orig_socket);

    p = GetProcAddress(ws, "WSASocketW");
    if (p) install_inline(&g_hk_wsasocket, p, (void *)hook_WSASocketW, (void **)&orig_WSASocketW);

    log_line("ws2_32 hooks installed");
}

static NTSTATUS NTAPI hook_LdrLoadDll(PWSTR path, PULONG flags,
                                      UNICODE_STRING *name, HANDLE *handle)
{
    NTSTATUS st = orig_LdrLoadDll(path, flags, name, handle);
    if (st >= 0 && handle && *handle && name) {
        if (wstr_has(name, L"ws2_32") || wstr_has(name, L"wsock32"))
            install_ws_hooks((HMODULE)(*handle));
    }
    return st;
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

BOOL WINAPI DllMain(HINSTANCE h, DWORD reason, LPVOID reserved)
{
    HMODULE ntdll;
    HMODULE ws;
    void *ldr;
    (void)reserved;
    if (reason != DLL_PROCESS_ATTACH) return TRUE;
    DisableThreadLibraryCalls(h);
    init_config();
    if (!g_ready) return TRUE;

    ntdll = GetModuleHandleA("ntdll.dll");
    if (ntdll) {
        ldr = GetProcAddress(ntdll, "LdrLoadDll");
        if (ldr)
            install_inline(&g_hk_ldr, ldr, (void *)hook_LdrLoadDll, (void **)&orig_LdrLoadDll);
    }

    ws = GetModuleHandleA("ws2_32.dll");
    if (!ws) ws = GetModuleHandleA("wsock32.dll");
    if (ws) install_ws_hooks(ws);

    return TRUE;
}
