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

from adapters import usable_adapters, list_adapters, find_adapter, public_ip_via, KIND_LABELS
from socks_proxy import ProxyPool
from launcher import launch_app, list_running_processes, dll_path, guess_mode

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
1. 先用管理员身份打开本程序（绑定网卡需要管理员权限）。
2. 确认顶部「可用网卡」里至少有 2 张已连接、有 IPv4 的网卡。
3. 点「添加软件」，选 exe，再选要走的网卡。
4. 一定要从本程序点「启动」。从桌面图标或开始菜单直接打开，不会走你指定的网卡。
5. 浏览器、抖音这类程序建议模式选「自动」或「浏览器代理」；WorkBuddy、VPN 客户端选「网卡绑定」。

【启动模式】
  · 自动：浏览器走本地代理，其它程序尝试网卡绑定（注入 BindHook.dll）。
  · 网卡绑定：把程序的网络连接绑到指定网卡的 IP / 接口（适合多数 Win32 软件、VPN 客户端）。
  · 浏览器代理：在本机起一个只从该网卡出站的 SOCKS5/HTTP 代理，再把浏览器指过去（适合 Chrome / Edge / Firefox / 抖音）。
  · 普通启动：不分流，只是替你打开程序。

【必须知道的限制】
  · 微软商店 UWP 应用无法分流。
  · 带反作弊的游戏往往会拒绝 DLL 注入，请不要对这类程序使用「网卡绑定」。
  · Chrome / Edge / 抖音 是单实例程序：启动前请勾选「先关闭已运行的同名进程」，否则新进程只会附到旧进程上，代理参数无效。
  · Firefox 代理模式会使用独立配置目录，和你日常的书签/登录不是同一套。
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
    params = " ".join('"%s"' % a if " " in a else a for a in sys.argv)
    if getattr(sys, "frozen", False):
        exe = sys.executable
        args = " ".join('"%s"' % a if " " in a else a for a in sys.argv[1:])
    else:
        exe = sys.executable
        args = '"%s" %s' % (os.path.abspath(sys.argv[0]), " ".join(sys.argv[1:]))
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, args, None, 1)
    return rc > 32


def load_config():
    if not os.path.isfile(CONFIG_FILE):
        return {"rules": []}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"rules": []}
        data.setdefault("rules", [])
        return data
    except Exception:
        return {"rules": []}


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
        self.geometry("620x560")
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
                        variable=self.var_close).pack(anchor="w", padx=18, pady=14)

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
        })
        self.on_save(self.rule)
        self.destroy()


class SplitNICApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("%s  %s" % (APP_NAME, APP_NAME_EN))
        self.geometry("1180x780")
        self.minsize(980, 640)
        self.configure(fg_color=("#f4f6fb", "#0f1419"))
        icon_path = os.path.join(HERE, "assets", "icon.ico")
        if os.path.isfile(icon_path):
            try:
                self.iconbitmap(icon_path)
            except Exception:
                pass

        self.config_data = load_config()
        self.adapters = []
        self.proxy_pool = ProxyPool(log=self.log)
        self._busy = False

        self.font_title = ctk.CTkFont(family="Microsoft YaHei UI", size=22, weight="bold")
        self.font_h = ctk.CTkFont(family="Microsoft YaHei UI", size=15, weight="bold")
        self.font = ctk.CTkFont(family="Microsoft YaHei UI", size=13)
        self.font_small = ctk.CTkFont(family="Microsoft YaHei UI", size=12)

        self._build()
        self.refresh_adapters()
        self.render_rules()
        self.after(200, self._warn_if_needed)

    def _build(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=22, pady=(16, 6))
        ctk.CTkLabel(header, text=APP_NAME, font=self.font_title).pack(side="left")
        ctk.CTkLabel(header, text="  按软件选择走有线网还是无线网",
                     font=self.font, text_color="gray").pack(side="left", padx=(8, 0), pady=(8, 0))

        self.admin_pill = ctk.CTkLabel(header, text="", font=self.font_small, width=140)
        self.admin_pill.pack(side="right")
        self._set_admin_pill()

        self.tabs = ctk.CTkTabview(self)
        self.tabs.pack(fill="both", expand=True, padx=18, pady=(0, 8))
        self.tab_main = self.tabs.add("分流")
        self.tab_nics = self.tabs.add("网卡详情")
        self.tab_help = self.tabs.add("使用说明与注意事项")

        self._build_main(self.tab_main)
        self._build_nics(self.tab_nics)
        self._build_help(self.tab_help)

        log_wrap = ctk.CTkFrame(self)
        log_wrap.pack(fill="x", padx=18, pady=(0, 14))
        ctk.CTkLabel(log_wrap, text="运行日志", font=self.font_h).pack(anchor="w", padx=10, pady=(8, 0))
        self.log_box = ctk.CTkTextbox(log_wrap, height=120, font=self.font_small)
        self.log_box.pack(fill="x", padx=10, pady=(4, 10))
        self.log_box.configure(state="disabled")

    def _set_admin_pill(self):
        if is_admin():
            self.admin_pill.configure(text="管理员  已获得", text_color="#22c55e")
        else:
            self.admin_pill.configure(text="非管理员  部分功能不可用", text_color="#f59e0b")

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

        self.rule_box = ctk.CTkScrollableFrame(tab, height=280)
        self.rule_box.pack(fill="both", expand=True, pady=(4, 8))

        hint = (
            "示例：把 WorkBuddy、VPN 指到「有线网」，把抖音、浏览器指到「无线网」。"
            "必须从这里点启动，不要从桌面图标打开。"
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

    def _build_help(self, tab):
        box = ctk.CTkTextbox(tab, font=self.font)
        box.pack(fill="both", expand=True, pady=8)
        box.insert("1.0", HELP_TEXT)
        box.configure(state="disabled")

    def log(self, msg):
        def _append():
            self.log_box.configure(state="normal")
            self.log_box.insert("end", msg + "\n")
            self.log_box.see("end")
            self.log_box.configure(state="disabled")
        if threading.current_thread() is threading.main_thread():
            _append()
        else:
            self.after(0, _append)

    def refresh_adapters(self):
        try:
            self.adapters = usable_adapters()
            all_nics = list_adapters(include_down=True, include_loopback=False)
        except Exception as exc:
            self.log("读取网卡失败：%s" % exc)
            self.adapters = []
            all_nics = []
        self._render_nic_cards()
        self._render_nic_details(all_nics)
        up = [a for a in self.adapters if a.get("up") and a.get("ipv4")]
        if len(up) < 2:
            self.log("当前已连接且有 IPv4 的网卡不足 2 张。请同时连接有线网和无线网（或 VPN）后再刷新。")
        else:
            names = "、".join("%s(%s)" % (a["name"], a["kind_label"]) for a in up)
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
            status = a["oper_label"] if a.get("ipv4") else a["oper_label"] + "（缺 IPv4）"
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
        for w in self.rule_box.winfo_children():
            w.destroy()
        rules = self.config_data.get("rules") or []
        if not rules:
            ctk.CTkLabel(self.rule_box, text="还没有规则。点右上角「添加软件」，选择 exe 并指定网卡。",
                         font=self.font, text_color="gray").pack(pady=24)
            return
        header = ctk.CTkFrame(self.rule_box, fg_color="transparent")
        header.pack(fill="x", pady=(0, 4))
        for text, width in (("软件", 180), ("网卡", 220), ("模式", 110), ("路径", 360)):
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
                     width=180, anchor="w", font=self.font_h).pack(side="left", padx=(10, 0), pady=10)
        ctk.CTkLabel(row, text=nic_text, width=220, anchor="w", font=self.font,
                     text_color=nic_color).pack(side="left")
        ctk.CTkLabel(row, text=MODE_LABELS.get(rule.get("mode") or "auto", "自动"),
                     width=110, anchor="w", font=self.font).pack(side="left")
        ctk.CTkLabel(row, text=rule.get("exe") or "", width=360, anchor="w",
                     font=self.font_small, text_color="gray").pack(side="left")

        btns = ctk.CTkFrame(row, fg_color="transparent")
        btns.pack(side="right", padx=8)
        ctk.CTkButton(btns, text="启动", width=70, command=lambda r=rule: self.start_rule(r)).pack(side="left", padx=3)
        ctk.CTkButton(btns, text="编辑", width=60, fg_color="gray",
                      command=lambda r=rule: self.edit_rule(r)).pack(side="left", padx=3)
        ctk.CTkButton(btns, text="删除", width=60, fg_color="#b91c1c", hover_color="#7f1d1d",
                      command=lambda r=rule: self.delete_rule(r)).pack(side="left", padx=3)

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
        pid, method = launch_app(rule, adapter, self.proxy_pool, log=self.log)
        self.log("已启动 %s  PID %s  %s" % (rule.get("name"), pid, method))
        return pid

    def start_rule(self, rule):
        if self._busy:
            self.log("请等待当前启动完成。")
            return
        adapter = self._resolve_adapter(rule)
        if not adapter or not adapter.get("up") or not adapter.get("ipv4"):
            messagebox.showerror(APP_NAME, "规则「%s」指定的网卡当前不可用。请连接该网卡后刷新。" % rule.get("name"))
            return
        mode = rule.get("mode") or "auto"
        if not is_admin() and mode in ("auto", "bind"):
            if messagebox.askyesno(APP_NAME, "网卡绑定需要管理员权限。现在以管理员重新打开吗？\n（浏览器代理模式可以不提权）"):
                if relaunch_as_admin():
                    self.destroy()
                return

        def work():
            self._busy = True
            try:
                self._launch_one(rule)
            except Exception as exc:
                self.log("启动失败：%s" % exc)
                err = str(exc)
                self.after(0, lambda: messagebox.showerror(APP_NAME, "启动失败：\n%s" % err))
            finally:
                self._busy = False

        threading.Thread(target=work, daemon=True).start()

    def start_all(self):
        rules = [r for r in self.config_data.get("rules") or [] if r.get("enabled", True)]
        if not rules:
            messagebox.showinfo(APP_NAME, "没有可启动的规则。")
            return
        if self._busy:
            self.log("请等待当前启动完成。")
            return
        if not is_admin():
            if messagebox.askyesno(APP_NAME, "批量启动里如果包含网卡绑定，需要管理员权限。现在以管理员重新打开吗？"):
                if relaunch_as_admin():
                    self.destroy()
                return

        def work():
            self._busy = True
            try:
                import time
                for r in rules:
                    try:
                        self._launch_one(r)
                    except Exception as exc:
                        self.log("启动 %s 失败：%s" % (r.get("name"), exc))
                    time.sleep(0.6)
            finally:
                self._busy = False

        threading.Thread(target=work, daemon=True).start()

    def test_public_ips(self):
        nics = [a for a in self.adapters if a.get("up") and a.get("ipv4")]
        if not nics:
            messagebox.showinfo(APP_NAME, "没有已连接且有 IPv4 的网卡。")
            return
        self.log("开始测试每张网卡的公网 IP（访问 api.ipify.org）…")

        def work():
            for a in nics:
                ip = a["ipv4"][0]
                try:
                    pub = public_ip_via(ip, a["if_index"])
                    self.log("  %s (%s, %s)  公网 IP = %s" % (a["name"], a["kind_label"], ip, pub))
                except Exception as exc:
                    self.log("  %s (%s, %s)  测试失败：%s" % (a["name"], a["kind_label"], ip, exc))
            self.log("公网 IP 测试结束。两张网卡如果公网 IP 不同，说明分流有物理基础。")

        threading.Thread(target=work, daemon=True).start()

    def _warn_if_needed(self):
        if not is_admin():
            if messagebox.askyesno(
                APP_NAME,
                "当前不是管理员。\n\n"
                "「网卡绑定」WorkBuddy / VPN 需要管理员权限；\n"
                "浏览器代理模式可以不提权。\n\n"
                "要以管理员重新打开吗？",
            ):
                if relaunch_as_admin():
                    self.destroy()
                    return
        hook = dll_path()
        if not hook:
            self.log("未找到 BindHook.dll：网卡绑定模式不可用，浏览器代理模式仍可使用。运行 build.ps1 可编译该模块。")
        else:
            self.log("绑定模块：%s" % hook)

    def on_close(self):
        try:
            self.proxy_pool.stop_all()
        except Exception:
            pass
        self.destroy()


def main():
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    app = SplitNICApp()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        try:
            messagebox.showerror(APP_NAME, traceback.format_exc())
        except Exception:
            pass
        sys.exit(1)
