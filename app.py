# -*- coding: utf-8 -*-
"""
网口分流 SplitNIC
Windows 多网卡按应用分流：为每个软件指定走有线网、无线网或 VPN 网卡。
"""
from __future__ import print_function

import os
import sys
import json
import uuid
import time
import ctypes
import threading
import traceback

# Make local imports work when frozen or run from any cwd.
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

os.chdir(HERE)

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

import customtkinter as ctk
from tkinter import filedialog, messagebox

HAS_DND = False
try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    HAS_DND = True
except Exception:
    TkinterDnD = None
    DND_FILES = None

from adapters import usable_adapters, list_adapters, find_adapter, public_ip_via, KIND_LABELS
from socks_proxy import ProxyPool
from launcher import (
    launch_app, list_running_processes, dll_path, guess_mode,
    is_rule_running, stop_rule_processes, has_anticheat,
)
from diagnose import run_selftest
from simple_board import SimpleBoard
from winutil import (
    ensure_single_instance, create_desktop_shortcuts, set_start_with_windows,
    is_start_with_windows, create_rule_shortcut, create_all_rule_shortcuts,
    post_ipc, drain_ipc, bring_existing_to_front, spawn_unelevated_self,
)

APP_NAME = "网口分流"
APP_NAME_EN = "SplitNIC"
CONFIG_DIR = os.path.join(os.environ.get("APPDATA", "."), "SplitNIC")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

KIND_COLOR = {
    "wired": "#22c55e",
    "wifi": "#38bdf8",
    "vpn": "#a78bfa",
    "virtual": "#f59e0b",
    "other": "#94a3b8",
}

MODE_LABELS = {
    "auto": "自动",
    "bind": "网卡绑定",
    "proxy": "浏览器代理",
    "plain": "普通启动",
}

HELP_TEXT = """\
【这是什么】
电脑同时连着有线网和无线网（或再加 VPN）时，Windows 默认会自己挑一张网卡出门。
本工具让你指定：某个软件走哪一张网卡。

典型用法：
  · 有线网  →  WorkBuddy、VPN 客户端
  · 无线网  →  抖音、Chrome / Edge / 浏览器

【怎么用】
1. 用普通方式打开（不要「以管理员运行」）。管理员窗口会被 Windows 禁止从桌面拖入图标。
2. 确认顶部同时出现有线网和无线网。
3. 把桌面上的应用快捷方式拖到对应网络卡片里，点图标就能启动。网卡绑定失败时再点右上角「管理员」。
4. 右上角「高级模式」才是原来的表格、诊断和手动配置。
5. 右键图标可以放到桌面、改详细设置或移除。

【启动模式】
  · 自动：浏览器走本地代理，其它程序尝试网卡绑定（注入 BindHook.dll）。
  · 网卡绑定：把程序的网络连接绑到指定网卡的 IP / 接口（适合多数 Win32 软件、VPN 客户端）。
  · 浏览器代理：在本机起一个只从该网卡出站的 SOCKS5/HTTP 代理，再把浏览器指过去（适合 Chrome / Edge / Firefox / 抖音）。
  · 普通启动：不分流，只是替你打开程序。

【必须知道的限制】
  · 微软商店 UWP 应用无法分流。
  · 带反作弊的游戏往往会拒绝 DLL 注入，请不要对这类程序使用「网卡绑定」。
  · 启动后规则上会显示「出口 x.x.x.x」，那是这张网卡测到的公网 IP，用来确认有没有走对。
  · 开机启动会带上「按规则自动拉起软件」。网卡重新插上后，也会自动启动勾了「自动启动」且当时没在运行的软件。
  · Chrome / Edge / 抖音默认使用独立配置目录，和日常浏览器分开，不必先关掉你正在用的那个。
  · 绑定网卡掉线时，默认会结束对应软件，避免 WorkBuddy / VPN 悄悄改走 Wi-Fi。
  · 开机自动拉起会等到网卡拿到 IPv4（最多约 90 秒），避免 DHCP 还没完成就启动失败。
  · Firefox 代理模式同样使用独立配置目录，和日常书签/登录不是同一套。
  · 32 位程序无法使用当前的 64 位绑定模块，请改用代理模式或 64 位版本。
  · 部分杀毒软件会拦截注入，请把 SplitNIC 和 BindHook.dll 加入信任列表。
  · DNS 仍可能从「默认网卡」出去（DNS 泄漏）。若两个网络的 DNS 策略不同，请在网卡属性里各自填写 DNS，或关掉不用的网卡的 IPv6。
  · 若开着 IPv6，流量可能从另一张网卡的 IPv6 溜走。不需要 IPv6 时建议在不用的网卡上取消勾选 IPv6。
  · VPN 分两种绑法，不要搞混：
        ① 让「VPN 客户端」走有线网去连服务器 → 把 VPN.exe 绑到有线网；
        ② 让某个软件走已经连上的 VPN 隧道 → 把该软件绑到 VPN 虚拟网卡（不是绑到 VPN.exe）。
  · 本工具不是杀毒、不是防火墙、不能保证匿名。分流失败时程序仍可能从默认网卡上网。
  · 请只在自己的电脑上使用；不要对系统关键进程（csrss、lsass、svchost、explorer）做注入。

【找不到网卡？】
  · 网线没插、Wi-Fi 没连、适配器被禁用，都不会出现在「可用」列表。
  · 点「刷新网卡」。虚拟网卡（VMware、Hyper-V、Bluetooth PAN）一般应忽略。
"""


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin():
    extra = [a for a in sys.argv[1:] if a != "--elevated"]
    extra.append("--elevated")
    if getattr(sys, "frozen", False):
        exe = sys.executable
        args = " ".join('"%s"' % a if " " in a else a for a in extra)
    else:
        exe = sys.executable
        args = '"%s" %s' % (
            os.path.abspath(sys.argv[0]),
            " ".join('"%s"' % a if " " in a else a for a in extra),
        )
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, args, None, 1)
    return rc > 32


def load_config():
    if not os.path.isfile(CONFIG_FILE):
        return {"rules": [], "settings": _apply_setting_defaults({})}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"rules": []}
        data.setdefault("rules", [])
        data.setdefault("settings", {})
        _apply_setting_defaults(data["settings"])
        return data
    except Exception:
        return {"rules": [], "settings": _apply_setting_defaults({})}


def _apply_setting_defaults(settings):
    settings.setdefault("minimize_to_tray", True)
    settings.setdefault("start_with_windows", False)
    settings.setdefault("auto_refresh", True)
    settings.setdefault("auto_launch_on_nic", True)
    settings.setdefault("kill_on_nic_down", True)
    settings.setdefault("launch_wait_nic", True)
    settings.setdefault("launch_wait_seconds", 90)
    settings.setdefault("isolated_browser_profile", True)
    return settings


def save_config(data):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    tmp = CONFIG_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_FILE)


def new_rule(**kwargs):
    rule = {
        "id": uuid.uuid4().hex,
        "name": "",
        "exe": "",
        "args": "",
        "workdir": "",
        "adapter_guid": "",
        "adapter_name": "",
        "adapter_kind": "",
        "mode": "auto",
        "close_existing": True,
        "enabled": True,
        "auto_launch": True,
        "kill_on_down": True,
        "isolated_profile": True,
    }
    rule.update(kwargs)
    return rule


