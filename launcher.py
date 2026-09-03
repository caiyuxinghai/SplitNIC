# -*- coding: utf-8 -*-
"""Launch a Windows process bound to a chosen network adapter."""
from __future__ import print_function

import os
import sys
import time
import ctypes
import ctypes.wintypes as wintypes
from ctypes import wintypes as wt

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)

CREATE_SUSPENDED = 0x00000004
CREATE_UNICODE_ENVIRONMENT = 0x00000400
CREATE_NEW_CONSOLE = 0x00000010
INFINITE = 0xFFFFFFFF
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
PAGE_READWRITE = 0x04
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
STILL_ACTIVE = 259

BROWSER_NAMES = {
    "chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe",
    "opera_gx.exe", "vivaldi.exe", "chromium.exe", "iexplore.exe",
    "qqbrowser.exe", "360chrome.exe", "360se.exe", "sogouexplorer.exe",
    "liebao.exe", "maxthon.exe", "safari.exe",
}

# Chromium / Electron apps that honor --proxy-server
CHROMIUM_LIKE = BROWSER_NAMES | {
    "douyin.exe", "抖音.exe", "tiktok.exe", "douyinlauncher.exe",
    "wechatbrowser.exe", "quark.exe", "ucbrowser.exe",
}


class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("nLength", wt.DWORD),
        ("lpSecurityDescriptor", ctypes.c_void_p),
        ("bInheritHandle", wt.BOOL),
    ]


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wt.DWORD),
        ("lpReserved", wt.LPWSTR),
        ("lpDesktop", wt.LPWSTR),
        ("lpTitle", wt.LPWSTR),
        ("dwX", wt.DWORD),
        ("dwY", wt.DWORD),
        ("dwXSize", wt.DWORD),
        ("dwYSize", wt.DWORD),
        ("dwXCountChars", wt.DWORD),
        ("dwYCountChars", wt.DWORD),
        ("dwFillAttribute", wt.DWORD),
        ("dwFlags", wt.DWORD),
        ("wShowWindow", wt.WORD),
        ("cbReserved2", wt.WORD),
        ("lpReserved2", ctypes.c_void_p),
        ("hStdInput", wt.HANDLE),
        ("hStdOutput", wt.HANDLE),
        ("hStdError", wt.HANDLE),
    ]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wt.HANDLE),
        ("hThread", wt.HANDLE),
        ("dwProcessId", wt.DWORD),
        ("dwThreadId", wt.DWORD),
    ]


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD),
        ("cntUsage", wt.DWORD),
        ("th32ProcessID", wt.DWORD),
        ("th32DefaultHeapID", ctypes.c_void_p),
        ("th32ModuleID", wt.DWORD),
        ("cntThreads", wt.DWORD),
        ("th32ParentProcessID", wt.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wt.DWORD),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


kernel32.CreateProcessW.argtypes = [
    wt.LPCWSTR, wt.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, wt.BOOL,
    wt.DWORD, ctypes.c_void_p, wt.LPCWSTR, ctypes.POINTER(STARTUPINFOW),
    ctypes.POINTER(PROCESS_INFORMATION),
]
kernel32.CreateProcessW.restype = wt.BOOL
kernel32.VirtualAllocEx.restype = ctypes.c_void_p
kernel32.WriteProcessMemory.argtypes = [
    wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_size_t),
]
kernel32.GetModuleHandleW.restype = wt.HMODULE
kernel32.GetProcAddress.restype = ctypes.c_void_p
kernel32.GetProcAddress.argtypes = [wt.HMODULE, ctypes.c_char_p]
kernel32.CreateRemoteThread.restype = wt.HANDLE
kernel32.ResumeThread.argtypes = [wt.HANDLE]
kernel32.ResumeThread.restype = wt.DWORD
kernel32.TerminateProcess.argtypes = [wt.HANDLE, wt.UINT]


def is_64bit_windows():
    return ctypes.sizeof(ctypes.c_void_p) == 8


def is_wow64(process_handle):
    flag = wt.BOOL(False)
    fn = getattr(kernel32, "IsWow64Process", None)
    if not fn:
        return False
    if not fn(process_handle, ctypes.byref(flag)):
        return False
    return bool(flag.value)


