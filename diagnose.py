# -*- coding: utf-8 -*-
"""Built-in diagnostics for SplitNIC."""
from __future__ import print_function

import os
import sys
import time
import socket
import ctypes
import traceback


def _ok(msg):
    return "OK    " + msg


def _fail(msg):
    return "FAIL  " + msg


def _info(msg):
    return "INFO  " + msg


def run_selftest(include_inject=True):
    lines = []
    lines.append("SplitNIC 自检")
    lines.append("Python %s  %s" % (sys.version.split()[0], sys.executable))
    lines.append("64-bit 解释器" if ctypes.sizeof(ctypes.c_void_p) == 8 else "32-bit 解释器（不支持）")

    try:
        admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        admin = False
    lines.append(_ok("管理员权限") if admin else _info("当前不是管理员（浏览器代理仍可用，网卡绑定可能失败）"))

    from launcher import dll_path
    hook = dll_path()
    if not hook:
        lines.append(_fail("找不到 BindHook.dll"))
    else:
        lines.append(_ok("BindHook.dll  " + hook))
        try:
            h = ctypes.WinDLL(hook)
            lines.append(_ok("本进程可以 LoadLibrary(BindHook.dll)"))
            del h
        except Exception as exc:
            lines.append(_fail("LoadLibrary(BindHook.dll) 失败：%s" % exc))

    from adapters import list_adapters, usable_adapters, apply_unicast_if
    try:
        all_nics = list_adapters(include_down=True, include_loopback=False)
        usable = usable_adapters()
        lines.append(_ok("网卡枚举成功，共 %d 张，可用 %d 张" % (len(all_nics), len(usable))))
        for a in all_nics:
            ip = ",".join(a.get("ipv4") or []) or "-"
            lines.append("      - %s  %s  %s  IPv4=%s  ifIndex=%s" % (
                a["name"], a["kind_label"], a["oper_label"], ip, a["if_index"]))
        if len(usable) < 2:
            lines.append(_fail("已连接且有 IPv4 的网卡不足 2 张，无法做双网分流"))
        else:
            lines.append(_ok("满足双网分流条件"))
    except Exception as exc:
        usable = []
        lines.append(_fail("网卡枚举失败：%s" % exc))
        lines.append(traceback.format_exc())

    probe_targets = [("223.5.5.5", 443), ("www.baidu.com", 80), ("8.8.8.8", 53)]
    for a in usable:
        ip = a["ipv4"][0]
        last_err = None
        reached = None
        for host, port in probe_targets:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                sock.settimeout(4)
                sock.bind((ip, 0))
                apply_unicast_if(sock, a["if_index"])
                sock.connect((host, port))
                reached = "%s:%s" % (host, port)
                break
            except Exception as exc:
                last_err = exc
            finally:
                try:
                    sock.close()
                except Exception:
                    pass
        if reached:
            lines.append(_ok("%s (%s) 绑定 %s 后能连 %s" % (a["name"], a["kind_label"], ip, reached)))
        else:
            lines.append(_fail("%s (%s) 绑定 %s 出口测试失败：%s" % (a["name"], a["kind_label"], ip, last_err)))

    if usable:
        from socks_proxy import AdapterProxy
        a = usable[0]
        proxy = AdapterProxy(a["ipv4"][0], a["if_index"])
        try:
            sp, hp = proxy.start()
            lines.append(_ok("本地代理已启动 SOCKS %s  HTTP %s" % (sp, hp)))
            c = socket.create_connection(("127.0.0.1", sp), timeout=5)
            c.sendall(b"\x05\x01\x00")
            hello = c.recv(2)
            if hello != b"\x05\x00":
                raise RuntimeError("SOCKS 握手失败 %r" % hello)
            req = b"\x05\x01\x00\x01" + socket.inet_aton("223.5.5.5") + b"\x01\xbb"
            c.sendall(req)
            reply = c.recv(16)
            if not reply or reply[1] != 0:
                raise RuntimeError("SOCKS CONNECT 223.5.5.5 失败 %r" % reply)
            lines.append(_ok("经 SOCKS 代理 CONNECT 223.5.5.5:443 成功"))
            c.close()
        except Exception as exc:
            lines.append(_fail("代理自检失败：%s" % exc))
        finally:
            proxy.stop()

    if include_inject and usable and hook:
        notepad = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "notepad.exe")
        if os.path.isfile(notepad):
            from launcher import inject_and_launch
            import psutil
            a = usable[0]
            pid = None
            try:
                pid = inject_and_launch(notepad, "", "", a["ipv4"][0], a["if_index"])
                time.sleep(1.2)
                if psutil.pid_exists(pid):
                    lines.append(_ok("向 notepad.exe 注入 BindHook 后进程仍存活 PID %s" % pid))
                else:
                    lines.append(_fail("向 notepad.exe 注入后进程立刻退出，挂钩仍可能有问题"))
            except Exception as exc:
                lines.append(_fail("notepad 注入失败：%s" % exc))
            finally:
                if pid:
                    try:
                        p = psutil.Process(pid)
                        p.terminate()
                        p.wait(3)
                    except Exception:
                        pass
        else:
            lines.append(_info("没有 notepad.exe，跳过注入测试"))

    return "\n".join(lines)


if __name__ == "__main__":
    print(run_selftest())