class ProcessPicker(ctk.CTkToplevel):
    def __init__(self, master, on_pick):
        super().__init__(master)
        self.on_pick = on_pick
        self.title("从正在运行的进程添加")
        self.geometry("640x520")
        self.transient(master)
        self.grab_set()
        self.rows = []

        ctk.CTkLabel(self, text="搜索进程", font=("Microsoft YaHei UI", 13)).pack(anchor="w", padx=16, pady=(14, 4))
        self.search = ctk.CTkEntry(self, placeholder_text="输入名称或路径，例如 chrome、抖音、WorkBuddy")
        self.search.pack(fill="x", padx=16)
        self.search.bind("<KeyRelease>", lambda e: self.refresh())

        self.box = ctk.CTkScrollableFrame(self, height=360)
        self.box.pack(fill="both", expand=True, padx=16, pady=10)

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=16, pady=(0, 14))
        ctk.CTkButton(bar, text="刷新", width=90, command=self.reload).pack(side="left")
        ctk.CTkButton(bar, text="取消", width=90, fg_color="gray", command=self.destroy).pack(side="right")

        self.after(80, self.reload)

    def reload(self):
        try:
            self.rows = list_running_processes()
        except Exception as exc:
            messagebox.showerror(APP_NAME, "读取进程失败：%s" % exc)
            self.rows = []
        self.refresh()

    def refresh(self):
        for w in self.box.winfo_children():
            w.destroy()
        q = (self.search.get() or "").strip().lower()
        shown = 0
        for row in self.rows:
            blob = (row["name"] + " " + row["exe"]).lower()
            if q and q not in blob:
                continue
            shown += 1
            if shown > 80:
                ctk.CTkLabel(self.box, text="结果太多，请再输入几个字过滤…", text_color="gray").pack(anchor="w", pady=6)
                break
            line = ctk.CTkFrame(self.box, fg_color=("gray90", "gray17"))
            line.pack(fill="x", pady=2)
            ctk.CTkLabel(line, text="%s    PID %s" % (row["name"], row["pid"]),
                         font=("Microsoft YaHei UI", 13, "bold"), width=260, anchor="w").pack(side="left", padx=8, pady=6)
            ctk.CTkLabel(line, text=row["exe"], text_color="gray", anchor="w").pack(side="left", fill="x", expand=True)
            ctk.CTkButton(line, text="选择", width=70,
                          command=lambda r=row: self.pick(r)).pack(side="right", padx=8)

    def pick(self, row):
        self.on_pick(row)
        self.destroy()


class RuleEditor(ctk.CTkToplevel):
    def __init__(self, master, adapters, rule, on_save):
        super().__init__(master)
        self.adapters = adapters
        self.rule = dict(rule)
        self.on_save = on_save
        self.title("编辑分流规则" if rule.get("exe") else "添加软件")
        self.geometry("620x680")
        self.transient(master)
        self.grab_set()

        pad = {"padx": 18, "pady": (10, 0)}
        ctk.CTkLabel(self, text="显示名称", font=("Microsoft YaHei UI", 13)).pack(anchor="w", **pad)
        self.e_name = ctk.CTkEntry(self)
        self.e_name.pack(fill="x", padx=18)

        ctk.CTkLabel(self, text="程序路径（.exe）", font=("Microsoft YaHei UI", 13)).pack(anchor="w", **pad)
        path_row = ctk.CTkFrame(self, fg_color="transparent")
        path_row.pack(fill="x", padx=18)
        self.e_exe = ctk.CTkEntry(path_row)
        self.e_exe.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(path_row, text="浏览…", width=80, command=self.browse).pack(side="left", padx=(8, 0))

        ctk.CTkLabel(self, text="启动参数（可选）", font=("Microsoft YaHei UI", 13)).pack(anchor="w", **pad)
        self.e_args = ctk.CTkEntry(self)
        self.e_args.pack(fill="x", padx=18)

        ctk.CTkLabel(self, text="工作目录（可选，默认用 exe 所在目录）", font=("Microsoft YaHei UI", 13)).pack(anchor="w", **pad)
        self.e_cwd = ctk.CTkEntry(self)
        self.e_cwd.pack(fill="x", padx=18)

        ctk.CTkLabel(self, text="走哪一张网卡", font=("Microsoft YaHei UI", 13)).pack(anchor="w", **pad)
        values = []
        self._adapter_map = {}
        for a in adapters:
            ip = (a.get("ipv4") or ["无 IPv4"])[0]
            label = "%s  ·  %s  ·  %s" % (a["name"], a["kind_label"], ip)
            values.append(label)
            self._adapter_map[label] = a
        self.cb_adapter = ctk.CTkComboBox(self, values=values or ["（没有可用网卡，请先连接）"], width=560)
        self.cb_adapter.pack(fill="x", padx=18)
        if values:
            picked = None
            for label, a in self._adapter_map.items():
                if rule.get("adapter_guid") and a["guid"] == rule["adapter_guid"]:
                    picked = label
                    break
                if rule.get("adapter_name") and a["name"] == rule["adapter_name"]:
                    picked = label
            self.cb_adapter.set(picked or values[0])

        ctk.CTkLabel(self, text="启动模式", font=("Microsoft YaHei UI", 13)).pack(anchor="w", **pad)
        self.cb_mode = ctk.CTkComboBox(
            self, values=["自动", "网卡绑定", "浏览器代理", "普通启动"], width=240)
        self.cb_mode.pack(anchor="w", padx=18)
        reverse = {v: k for k, v in MODE_LABELS.items()}
        self.cb_mode.set(MODE_LABELS.get(rule.get("mode") or "auto", "自动"))

        self.var_close = ctk.BooleanVar(value=bool(rule.get("close_existing", True)))
        ctk.CTkCheckBox(self, text="启动前先关闭已运行的同名进程（浏览器 / 抖音必须勾选）",
                        variable=self.var_close).pack(anchor="w", padx=18, pady=(14, 4))
        self.var_auto = ctk.BooleanVar(value=bool(rule.get("auto_launch", True)))
        ctk.CTkCheckBox(self, text="开机 / 这张网卡重新连上时，若软件没在运行则自动启动",
                        variable=self.var_auto).pack(anchor="w", padx=18, pady=(4, 4))
        self.var_kill = ctk.BooleanVar(value=bool(rule.get("kill_on_down", True)))
        ctk.CTkCheckBox(self, text="这张网卡掉线时结束此软件，防止改走别的网",
                        variable=self.var_kill).pack(anchor="w", padx=18, pady=(4, 4))
        self.var_iso = ctk.BooleanVar(value=bool(rule.get("isolated_profile", True)))
        ctk.CTkCheckBox(self, text="浏览器用独立配置（不关掉你日常的 Chrome/Edge/抖音）",
                        variable=self.var_iso).pack(anchor="w", padx=18, pady=(4, 10))

        self.e_name.insert(0, rule.get("name") or "")
        self.e_exe.insert(0, rule.get("exe") or "")
        self.e_args.insert(0, rule.get("args") or "")
        self.e_cwd.insert(0, rule.get("workdir") or "")

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=18, pady=16)
        ctk.CTkButton(bar, text="保存", width=120, command=self.save).pack(side="right")
        ctk.CTkButton(bar, text="取消", width=90, fg_color="gray", command=self.destroy).pack(side="right", padx=8)

    def browse(self):
        path = filedialog.askopenfilename(
            parent=self, title="选择要分流的程序",
            filetypes=[("程序", "*.exe"), ("全部文件", "*.*")],
        )
        if not path:
            return
        self.e_exe.delete(0, "end")
        self.e_exe.insert(0, path)
        if not self.e_name.get().strip():
            self.e_name.insert(0, os.path.splitext(os.path.basename(path))[0])

    def save(self):
        exe = self.e_exe.get().strip()
        name = self.e_name.get().strip() or os.path.splitext(os.path.basename(exe))[0]
        if not exe or not os.path.isfile(exe):
            messagebox.showerror(APP_NAME, "请选择一个有效的 .exe 文件。", parent=self)
            return
        label = self.cb_adapter.get()
        adapter = self._adapter_map.get(label)
        if not adapter:
            messagebox.showerror(APP_NAME, "请选择一张网卡。", parent=self)
            return
        mode_ui = self.cb_mode.get()
        mode = {v: k for k, v in MODE_LABELS.items()}.get(mode_ui, "auto")
        self.rule.update({
            "name": name,
            "exe": exe,
            "args": self.e_args.get().strip(),
            "workdir": self.e_cwd.get().strip(),
            "adapter_guid": adapter["guid"],
            "adapter_name": adapter["name"],
            "adapter_kind": adapter["kind"],
            "mode": mode,
            "close_existing": bool(self.var_close.get()),
            "auto_launch": bool(self.var_auto.get()),
            "kill_on_down": bool(self.var_kill.get()),
            "isolated_profile": bool(self.var_iso.get()),
        })
        self.on_save(self.rule)
        self.destroy()