def exe_is_64bit(path):
    """Read PE machine type. True if x64, False if x86, None if unknown."""
    try:
        with open(path, "rb") as f:
            data = f.read(4096)
        if data[:2] != b"MZ":
            return None
        e_lfanew = int.from_bytes(data[0x3C:0x40], "little")
        machine = int.from_bytes(data[e_lfanew + 4:e_lfanew + 6], "little")
        if machine == 0x8664:
            return True
        if machine == 0x14C:
            return False
        return None
    except Exception:
        return None


def dll_path():
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, "native", "BindHook.dll"),
        os.path.join(here, "BindHook.dll"),
    ]
    if getattr(sys, "frozen", False):
        candidates.insert(0, os.path.join(os.path.dirname(sys.executable), "BindHook.dll"))
        candidates.insert(0, os.path.join(sys._MEIPASS, "BindHook.dll"))  # type: ignore[attr-defined]
    for p in candidates:
        if os.path.isfile(p):
            return os.path.abspath(p)
    return None


def guess_mode(exe_path):
    name = os.path.basename(exe_path or "").lower()
    if name in BROWSER_NAMES or name in CHROMIUM_LIKE:
        return "proxy"
    return "bind"


def is_chromium_like(exe_path):
    name = os.path.basename(exe_path or "").lower()
    return name in CHROMIUM_LIKE or name.endswith("browser.exe")


def is_firefox(exe_path):
    return os.path.basename(exe_path or "").lower() == "firefox.exe"


def list_running_processes():
    """Return list of dicts: pid, name, exe."""
    import psutil
    rows = []
    for p in psutil.process_iter(["pid", "name", "exe"]):
        info = p.info
        exe = info.get("exe") or ""
        if not exe:
            continue
        rows.append({
            "pid": info["pid"],
            "name": info.get("name") or os.path.basename(exe),
            "exe": exe,
        })
    rows.sort(key=lambda r: (r["name"].lower(), r["pid"]))
    return rows


def close_by_exe(exe_path, timeout=8):
    import psutil
    target = os.path.normcase(os.path.abspath(exe_path))
    killed = []
    for p in psutil.process_iter(["pid", "exe", "name"]):
        try:
            pexe = p.info.get("exe") or ""
            if os.path.normcase(os.path.abspath(pexe)) == target:
                p.terminate()
                killed.append(p.pid)
        except (psutil.Error, OSError, ValueError):
            continue
    if not killed:
        # fallback: match by basename
        base = os.path.basename(target).lower()
        for p in psutil.process_iter(["pid", "name"]):
            try:
                if (p.info.get("name") or "").lower() == base:
                    p.terminate()
                    killed.append(p.pid)
            except (psutil.Error, OSError):
                continue
    deadline = time.time() + timeout
    while time.time() < deadline and killed:
        still = []
        for pid in killed:
            try:
                if psutil.pid_exists(pid):
                    still.append(pid)
            except Exception:
                pass
        if not still:
            break
        time.sleep(0.2)
    for pid in killed:
        try:
            if psutil.pid_exists(pid):
                psutil.Process(pid).kill()
        except Exception:
            pass
    return killed


def _env_block(extra):
    env = os.environ.copy()
    env.update(extra)
    # UTF-16LE block, each entry KEY=VAL\0, terminated by extra \0
    parts = []
    for k, v in env.items():
        parts.append("%s=%s" % (k, v))
    raw = "\0".join(parts) + "\0\0"
    return ctypes.create_unicode_buffer(raw)