class SplitNICApp(ctk.CTkFrame):
    def __init__(self, master, pending_cmds=None, start_minimized=False):
        super().__init__(master, fg_color="#0b0e14")
        self.root = master
        self._has_dnd = HAS_DND
        self._advanced = False

        self.config_data = load_config()
        self.adapters = []
        self.proxy_pool = ProxyPool(log=self.log)
        self._busy = False
        self._tray = None
        self._nic_sig = None
        self._up_guids = set()
        self._quitting = False
        self._egress = {}
        self._adapter_pub = {}
        self._pending_cmds = list(pending_cmds or [])
        self._start_minimized = bool(start_minimized)
        self._boot_done = False
        self._queue = []
        self._wait_since = {}
        self._started_at = time.time()

        self.font_title = ctk.CTkFont(family="Microsoft YaHei UI", size=26, weight="bold")
        self.font_h = ctk.CTkFont(family="Microsoft YaHei UI", size=15, weight="bold")
        self.font = ctk.CTkFont(family="Microsoft YaHei UI", size=13)
        self.font_small = ctk.CTkFont(family="Microsoft YaHei UI", size=12)

        self._build()
        self.refresh_adapters()
        self.render_rules()
        self._drop_hook = None
        self._ole_site = None
        self._drop_guard = (0, ())
        self.after(200, self._warn_if_needed)
        self.after(300, self._install_native_drop)
        self.after(800, self._ensure_normal_shortcut)
        self.after(400, self._start_tray)
        self.after(700, self._poll_ipc)
        self.after(900, self._run_pending)
        self.after(1200, self._schedule_auto_refresh)
        self.bind("<F5>", lambda e: self.refresh_adapters())
        self.after(80, self._force_show)
        if self._start_minimized:
            self.after(400, self.root.withdraw)

    def _force_show(self):
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.attributes("-topmost", True)
            self.after(600, lambda: self.root.attributes("-topmost", False))
        except Exception:
            pass

    def _build(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=28, pady=(18, 8))
        ctk.CTkLabel(header, text=APP_NAME, font=self.font_title, text_color="#f8fafc").pack(side="left")

        self.btn_mode = ctk.CTkButton(
            header, text="高级模式", width=96, height=34, corner_radius=10,
            fg_color="#1e293b", hover_color="#334155", text_color="#e2e8f0",
            command=self.toggle_advanced,
        )
        self.btn_mode.pack(side="right")
        self.admin_pill = ctk.CTkLabel(header, text="", font=self.font_small, width=120)
        self.admin_pill.pack(side="right", padx=10)
        self.btn_elevate = ctk.CTkButton(
            header, text="管理员", width=84, height=34, corner_radius=10,
            fg_color="#1e293b", hover_color="#334155", command=self.elevate,
        )
        self.btn_elevate.pack(side="right", padx=(0, 6))
        self._set_admin_pill()

        self.simple_board = SimpleBoard(self, self)
        self.simple_board.pack(fill="both", expand=True, padx=24, pady=(0, 18))

        self.advanced_wrap = ctk.CTkFrame(self, fg_color="transparent")
        self.tabs = ctk.CTkTabview(self.advanced_wrap)
        self.tabs.pack(fill="both", expand=True, padx=18, pady=(0, 8))
        self.tab_main = self.tabs.add("分流")
        self.tab_nics = self.tabs.add("网卡详情")
        self.tab_diag = self.tabs.add("诊断")
        self.tab_settings = self.tabs.add("设置")
        self.tab_help = self.tabs.add("使用说明与注意事项")

        self._build_main(self.tab_main)
        self._build_nics(self.tab_nics)
        self._build_diag(self.tab_diag)
        self._build_settings(self.tab_settings)
        self._build_help(self.tab_help)

        self.log_wrap = ctk.CTkFrame(self.advanced_wrap, fg_color="#141a22")
        ctk.CTkLabel(self.log_wrap, text="运行日志", font=self.font_h).pack(anchor="w", padx=10, pady=(8, 0))
        self.log_box = ctk.CTkTextbox(self.log_wrap, height=120, font=self.font_small)
        self.log_box.pack(fill="x", padx=10, pady=(4, 10))
        self.log_box.configure(state="disabled")
        self.log_wrap.pack(fill="x", padx=18, pady=(0, 14))

    def _set_admin_pill(self):
        if is_admin():
            self.admin_pill.configure(text="管理员", text_color="#34d399")
            self.btn_elevate.pack_forget()
        else:
            self.admin_pill.configure(text="普通权限", text_color="#fbbf24")

    def elevate(self):
        if relaunch_as_admin():
            self.on_close()
        else:
            messagebox.showerror(APP_NAME, "提权失败。网卡绑定不是必须提权；浏览器/抖音用代理模式即可。")

    def _ensure_normal_shortcut(self):
        """Desktop shortcut must NOT request admin, or Explorer drag-drop is blocked."""
        try:
            create_desktop_shortcuts(run_as_admin=False)
        except Exception:
            pass

    def _install_native_drop(self):
        try:
            from ole_drop import OleDropSite
        except Exception as exc:
            self.log("系统拖放模块加载失败：%s" % exc)
            OleDropSite = None
        if OleDropSite is not None:
            if self._ole_site is None:
                self._ole_site = OleDropSite(
                    self.root,
                    on_drop=self._on_ole_drop,
                    on_over=self._on_ole_over,
                    on_leave=self._on_ole_leave,
                )
            added = 0
            try:
                added = self._ole_site.install()
            except Exception as exc:
                self.log("系统拖放注册失败：%s" % exc)
            n = self._ole_site.registered_count()
            if added and not getattr(self, "_ole_logged", False):
                self.log("系统拖放已接管 %d 个窗口，可把桌面快捷方式拖进网卡" % n)
                self._ole_logged = True
            elif n == 0 and self._ole_site.last_error:
                self.log("系统拖放未就绪：%s" % self._ole_site.last_error)
        if HAS_DND and DND_FILES:
            try:
                from dropfiles import bind_drop
                bind_drop(self.root, self._on_tk_drop)
            except Exception as exc:
                self.log("tkdnd 备用拖入失败：%s" % exc)
        if hasattr(self, "simple_board"):
            self.simple_board.bind_os_drops()
        if is_admin():
            self.log("当前是管理员：Windows 会禁止从桌面拖文件进来。请关掉后用桌面「网口分流」普通打开。")
            if hasattr(self, "simple_board"):
                self.simple_board.set_status("管理员窗口拖不进桌面图标。请关掉，用普通方式打开后再拖")

    def _on_ole_drop(self, files, x, y):
        from dropfiles import files_from_drop
        exes = files_from_drop(files)
        self.log("拖入：%s → %s" % (
            "；".join(os.path.basename(p) for p in (files or [])),
            "；".join(os.path.basename(e) for e in exes) or "未能识别",
        ))
        self._on_desktop_drop(exes, int(x), int(y), files)

    def _on_ole_over(self, x, y):
        if getattr(self, "_advanced", False):
            return
        board = getattr(self, "simple_board", None)
        if board is None:
            return
        zone = board._zone_at(x, y)
        board._set_hot(zone._guid if zone is not None else None)

    def _on_ole_leave(self):
        board = getattr(self, "simple_board", None)
        if board is not None:
            board._set_hot(None)

    def _on_tk_drop(self, event):
        from dropfiles import files_from_drop
        data = getattr(event, "data", "") or ""
        try:
            parts = list(self.tk.splitlist(data))
        except Exception:
            parts = [data]
        exes = files_from_drop(parts)
        x = getattr(event, "x_root", None)
        y = getattr(event, "y_root", None)
        if x is None or y is None:
            x = int(self.root.winfo_pointerx())
            y = int(self.root.winfo_pointery())
        self.log("拖入：%s → %s" % (data, "；".join(os.path.basename(e) for e in exes) or "未能识别"))
        self._on_desktop_drop(exes, int(x), int(y), parts)
        return "copy"

    def _on_desktop_drop(self, exes, x, y, raw=None):
        if getattr(self, "_advanced", False):
            return
        key = tuple(exes or [])
        now = time.time()
        if key and key == self._drop_guard[1] and (now - self._drop_guard[0]) < 0.6:
            return
        self._drop_guard = (now, key)
        board = getattr(self, "simple_board", None)
        if board is None:
            return
        zone = board._zone_at(x, y)
        if not exes:
            board.set_status("请拖入程序图标（桌面快捷方式或 .exe）")
            board.flash_zones()
            return
        if zone is None:
            board.set_status("请拖到「有线网」或「无线网」那一张卡片上")
            board.flash_zones()
            return
        for exe in exes:
            self.add_exe_to_adapter(zone._adapter, exe_path=exe)
        board._set_hot(None)

    def toggle_advanced(self):
        self._advanced = not self._advanced
        if self._advanced:
            self.simple_board.pack_forget()
            self.advanced_wrap.pack(fill="both", expand=True, padx=0, pady=0)
            self.btn_mode.configure(text="简洁模式")
            self._render_rule_table()
        else:
            self.advanced_wrap.pack_forget()
            self.simple_board.pack(fill="both", expand=True, padx=24, pady=(0, 18))
            self.btn_mode.configure(text="高级模式")
            self.simple_board.refresh()

    def add_exe_to_adapter(self, adapter, exe_path=None):
        if not exe_path:
            exe_path = filedialog.askopenfilename(
                parent=self, title="选择要放到「%s」的程序" % (adapter.get("network_name") or adapter.get("name") or "这张网"),
                filetypes=[("程序", "*.exe"), ("全部文件", "*.*")],
            )
        if not exe_path or not os.path.isfile(exe_path):
            return
        exe_path = os.path.abspath(exe_path)
        key = os.path.normcase(exe_path)
        for r in self.config_data.get("rules") or []:
            if os.path.normcase(os.path.abspath(r.get("exe") or "")) == key:
                self.assign_rule_to_adapter(r, adapter)
                return
        name = os.path.splitext(os.path.basename(exe_path))[0]
        rule = new_rule(
            name=name, exe=exe_path, mode=guess_mode(exe_path),
            adapter_guid=adapter.get("guid") or "",
            adapter_name=adapter.get("name") or "",
            adapter_kind=adapter.get("kind") or "",
        )
        self.config_data.setdefault("rules", []).append(rule)
        self.persist()
        label = adapter.get("network_name") or adapter.get("name")
        self.log("已找到程序 %s → 放到 %s" % (exe_path, label))
        if hasattr(self, "simple_board"):
            self.simple_board.set_status("已找到 %s，放到 %s" % (os.path.basename(exe_path), label))
            self.simple_board.refresh()
            self.simple_board.bind_os_drops()
        self._after_rule_placed(rule, adapter)

    def _after_rule_placed(self, rule, adapter):
        exe = rule.get("exe") or ""
        label = adapter.get("network_name") or adapter.get("name")
        if has_anticheat(exe):
            msg = (
                "已找到对应程序：\n%s\n\n"
                "已放到「%s」，但这个游戏带反作弊，不能用网卡绑定分流"
                "（注入会被当成外挂，也可能根本绑不上）。\n\n"
                "分流请用抖音、Chrome、WorkBuddy、VPN 客户端这类软件；"
                "游戏请走系统默认网卡。"
            ) % (exe, label)
            self.log(msg.replace("\n", " "))
            if hasattr(self, "simple_board"):
                self.simple_board.set_status("已找到 %s，但这是带反作弊的游戏，不能分流" % os.path.basename(exe))
            self.after(0, lambda: messagebox.showwarning(APP_NAME, msg))
            return
        if hasattr(self, "simple_board"):
            self.simple_board.set_status("已找到 %s，正在用「%s」启动…" % (os.path.basename(exe), label))
        self.start_rule(rule)

    def assign_rule_to_adapter(self, rule, adapter):
        rid = rule.get("id")
        for r in self.config_data.get("rules") or []:
            if r.get("id") == rid:
                r["adapter_guid"] = adapter.get("guid") or ""
                r["adapter_name"] = adapter.get("name") or ""
                r["adapter_kind"] = adapter.get("kind") or ""
                break
        self.persist()
        label = adapter.get("network_name") or adapter.get("name")
        self.log("%s → %s（%s）" % (rule.get("name"), label, rule.get("exe")))
        if hasattr(self, "simple_board"):
            self.simple_board.set_status("%s 现在走 %s" % (rule.get("name"), label))
            self.simple_board.refresh()
        self._after_rule_placed(rule, adapter)

    def _build_main(self, tab):
        ctk.CTkLabel(tab, text="可用网卡", font=self.font_h).pack(anchor="w", pady=(4, 4))
        self.nic_bar = ctk.CTkFrame(tab, fg_color="transparent")
        self.nic_bar.pack(fill="x")

        tools = ctk.CTkFrame(tab, fg_color="transparent")
        tools.pack(fill="x", pady=(10, 4))
        ctk.CTkLabel(tools, text="分流规则", font=self.font_h).pack(side="left")
        ctk.CTkButton(tools, text="添加软件", width=100, command=self.add_rule).pack(side="right")
        ctk.CTkButton(tools, text="从进程添加", width=110, command=self.add_from_process).pack(side="right", padx=6)
        ctk.CTkButton(tools, text="启动全部", width=100, fg_color="#2563eb",
                      command=self.start_all).pack(side="right", padx=6)
        ctk.CTkButton(tools, text="刷新网卡", width=90, fg_color="gray",
                      command=self.refresh_adapters).pack(side="right", padx=6)
        ctk.CTkButton(tools, text="运行诊断", width=90, fg_color="#0f766e",
                      command=self.run_diagnose).pack(side="right", padx=6)
        ctk.CTkButton(tools, text="规则快捷方式", width=110, fg_color="#7c3aed",
                      command=self.make_all_rule_shortcuts).pack(side="right", padx=6)

        self.rule_box = ctk.CTkScrollableFrame(tab, height=280)
        self.rule_box.pack(fill="both", expand=True, pady=(4, 8))

        hint = (
            "示例：WorkBuddy / VPN → 有线网，抖音 / 浏览器 → 无线网。"
            "点「快捷方式」生成桌面图标，以后请用那个图标打开，不要用软件原来的图标。"
        )
        ctk.CTkLabel(tab, text=hint, font=self.font_small, text_color="gray",
                     wraplength=1000, justify="left").pack(anchor="w", pady=(0, 4))

    def _build_nics(self, tab):
        top = ctk.CTkFrame(tab, fg_color="transparent")
        top.pack(fill="x")
        ctk.CTkButton(top, text="刷新", width=80, command=self.refresh_adapters).pack(side="left")
        ctk.CTkButton(top, text="测试每张网卡的公网 IP", width=200,
                      command=self.test_public_ips).pack(side="left", padx=8)
        self.nic_detail = ctk.CTkScrollableFrame(tab)
        self.nic_detail.pack(fill="both", expand=True, pady=8)

    def _build_diag(self, tab):
        top = ctk.CTkFrame(tab, fg_color="transparent")
        top.pack(fill="x")
        ctk.CTkButton(top, text="开始自检", width=120, command=self.run_diagnose).pack(side="left")
        ctk.CTkLabel(top, text="会测试网卡、本地代理，并用记事本验证注入是否会把进程打崩。",
                     font=self.font_small, text_color="gray").pack(side="left", padx=10)
        self.diag_box = ctk.CTkTextbox(tab, font=ctk.CTkFont(family="Consolas", size=13))
        self.diag_box.pack(fill="both", expand=True, pady=8)

    def _build_help(self, tab):
        box = ctk.CTkTextbox(tab, font=self.font)
        box.pack(fill="both", expand=True, pady=8)
        box.insert("1.0", HELP_TEXT)
        box.configure(state="disabled")

    def _settings(self):
        return self.config_data.setdefault("settings", _apply_setting_defaults({}))

    def _build_settings(self, tab):
        s = self._settings()
        wrap = ctk.CTkFrame(tab, fg_color="transparent")
        wrap.pack(fill="both", expand=True, padx=8, pady=12)

        self.var_tray = ctk.BooleanVar(value=bool(s.get("minimize_to_tray", True)))
        self.var_auto = ctk.BooleanVar(value=bool(s.get("auto_refresh", True)))
        self.var_boot = ctk.BooleanVar(value=bool(s.get("start_with_windows", False) or is_start_with_windows()))
        self.var_nic_launch = ctk.BooleanVar(value=bool(s.get("auto_launch_on_nic", True)))
        self.var_kill_down = ctk.BooleanVar(value=bool(s.get("kill_on_nic_down", True)))
        self.var_wait_nic = ctk.BooleanVar(value=bool(s.get("launch_wait_nic", True)))
        self.var_iso_browser = ctk.BooleanVar(value=bool(s.get("isolated_browser_profile", True)))

        ctk.CTkCheckBox(wrap, text="关闭窗口时最小化到托盘（托盘图标退出才真正关掉）",
                        variable=self.var_tray, command=self._save_settings).pack(anchor="w", pady=6)
        ctk.CTkCheckBox(wrap, text="自动刷新网卡（约 20 秒，网卡插拔后不用手点刷新）",
                        variable=self.var_auto, command=self._save_settings).pack(anchor="w", pady=6)
        ctk.CTkCheckBox(wrap, text="开机自动启动（启动后按规则自动拉起勾了「自动启动」的软件）",
                        variable=self.var_boot, command=self._toggle_autostart).pack(anchor="w", pady=6)
        ctk.CTkCheckBox(wrap, text="网卡重新连上后，自动启动绑在这张卡上、且当时没在运行的软件",
                        variable=self.var_nic_launch, command=self._save_settings).pack(anchor="w", pady=6)
        ctk.CTkCheckBox(wrap, text="网卡掉线时结束绑在该卡上的软件，防止 WorkBuddy/VPN 改走 Wi-Fi",
                        variable=self.var_kill_down, command=self._save_settings).pack(anchor="w", pady=6)
        ctk.CTkCheckBox(wrap, text="自动启动时先等网卡拿到 IPv4（最多 90 秒），避免开机 DHCP 没完成",
                        variable=self.var_wait_nic, command=self._save_settings).pack(anchor="w", pady=6)
        ctk.CTkCheckBox(wrap, text="浏览器用独立配置目录（默认；不关掉你正在用的 Chrome）",
                        variable=self.var_iso_browser, command=self._save_settings).pack(anchor="w", pady=6)

        ctk.CTkLabel(wrap, text="快捷方式", font=self.font_h).pack(anchor="w", pady=(18, 6))
        ctk.CTkButton(wrap, text="在桌面创建「网口分流」快捷方式", width=320,
                      command=self.make_desktop_shortcut).pack(anchor="w", pady=4)
        ctk.CTkButton(wrap, text="为每条规则创建桌面快捷方式（软件名＋网卡）", width=320,
                      fg_color="#7c3aed", command=self.make_all_rule_shortcuts).pack(anchor="w", pady=4)
        ctk.CTkLabel(wrap, text="规则快捷方式例如：WorkBuddy（有线网）、抖音（无线网）。双击即按规则启动。",
                     font=self.font_small, text_color="gray").pack(anchor="w")
        ctk.CTkLabel(wrap, text="F5 刷新网卡。再开一次程序会把命令交给已有窗口，不会重复开。",
                     font=self.font_small, text_color="gray").pack(anchor="w", pady=(8, 0))

    def _save_settings(self):
        s = self._settings()
        mapping = (
            ("var_tray", "minimize_to_tray"),
            ("var_auto", "auto_refresh"),
            ("var_boot", "start_with_windows"),
            ("var_nic_launch", "auto_launch_on_nic"),
            ("var_kill_down", "kill_on_nic_down"),
            ("var_wait_nic", "launch_wait_nic"),
            ("var_iso_browser", "isolated_browser_profile"),
        )
        for attr, key in mapping:
            var = getattr(self, attr, None)
            if var is None:
                continue
            s[key] = bool(var.get())
        save_config(self.config_data)

    def _toggle_autostart(self):
        enabled = bool(self.var_boot.get())
        try:
            path = set_start_with_windows(enabled)
            self._save_settings()
            if enabled:
                self.log("已写入开机启动：%s" % path)
            else:
                self.log("已取消开机启动")
        except Exception as exc:
            self.var_boot.set(not enabled)
            messagebox.showerror(APP_NAME, "设置开机启动失败：%s" % exc)

    def make_desktop_shortcut(self):
        try:
            created = create_desktop_shortcuts(run_as_admin=False)
            self.log("已创建桌面快捷方式：%s" % " ； ".join(created))
            messagebox.showinfo(APP_NAME, "已在桌面创建「网口分流」快捷方式。\n请用这个图标打开（不要选以管理员运行），才能把桌面应用拖进来。")
        except Exception as exc:
            messagebox.showerror(APP_NAME, "创建快捷方式失败：%s" % exc)

    def make_all_rule_shortcuts(self):
        rules = self.config_data.get("rules") or []
        if not rules:
            messagebox.showinfo(APP_NAME, "还没有规则。请先添加软件。")
            return
        try:
            created = create_all_rule_shortcuts(rules)
            self.log("已创建 %d 个规则快捷方式" % len(created))
            for p in created:
                self.log("  " + p)
            messagebox.showinfo(
                APP_NAME,
                "已在桌面创建 %d 个快捷方式，例如「WorkBuddy（有线网）」。\n"
                "以后请用这些图标打开对应软件。" % len(created),
            )
        except Exception as exc:
            messagebox.showerror(APP_NAME, "创建规则快捷方式失败：%s" % exc)

    def make_one_rule_shortcut(self, rule):
        try:
            path = create_rule_shortcut(rule)
            self.log("已创建快捷方式：%s" % path)
            messagebox.showinfo(APP_NAME, "已放到桌面：\n%s" % os.path.basename(path))
        except Exception as exc:
            messagebox.showerror(APP_NAME, "创建快捷方式失败：%s" % exc)

    def log(self, msg):
        def _append():
            try:
                if not self.winfo_exists():
                    return
                self.log_box.configure(state="normal")
                self.log_box.insert("end", msg + "\n")
                self.log_box.see("end")
                self.log_box.configure(state="disabled")
            except Exception:
                pass
        try:
            if threading.current_thread() is threading.main_thread():
                _append()
            else:
                self.after(0, _append)
        except Exception:
            pass

    def refresh_adapters(self, silent=False):
        try:
            self.adapters = usable_adapters()
            all_nics = list_adapters(include_down=True, include_loopback=False)
        except Exception as exc:
            if not silent:
                self.log("读取网卡失败：%s" % exc)
            self.adapters = []
            all_nics = []
        sig = tuple(
            (a.get("guid"), a.get("up"), tuple(a.get("ipv4") or []), a.get("network_name") or "")
            for a in self.adapters
        )
        changed = sig != self._nic_sig
        self._nic_sig = sig
        if not silent or changed:
            self._render_nic_cards()
            self._render_nic_details(all_nics)
            self.render_rules()
        new_up = set(
            a.get("guid") for a in self.adapters
            if a.get("up") and a.get("ipv4") and a.get("guid")
        )
        appeared = new_up - self._up_guids
        disappeared = self._up_guids - new_up
        if self._boot_done and disappeared and self._settings().get("kill_on_nic_down", True):
            for guid in disappeared:
                self._kill_for_guid(guid)
        if self._boot_done and appeared and self._settings().get("auto_launch_on_nic", True):
            for guid in appeared:
                self._auto_launch_for_guid(guid)
        self._up_guids = new_up
        if not self._boot_done:
            self._boot_done = True
        if silent and not changed:
            return
        up = [a for a in self.adapters if a.get("up") and a.get("ipv4")]
        if len(up) < 2:
            self.log("当前已连接且有 IPv4 的网卡不足 2 张。请同时连接有线网和无线网（或 VPN）后再刷新。")
        else:
            names = "、".join("%s(%s)" % (a.get("network_name") or a["name"], a["kind_label"]) for a in up)
            self.log("检测到 %d 张可用网卡：%s" % (len(up), names))

    def _render_nic_cards(self):
        for w in self.nic_bar.winfo_children():
            w.destroy()
        if not self.adapters:
            ctk.CTkLabel(self.nic_bar, text="没有可用网卡。请连接网络后点「刷新网卡」。",
                         text_color="#f59e0b", font=self.font).pack(anchor="w")
            return
        for a in self.adapters:
            color = KIND_COLOR.get(a["kind"], "#94a3b8")
            card = ctk.CTkFrame(self.nic_bar, fg_color=("#ffffff", "#1a2332"), corner_radius=10)
            card.pack(side="left", padx=(0, 10), pady=4, ipadx=4)
            bar = ctk.CTkFrame(card, width=6, fg_color=color, corner_radius=3)
            bar.pack(side="left", fill="y", padx=(6, 8), pady=8)
            body = ctk.CTkFrame(card, fg_color="transparent")
            body.pack(side="left", padx=(0, 12), pady=8)
            ctk.CTkLabel(body, text=a["name"], font=self.font_h, anchor="w").pack(anchor="w")
            ip = (a.get("ipv4") or ["无 IPv4"])[0]
            gw = (a.get("gateway") or ["-"])[0]
            line = "%s    %s    网关 %s" % (a["kind_label"], ip, gw)
            ctk.CTkLabel(body, text=line, font=self.font_small, text_color="gray", anchor="w").pack(anchor="w")
            pub = self._adapter_pub.get(a.get("guid"))
            status = a["oper_label"] if a.get("ipv4") else a["oper_label"] + "（缺 IPv4）"
            if pub:
                status = status + "    公网 " + pub
            ctk.CTkLabel(body, text=status, font=self.font_small, text_color=color, anchor="w").pack(anchor="w")

    def _render_nic_details(self, all_nics):
        for w in self.nic_detail.winfo_children():
            w.destroy()
        for a in all_nics:
            color = KIND_COLOR.get(a["kind"], "#94a3b8")
            card = ctk.CTkFrame(self.nic_detail, fg_color=("#ffffff", "#1a2332"))
            card.pack(fill="x", pady=6)
            ctk.CTkLabel(card, text=a["name"], font=self.font_h, text_color=color).pack(anchor="w", padx=12, pady=(8, 0))
            lines = [
                "类型：%s    状态：%s    接口序号 ifIndex=%s" % (a["kind_label"], a["oper_label"], a["if_index"]),
                "描述：%s" % a["description"],
                "IPv4：%s" % (", ".join(a["ipv4"]) or "无"),
                "网关：%s" % (", ".join(a["gateway"]) or "无"),
                "DNS：%s" % (", ".join(a["dns"]) or "无"),
                "MAC：%s    速率：%s Mbps    MTU：%s" % (a["mac"] or "-", a["speed_mbps"] or "-", a["mtu"]),
                "GUID：%s" % a["guid"],
            ]
            ctk.CTkLabel(card, text="\n".join(lines), font=self.font_small, justify="left",
                         anchor="w").pack(anchor="w", padx=12, pady=(2, 10))

    def render_rules(self):
        if getattr(self, "_advanced", False):
            self._render_rule_table()
        elif hasattr(self, "simple_board"):
            self.simple_board.refresh()

    def _render_rule_table(self):
        if not hasattr(self, "rule_box"):
            return
        for w in self.rule_box.winfo_children():
            w.destroy()
        rules = self.config_data.get("rules") or []
        if not rules:
            ctk.CTkLabel(self.rule_box, text="还没有规则。点右上角「添加软件」，选择 exe 并指定网卡。",
                         font=self.font, text_color="gray").pack(pady=24)
            return
        header = ctk.CTkFrame(self.rule_box, fg_color="transparent")
        header.pack(fill="x", pady=(0, 4))
        for text, width in (("软件", 160), ("网卡", 170), ("模式", 80), ("状态", 60), ("出口 IP", 130)):
            ctk.CTkLabel(header, text=text, width=width, anchor="w",
                         font=self.font_small, text_color="gray").pack(side="left")

        for rule in rules:
            self._rule_row(rule)

    def _rule_row(self, rule):
        row = ctk.CTkFrame(self.rule_box, fg_color=("#ffffff", "#1a2332"), corner_radius=8)
        row.pack(fill="x", pady=3)
        adapter = find_adapter(
            self.adapters,
            guid=rule.get("adapter_guid"),
            name=rule.get("adapter_name"),
            kind=rule.get("adapter_kind"),
        )
        if adapter:
            nic_text = "%s  (%s)" % (adapter["name"], adapter["kind_label"])
            nic_color = KIND_COLOR.get(adapter["kind"], "gray")
        else:
            nic_text = "%s  （当前未连接）" % (rule.get("adapter_name") or "未知网卡")
            nic_color = "#f59e0b"

        ctk.CTkLabel(row, text=rule.get("name") or os.path.basename(rule.get("exe") or ""),
                     width=160, anchor="w", font=self.font_h).pack(side="left", padx=(10, 0), pady=10)
        ctk.CTkLabel(row, text=nic_text, width=170, anchor="w", font=self.font,
                     text_color=nic_color).pack(side="left")
        ctk.CTkLabel(row, text=MODE_LABELS.get(rule.get("mode") or "auto", "自动"),
                     width=80, anchor="w", font=self.font).pack(side="left")
        running = is_rule_running(rule)
        ctk.CTkLabel(row, text="运行中" if running else "未运行", width=60, anchor="w",
                     font=self.font_small, text_color="#22c55e" if running else "gray").pack(side="left")
        info = self._egress.get(rule.get("id") or "")
        if info and info.get("ip"):
            egress_text, egress_color = info["ip"], "#38bdf8"
        elif info and info.get("error"):
            egress_text, egress_color = "未测到", "#f59e0b"
        else:
            egress_text, egress_color = "—", "gray"
        ctk.CTkLabel(row, text=egress_text, width=130, anchor="w",
                     font=self.font_small, text_color=egress_color).pack(side="left")

        btns = ctk.CTkFrame(row, fg_color="transparent")
        btns.pack(side="right", padx=8)
        ctk.CTkButton(btns, text="启动", width=64, command=lambda r=rule: self.start_rule(r)).pack(side="left", padx=2)
        ctk.CTkButton(btns, text="快捷方式", width=78, fg_color="#7c3aed", hover_color="#5b21b6",
                      command=lambda r=rule: self.make_one_rule_shortcut(r)).pack(side="left", padx=2)
        ctk.CTkButton(btns, text="编辑", width=52, fg_color="gray",
                      command=lambda r=rule: self.edit_rule(r)).pack(side="left", padx=2)
        ctk.CTkButton(btns, text="删除", width=52, fg_color="#b91c1c", hover_color="#7f1d1d",
                      command=lambda r=rule: self.delete_rule(r)).pack(side="left", padx=2)

    def persist(self):
        save_config(self.config_data)
        self.render_rules()

    def add_rule(self):
        if not self.adapters:
            messagebox.showwarning(APP_NAME, "没有可用网卡，请先连接至少一张网卡并刷新。")
            return
        RuleEditor(self, self.adapters, new_rule(), on_save=self._save_new)

    def _save_new(self, rule):
        self.config_data.setdefault("rules", []).append(rule)
        self.persist()
        self.log("已添加规则：%s → %s" % (rule["name"], rule["adapter_name"]))

    def edit_rule(self, rule):
        if not self.adapters:
            messagebox.showwarning(APP_NAME, "没有可用网卡，无法编辑。")
            return

        def on_save(updated):
            for i, r in enumerate(self.config_data.get("rules") or []):
                if r.get("id") == updated.get("id"):
                    self.config_data["rules"][i] = updated
                    break
            self.persist()
            self.log("已更新规则：%s" % updated["name"])

        RuleEditor(self, self.adapters, rule, on_save=on_save)

    def delete_rule(self, rule):
        if not messagebox.askyesno(APP_NAME, "删除规则「%s」？" % (rule.get("name") or "")):
            return
        self.config_data["rules"] = [r for r in self.config_data.get("rules") or [] if r.get("id") != rule.get("id")]
        self.persist()
        self.log("已删除规则：%s" % rule.get("name"))

    def add_from_process(self):
        if not self.adapters:
            messagebox.showwarning(APP_NAME, "没有可用网卡。")
            return

        def on_pick(row):
            rule = new_rule(
                name=os.path.splitext(row["name"])[0],
                exe=row["exe"],
                mode=guess_mode(row["exe"]),
            )
            RuleEditor(self, self.adapters, rule, on_save=self._save_new)

        ProcessPicker(self, on_pick)

    def _resolve_adapter(self, rule):
        return find_adapter(
            self.adapters,
            guid=rule.get("adapter_guid"),
            name=rule.get("adapter_name"),
            kind=rule.get("adapter_kind"),
        )

    def _launch_one(self, rule):
        adapter = self._resolve_adapter(rule)
        if not adapter or not adapter.get("up") or not adapter.get("ipv4"):
            raise RuntimeError("规则「%s」指定的网卡当前不可用。请连接该网卡后刷新。" % rule.get("name"))
        self.log("正在启动 %s …" % rule.get("name"))
        if rule.get("isolated_profile") is None:
            rule = dict(rule)
            rule["isolated_profile"] = bool(self._settings().get("isolated_browser_profile", True))
        pid, method = launch_app(rule, adapter, self.proxy_pool, log=self.log)
        self.log("已启动 %s  PID %s  %s" % (rule.get("name"), pid, method))
        self._probe_egress(rule, adapter)
        return pid

    def _probe_egress(self, rule, adapter):
        rid = rule.get("id") or ""
        bind_ip = (adapter.get("ipv4") or [None])[0]
        if_index = adapter.get("if_index")
        name = rule.get("name") or rid

        def work():
            try:
                pub = public_ip_via(bind_ip, if_index)
                self._egress[rid] = {"ip": pub, "adapter": adapter.get("name")}
                if adapter.get("guid"):
                    self._adapter_pub[adapter["guid"]] = pub
                self.log("  %s 实际出口 %s（经 %s %s）" % (
                    name, pub, adapter.get("kind_label"), adapter.get("name")))
            except Exception as exc:
                self._egress[rid] = {"ip": None, "error": str(exc)}
                self.log("  %s 出口探测失败：%s" % (name, exc))
            self.after(0, self.render_rules)

        threading.Thread(target=work, daemon=True).start()

    def start_rule(self, rule, quiet=False):
        self._queue.append((rule, quiet))
        self._kick_queue()

    def start_all(self, only_auto=False, skip_running=False, quiet=False):
        rules = []
        for r in self.config_data.get("rules") or []:
            if not r.get("enabled", True):
                continue
            if only_auto and not r.get("auto_launch", True):
                continue
            if skip_running and is_rule_running(r):
                self.log("跳过已在运行：%s" % r.get("name"))
                continue
            rules.append(r)
        if not rules:
            if not quiet:
                messagebox.showinfo(APP_NAME, "没有可启动的规则。")
            return
        if not is_admin():
            self.log("未提权批量启动：网卡绑定类规则可能失败。")
        for r in rules:
            self.start_rule(r, quiet=quiet)

    def _kick_queue(self):
        if self._busy or not self._queue:
            return
        wait_enabled = bool(self._settings().get("launch_wait_nic", True))
        limit = float(self._settings().get("launch_wait_seconds") or 90)
        now = time.time()
        deferred = []
        launched = False
        while self._queue and not launched:
            rule, quiet = self._queue.pop(0)
            adapter = self._resolve_adapter(rule)
            if (not adapter or not adapter.get("up") or not adapter.get("ipv4")) and quiet and wait_enabled:
                try:
                    self.adapters = usable_adapters()
                except Exception:
                    pass
                adapter = self._resolve_adapter(rule)
            if not adapter or not adapter.get("up") or not adapter.get("ipv4"):
                rid = rule.get("id") or rule.get("name") or ""
                if quiet and wait_enabled:
                    first = self._wait_since.get(rid, now)
                    self._wait_since[rid] = first
                    if now - first < limit:
                        deferred.append((rule, quiet))
                        continue
                    self._wait_since.pop(rid, None)
                msg = "规则「%s」指定的网卡当前不可用。" % rule.get("name")
                self.log(msg)
                if not quiet:
                    messagebox.showerror(APP_NAME, msg + "请连接该网卡后刷新。")
                continue
            self._wait_since.pop(rule.get("id") or rule.get("name") or "", None)
            mode = rule.get("mode") or "auto"
            resolved = mode if mode != "auto" else guess_mode(rule.get("exe") or "")
            if not is_admin() and resolved == "bind":
                self.log("未提权：仍尝试网卡绑定。若启动失败，请点右上角「获取管理员权限」。")

            def work(rule=rule, quiet=quiet):
                self._busy = True
                try:
                    self._launch_one(rule)
                except Exception as exc:
                    self.log("启动失败：%s" % exc)
                    err = str(exc)
                    if not quiet:
                        self.after(0, lambda: messagebox.showerror(APP_NAME, "启动失败：\n%s" % err))
                finally:
                    self._busy = False
                    self.after(80, self._kick_queue)

            threading.Thread(target=work, daemon=True).start()
            launched = True
        self._queue = deferred + self._queue
        if deferred and not launched:
            names = "、".join((r.get("name") or "") for r, _q in deferred)
            self.log("等待网卡就绪：%s（最多 %.0f 秒）…" % (names, limit))
            self.after(2000, self._kick_queue)

    def _find_rule(self, rule_id):
        for r in self.config_data.get("rules") or []:
            if r.get("id") == rule_id:
                return r
        return None

    def _auto_launch_for_guid(self, guid):
        nic = None
        for a in self.adapters:
            if a.get("guid") == guid:
                nic = a
                break
        self.log("网卡恢复：%s，检查自动启动规则…" % ((nic or {}).get("name") or guid))
        for rule in self.config_data.get("rules") or []:
            if not rule.get("enabled", True) or not rule.get("auto_launch", True):
                continue
            adapter = self._resolve_adapter(rule)
            if not adapter or adapter.get("guid") != guid:
                continue
            if is_rule_running(rule):
                self.log("  %s 已在运行，跳过" % rule.get("name"))
                continue
            self.log("  自动启动 %s" % rule.get("name"))
            self.start_rule(rule, quiet=True)

    def _kill_for_guid(self, guid):
        nic_name = guid
        for a in list_adapters(include_down=True, include_loopback=False):
            if a.get("guid") == guid:
                nic_name = a.get("name") or guid
                break
        stopped = []
        for rule in self.config_data.get("rules") or []:
            if not rule.get("kill_on_down", True):
                continue
            if rule.get("adapter_guid") != guid:
                continue
            exe = rule.get("exe") or ""
            if not exe or not is_rule_running(rule):
                continue
            try:
                killed = stop_rule_processes(rule)
            except Exception as exc:
                self.log("结束 %s 失败：%s" % (rule.get("name"), exc))
                continue
            if killed:
                stopped.append(rule.get("name") or os.path.basename(exe))
                self._egress[rule.get("id") or ""] = {"ip": None, "error": "网卡已掉线"}
        if stopped:
            msg = "网卡「%s」掉线，已停止：%s（防止改走别的网）" % (nic_name, "、".join(stopped))
            self.log(msg)
            self._tray_notify("网口分流", msg)
            self.render_rules()

    def _tray_notify(self, title, message):
        try:
            if self._tray:
                self._tray.notify(message, title)
        except Exception:
            pass

    def _run_pending(self):
        cmds = list(self._pending_cmds)
        self._pending_cmds = []
        self._apply_cmds(cmds)

    def _apply_cmds(self, cmds):
        for cmd in cmds:
            action = (cmd or {}).get("action")
            if action == "launch-all":
                self.log("收到命令：按规则自动启动")
                self.start_all(only_auto=True, skip_running=True, quiet=True)
            elif action == "launch":
                rid = cmd.get("id")
                rule = self._find_rule(rid)
                if not rule:
                    self.log("找不到规则 id=%s" % rid)
                    continue
                self.log("收到命令：启动 %s" % rule.get("name"))
                if not self._start_minimized:
                    self.show_from_tray()
                self.start_rule(rule, quiet=True)

    def _poll_ipc(self):
        if self._quitting:
            return
        try:
            cmds = drain_ipc()
            if cmds:
                self._apply_cmds(cmds)
        except Exception:
            pass
        if not self._quitting:
            self.after(700, self._poll_ipc)

    def test_public_ips(self):
        nics = [a for a in self.adapters if a.get("up") and a.get("ipv4")]
        if not nics:
            messagebox.showinfo(APP_NAME, "没有已连接且有 IPv4 的网卡。")
            return
        self.log("开始测试每张网卡的公网 IP…")

        def work():
            for a in nics:
                ip = a["ipv4"][0]
                try:
                    pub = public_ip_via(ip, a["if_index"])
                    self._adapter_pub[a.get("guid")] = pub
                    self.log("  %s (%s, %s)  公网 IP = %s" % (a["name"], a["kind_label"], ip, pub))
                except Exception as exc:
                    self.log("  %s (%s, %s)  测试失败：%s" % (a["name"], a["kind_label"], ip, exc))
            self.log("公网 IP 测试结束。两张网卡如果公网 IP 不同，说明分流有物理基础。")
            self.after(0, self._render_nic_cards)

        threading.Thread(target=work, daemon=True).start()

    def _warn_if_needed(self):
        if not is_admin():
            self.log("当前是普通权限，可以从桌面拖入图标。网卡绑定失败时再点右上角「管理员」。")
        hook = dll_path()
        if not hook:
            self.log("未找到 BindHook.dll：网卡绑定模式不可用，浏览器代理模式仍可使用。运行 build.ps1 可编译该模块。")
        else:
            self.log("绑定模块：%s" % hook)
        if is_start_with_windows():
            try:
                set_start_with_windows(True)
            except Exception:
                pass

    def run_diagnose(self):
        self.tabs.set("诊断")
        self.diag_box.delete("1.0", "end")
        self.diag_box.insert("end", "正在自检，请稍等…\n")
        self.log("开始自检…")

        def work():
            try:
                report = run_selftest(include_inject=True)
            except Exception:
                report = traceback.format_exc()
            def show():
                try:
                    self.diag_box.delete("1.0", "end")
                    self.diag_box.insert("end", report)
                    self.log("自检结束，请查看「诊断」页。")
                except Exception:
                    pass
            self.after(0, show)

        threading.Thread(target=work, daemon=True).start()

    def _schedule_auto_refresh(self):
        if self._quitting:
            return
        try:
            if self._settings().get("auto_refresh", True):
                self.refresh_adapters(silent=True)
        except Exception:
            pass
        if not self._quitting:
            interval = 3000 if (time.time() - self._started_at) < 120 else 20000
            self.after(interval, self._schedule_auto_refresh)

    def _start_tray(self):
        try:
            import pystray
            from PIL import Image
            icon_path = os.path.join(HERE, "assets", "icon.ico")
            try:
                image = Image.open(icon_path) if os.path.isfile(icon_path) else Image.new("RGB", (64, 64), (59, 130, 246))
            except Exception:
                image = Image.new("RGB", (64, 64), (59, 130, 246))
            menu = pystray.Menu(
                pystray.MenuItem("打开主窗口", lambda: self.after(0, self.show_from_tray), default=True),
                pystray.MenuItem("启动全部规则", lambda: self.after(0, self.start_all)),
                pystray.MenuItem("刷新网卡", lambda: self.after(0, self.refresh_adapters)),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("退出", lambda: self.after(0, self.quit_app)),
            )
            self._tray = pystray.Icon("SplitNIC", image, "网口分流", menu)
            self._tray.run_detached()
        except ImportError:
            self.log("未安装 pystray，托盘不可用。可执行：python -m pip install pystray")
            self._tray = None
        except Exception as exc:
            self.log("托盘启动失败：%s" % exc)
            self._tray = None

    def show_from_tray(self):
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        except Exception:
            pass

    def on_close(self):
        if not self._quitting and self._settings().get("minimize_to_tray", True) and self._tray:
            self.root.withdraw()
            self.log("已最小化到托盘。要退出请右键托盘图标选「退出」。")
            return
        self.quit_app()

    def quit_app(self):
        self._quitting = True
        try:
            if self._tray:
                self._tray.stop()
        except Exception:
            pass
        try:
            self.proxy_pool.stop_all()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass


def parse_cli(argv):
    launch_ids = []
    launch_all = False
    minimized = False
    args = list(argv)
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--launch" and i + 1 < len(args):
            launch_ids.append(args[i + 1])
            i += 2
            continue
        if a == "--launch-all":
            launch_all = True
            i += 1
            continue
        if a == "--minimized":
            minimized = True
            i += 1
            continue
        if a in ("--elevated", "--keep-admin"):
            i += 1
            continue
        i += 1
    cmds = []
    if launch_all:
        cmds.append({"action": "launch-all"})
    for rid in launch_ids:
        cmds.append({"action": "launch", "id": rid})
    return cmds, minimized


def main():
    cmds, minimized = parse_cli(sys.argv[1:])
    # Explorer cannot drop files onto an elevated window (UIPI → 🚫).
    # If this process was started "as admin" by the old shortcut, restart
    # at normal integrity unless the user explicitly clicked 管理员.
    if (
        is_admin()
        and "--elevated" not in sys.argv
        and "--keep-admin" not in sys.argv
        and "--selftest" not in sys.argv
    ):
        try:
            create_desktop_shortcuts(run_as_admin=False)
        except Exception:
            pass
        for cmd in cmds:
            post_ipc(cmd)
        if spawn_unelevated_self(sys.argv[1:]):
            return
    if not ensure_single_instance():
        for cmd in cmds:
            post_ipc(cmd)
        if not minimized:
            bring_existing_to_front()
        return
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")
    if HAS_DND:
        root = TkinterDnD.Tk()
    else:
        import tkinter as tk
        root = tk.Tk()
    root.title("%s  %s" % (APP_NAME, APP_NAME_EN))
    root.geometry("1280x760")
    root.minsize(980, 620)
    root.configure(bg="#0b0e14")
    icon_path = os.path.join(HERE, "assets", "icon.ico")
    if os.path.isfile(icon_path):
        try:
            root.iconbitmap(icon_path)
        except Exception:
            pass
    app = SplitNICApp(root, pending_cmds=cmds, start_minimized=minimized)
    app.pack(fill="both", expand=True)
    if HAS_DND:
        from dropfiles import bind_drop
        bind_drop(root, app._on_tk_drop)
        bind_drop(app, app._on_tk_drop)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    if minimized:
        root.withdraw()
    else:
        root.deiconify()
        root.lift()
    root.mainloop()


def write_error_log(text):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        path = os.path.join(CONFIG_DIR, "error.log")
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n----\n")
            f.write(text)
            f.write("\n")
        return path
    except Exception:
        return None


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
        print(run_selftest())
        sys.exit(0)
    try:
        main()
    except Exception:
        err = traceback.format_exc()
        traceback.print_exc()
        write_error_log(err)
        try:
            messagebox.showerror(APP_NAME, err)
        except Exception:
            pass
        sys.exit(1)