def inject_and_launch(exe_path, args, workdir, bind_ip, if_index, extra_env=None):
    hook = dll_path()
    if not hook:
        raise RuntimeError("找不到 BindHook.dll，无法做网卡绑定启动。请先运行 build.ps1 编译，或改用「浏览器代理」模式。")

    bit64 = exe_is_64bit(exe_path)
    if bit64 is False:
        raise RuntimeError("目标程序是 32 位，当前绑定模块只支持 64 位程序。请改用浏览器代理模式，或使用 64 位版本的软件。")

    si = STARTUPINFOW()
    si.cb = ctypes.sizeof(STARTUPINFOW)
    pi = PROCESS_INFORMATION()

    cmd = '"%s"' % exe_path
    if args:
        cmd = cmd + " " + args
    cmd_buf = ctypes.create_unicode_buffer(cmd)

    extra = {
        "SPLITNIC_BIND_IP": str(bind_ip),
        "SPLITNIC_IFINDEX": str(int(if_index)),
    }
    if extra_env:
        extra.update(extra_env)
    env_buf = _env_block(extra)

    flags = CREATE_SUSPENDED | CREATE_UNICODE_ENVIRONMENT
    cwd = workdir if workdir else os.path.dirname(exe_path)
    if not cwd:
        cwd = None

    ok = kernel32.CreateProcessW(
        None, cmd_buf, None, None, False, flags,
        ctypes.cast(env_buf, ctypes.c_void_p), cwd, ctypes.byref(si), ctypes.byref(pi),
    )
    if not ok:
        raise OSError("CreateProcess 失败，错误码 %s" % ctypes.get_last_error())

    try:
        if is_wow64(pi.hProcess):
            kernel32.TerminateProcess(pi.hProcess, 1)
            raise RuntimeError("目标是 32 位进程，无法注入 64 位绑定模块。")

        dll_buf = ctypes.create_unicode_buffer(hook)
        nbytes = (len(hook) + 1) * 2
        remote = kernel32.VirtualAllocEx(pi.hProcess, None, nbytes, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE)
        if not remote:
            raise OSError("VirtualAllocEx 失败，错误码 %s" % ctypes.get_last_error())
        written = ctypes.c_size_t(0)
        if not kernel32.WriteProcessMemory(pi.hProcess, remote, dll_buf, nbytes, ctypes.byref(written)):
            raise OSError("WriteProcessMemory 失败，错误码 %s" % ctypes.get_last_error())

        k32 = kernel32.GetModuleHandleW("kernel32.dll")
        load_lib = kernel32.GetProcAddress(k32, b"LoadLibraryW")
        if not load_lib:
            raise OSError("GetProcAddress(LoadLibraryW) 失败")

        thread = kernel32.CreateRemoteThread(pi.hProcess, None, 0, load_lib, remote, 0, None)
        if not thread:
            raise OSError("CreateRemoteThread 失败，错误码 %s。杀毒软件可能拦截了注入。" % ctypes.get_last_error())
        kernel32.WaitForSingleObject(thread, 8000)
        kernel32.CloseHandle(thread)
        kernel32.ResumeThread(pi.hThread)
        pid = pi.dwProcessId
        return pid
    except Exception:
        try:
            kernel32.TerminateProcess(pi.hProcess, 1)
        except Exception:
            pass
        raise
    finally:
        kernel32.CloseHandle(pi.hThread)
        kernel32.CloseHandle(pi.hProcess)


def launch_plain(exe_path, args, workdir, extra_env=None):
    si = STARTUPINFOW()
    si.cb = ctypes.sizeof(STARTUPINFOW)
    pi = PROCESS_INFORMATION()
    cmd = '"%s"' % exe_path
    if args:
        cmd = cmd + " " + args
    cmd_buf = ctypes.create_unicode_buffer(cmd)
    extra = extra_env or {}
    env_buf = _env_block(extra) if extra else None
    flags = CREATE_UNICODE_ENVIRONMENT if extra else 0
    cwd = workdir if workdir else os.path.dirname(exe_path) or None
    ok = kernel32.CreateProcessW(
        None, cmd_buf, None, None, False, flags,
        ctypes.cast(env_buf, ctypes.c_void_p) if env_buf else None,
        cwd, ctypes.byref(si), ctypes.byref(pi),
    )
    if not ok:
        raise OSError("CreateProcess 失败，错误码 %s" % ctypes.get_last_error())
    pid = pi.dwProcessId
    kernel32.CloseHandle(pi.hThread)
    kernel32.CloseHandle(pi.hProcess)
    return pid


def chromium_proxy_args(socks_port):
    return [
        "--proxy-server=socks5://127.0.0.1:%s" % socks_port,
        "--proxy-bypass-list=<-loopback>;localhost;127.0.0.1",
        "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1",
    ]


def firefox_profile_dir(adapter_key):
    root = os.path.join(os.environ.get("APPDATA", "."), "SplitNIC", "firefox-profiles")
    path = os.path.join(root, adapter_key)
    os.makedirs(path, exist_ok=True)
    return path


def write_firefox_userjs(profile, socks_port):
    userjs = os.path.join(profile, "user.js")
    content = "\n".join([
        'user_pref("network.proxy.type", 1);',
        'user_pref("network.proxy.socks", "127.0.0.1");',
        'user_pref("network.proxy.socks_port", %s);' % int(socks_port),
        'user_pref("network.proxy.socks_version", 5);',
        'user_pref("network.proxy.socks_remote_dns", true);',
        'user_pref("network.proxy.http", "");',
        'user_pref("network.proxy.ssl", "");',
        'user_pref("network.proxy.share_proxy_settings", false);',
        'user_pref("network.proxy.no_proxies_on", "localhost, 127.0.0.1");',
        "",
    ])
    with open(userjs, "w", encoding="utf-8") as f:
        f.write(content)


def launch_app(rule, adapter, proxy_pool, log=lambda m: None):
    """
    rule: dict with exe, args, workdir, mode, close_existing
    adapter: dict with ipv4, if_index
    returns (pid, method_text)
    """
    exe = rule["exe"]
    if not os.path.isfile(exe):
        raise FileNotFoundError("找不到程序：%s" % exe)
    args = (rule.get("args") or "").strip()
    workdir = (rule.get("workdir") or "").strip()
    mode = rule.get("mode") or "auto"
    if mode == "auto":
        mode = guess_mode(exe)

    bind_ip = (adapter.get("ipv4") or [None])[0]
    if_index = adapter.get("if_index")
    if not bind_ip or not if_index:
        raise RuntimeError("网卡 %s 没有可用的 IPv4 地址，无法分流。" % adapter.get("name"))

    if rule.get("close_existing"):
        killed = close_by_exe(exe)
        if killed:
            log("已结束旧进程 PID %s" % ", ".join(str(x) for x in killed))
            time.sleep(0.4)

    if mode == "proxy":
        proxy = proxy_pool.get(bind_ip, if_index)
        extra_env = {
            "ALL_PROXY": "socks5://127.0.0.1:%s" % proxy.socks_port,
            "all_proxy": "socks5://127.0.0.1:%s" % proxy.socks_port,
            "HTTP_PROXY": "http://127.0.0.1:%s" % proxy.http_port,
            "HTTPS_PROXY": "http://127.0.0.1:%s" % proxy.http_port,
            "http_proxy": "http://127.0.0.1:%s" % proxy.http_port,
            "https_proxy": "http://127.0.0.1:%s" % proxy.http_port,
        }
        extra_args = []
        if is_firefox(exe):
            key = "".join(ch if ch.isalnum() else "_" for ch in (adapter.get("guid") or str(if_index)))
            profile = firefox_profile_dir(key[:40])
            write_firefox_userjs(profile, proxy.socks_port)
            extra_args = ["-profile", '"%s"' % profile, "-no-remote"]
            log("Firefox 使用独立配置目录（书签与日常配置不共用）")
        elif is_chromium_like(exe):
            extra_args = chromium_proxy_args(proxy.socks_port)
        if extra_args:
            args = (args + " " + " ".join(extra_args)).strip()
        pid = launch_plain(exe, args, workdir, extra_env=extra_env)
        return pid, "浏览器/代理分流 → %s" % bind_ip

    if mode == "bind":
        pid = inject_and_launch(exe, args, workdir, bind_ip, if_index)
        return pid, "网卡绑定启动 → %s" % bind_ip

    if mode == "plain":
        pid = launch_plain(exe, args, workdir)
        return pid, "普通启动（未绑定网卡）"

    raise RuntimeError("未知启动模式：%s" % mode)
