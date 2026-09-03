# -*- coding: utf-8 -*-
"""Simple drag-and-drop board: drop apps onto a network."""
from __future__ import print_function

import os
import tkinter as tk
import customtkinter as ctk

from icons import exe_icon, placeholder_icon
from launcher import is_rule_running

KIND_STYLE = {
    "wired": {"color": "#34d399", "title": "有线网", "hint": "适合 WorkBuddy、VPN"},
    "wifi": {"color": "#38bdf8", "title": "无线网", "hint": "适合抖音、浏览器"},
    "vpn": {"color": "#c4b5fd", "title": "VPN", "hint": "走隧道的软件拖到这里"},
    "virtual": {"color": "#fbbf24", "title": "虚拟网卡", "hint": "拖到这里使用这张卡"},
    "other": {"color": "#94a3b8", "title": "其他网卡", "hint": "拖到这里使用这张卡"},
}

BG_ZONE = "#141a22"
BG_ZONE_HOT = "#1c2633"
BG_TILE = "#1b2330"
BG_TILE_HOT = "#243044"


def _parse_drop_files(widget, data):
    files = []
    try:
        parts = widget.tk.splitlist(data)
    except Exception:
        parts = [data]
    for p in parts:
        p = (p or "").strip().strip("{}")
        if p.lower().endswith(".lnk"):
            try:
                import win32com.client  # optional
            except Exception:
                p = _resolve_lnk_powershell(p)
        if p and os.path.isfile(p) and p.lower().endswith(".exe"):
            files.append(p)
    return files


def _resolve_lnk_powershell(path):
    try:
        import subprocess
        ps = (
            "$s = New-Object -ComObject WScript.Shell; "
            "$s.CreateShortcut('%s').TargetPath" % path.replace("'", "''")
        )
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-STA", "-Command", ps],
            stderr=subprocess.DEVNULL,
        )
        target = out.decode("utf-8", "ignore").strip()
        return target
    except Exception:
        return ""


class SimpleBoard(ctk.CTkFrame):
    def __init__(self, master, controller):
        super().__init__(master, fg_color="transparent")
        self.ctrl = controller
        self._zones = {}
        self._drag = None
        self._ghost = None
        self._icon_cache = {}
        self._hot_guid = None

        self.hint = ctk.CTkLabel(
            self,
            text="把软件拖到要用的网络上  ·  点图标启动  ·  拖到另一张网就换线路",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=14),
            text_color="#8b9bb4",
        )
        self.hint.pack(anchor="w", padx=4, pady=(0, 10))

        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True)

        self.status = ctk.CTkLabel(
            self, text="", font=ctk.CTkFont(family="Microsoft YaHei UI", size=12),
            text_color="#64748b",
        )
        self.status.pack(fill="x", pady=(10, 0))

        try:
            self.ctrl.bind("<Escape>", self._cancel_drag)
        except Exception:
            pass

    def set_status(self, text):
        self.status.configure(text=text or "")

    def refresh(self):
        for w in self.body.winfo_children():
            w.destroy()
        self._zones = {}
        adapters = [a for a in (self.ctrl.adapters or []) if a.get("up") and a.get("ipv4")]
        if not adapters:
            empty = ctk.CTkFrame(self.body, fg_color=BG_ZONE, corner_radius=18)
            empty.pack(fill="both", expand=True)
            ctk.CTkLabel(
                empty, text="还没有可用网络",
                font=ctk.CTkFont(family="Microsoft YaHei UI", size=22, weight="bold"),
            ).pack(pady=(80, 8))
            ctk.CTkLabel(
                empty, text="请同时连上有线网和无线网，然后按 F5 刷新。",
                font=ctk.CTkFont(family="Microsoft YaHei UI", size=14),
                text_color="#8b9bb4",
            ).pack()
            return

        n = max(len(adapters), 1)
        for i, adapter in enumerate(adapters):
            col = self._make_zone(self.body, adapter)
            col.grid(row=0, column=i, sticky="nsew", padx=8, pady=0)
            self.body.grid_columnconfigure(i, weight=1, uniform="nic")
        self.body.grid_rowconfigure(0, weight=1)

        leftover = self._unassigned_rules(adapters)
        if leftover:
            bar = ctk.CTkFrame(self.body, fg_color=BG_ZONE, corner_radius=14)
            bar.grid(row=1, column=0, columnspan=n, sticky="ew", padx=8, pady=(12, 0))
            ctk.CTkLabel(bar, text="还没放到网上的软件（拖进上面的网络）",
                         text_color="#8b9bb4",
                         font=ctk.CTkFont(family="Microsoft YaHei UI", size=12)).pack(anchor="w", padx=14, pady=(8, 4))
            row = ctk.CTkFrame(bar, fg_color="transparent")
            row.pack(fill="x", padx=10, pady=(0, 10))
            for rule in leftover:
                tile = self._make_tile(row, rule, None)
                tile.pack(side="left", padx=6, pady=4)

    def _unassigned_rules(self, adapters):
        from adapters import find_adapter
        out = []
        for rule in self.ctrl.config_data.get("rules") or []:
            a = find_adapter(adapters, rule.get("adapter_guid"), rule.get("adapter_name"), rule.get("adapter_kind"))
            if not a:
                out.append(rule)
        return out

    def _make_zone(self, parent, adapter):
        style = KIND_STYLE.get(adapter.get("kind") or "other", KIND_STYLE["other"])
        color = style["color"]
        zone = ctk.CTkFrame(parent, fg_color=BG_ZONE, corner_radius=20, border_width=1, border_color="#243044")
        zone._adapter = adapter
        zone._guid = adapter.get("guid")

        accent = ctk.CTkFrame(zone, height=5, fg_color=color, corner_radius=20)
        accent.pack(fill="x", padx=1, pady=(1, 0))

        head = ctk.CTkFrame(zone, fg_color="transparent")
        head.pack(fill="x", padx=18, pady=(14, 6))
        title = "%s  ·  %s" % (style["title"], adapter.get("name") or "")
        ctk.CTkLabel(
            head, text=title, anchor="w",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=18, weight="bold"),
            text_color="#f1f5f9",
        ).pack(anchor="w")
        ip = (adapter.get("ipv4") or ["-"])[0]
        pub = self.ctrl._adapter_pub.get(adapter.get("guid"))
        sub = ip if not pub else "%s    出口 %s" % (ip, pub)
        ctk.CTkLabel(head, text=sub, anchor="w", text_color=color,
                     font=ctk.CTkFont(family="Consolas", size=13)).pack(anchor="w")
        ctk.CTkLabel(head, text=style["hint"], anchor="w", text_color="#64748b",
                     font=ctk.CTkFont(family="Microsoft YaHei UI", size=12)).pack(anchor="w", pady=(2, 0))

        tiles = ctk.CTkScrollableFrame(zone, fg_color="transparent", height=360)
        tiles.pack(fill="both", expand=True, padx=10, pady=(4, 6))
        zone._tiles = tiles

        rules = self._rules_for(adapter)
        if not rules:
            ctk.CTkLabel(
                tiles, text="把软件图标拖到这里\n或点下面的添加",
                text_color="#4b5b73",
                font=ctk.CTkFont(family="Microsoft YaHei UI", size=14),
                justify="center",
            ).pack(expand=True, pady=40)
        else:
            wrap = ctk.CTkFrame(tiles, fg_color="transparent")
            wrap.pack(fill="x", anchor="n")
            for i, rule in enumerate(rules):
                tile = self._make_tile(wrap, rule, adapter)
                tile.grid(row=i // 3, column=i % 3, padx=6, pady=6, sticky="nw")

        add = ctk.CTkButton(
            zone, text="+  添加软件到这里", height=40, corner_radius=12,
            fg_color="#1e293b", hover_color="#334155", text_color="#e2e8f0",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=13),
            command=lambda a=adapter: self.ctrl.add_exe_to_adapter(a),
        )
        add.pack(fill="x", padx=16, pady=(0, 16))

        for w in (zone, tiles, head, add):
            self._bind_zone_drop(w, adapter)

        self._zones[adapter.get("guid")] = zone
        return zone

    def _rules_for(self, adapter):
        from adapters import find_adapter
        out = []
        for rule in self.ctrl.config_data.get("rules") or []:
            hit = find_adapter(
                self.ctrl.adapters, rule.get("adapter_guid"),
                rule.get("adapter_name"), rule.get("adapter_kind"),
            )
            if hit and hit.get("guid") == adapter.get("guid"):
                out.append(rule)
        return out

    def _ctk_image(self, path):
        from PIL import Image
        if path in self._icon_cache:
            return self._icon_cache[path]
        img = exe_icon(path, size=64)
        if img is None:
            img = placeholder_icon(64)
        cimg = ctk.CTkImage(light_image=img, dark_image=img, size=(44, 44))
        self._icon_cache[path] = cimg
        return cimg

    def _make_tile(self, parent, rule, adapter):
        running = is_rule_running(rule)
        tile = ctk.CTkFrame(parent, width=92, height=108, fg_color=BG_TILE, corner_radius=14)
        tile.pack_propagate(False)
        tile._rule = rule
        img = self._ctk_image(rule.get("exe") or "")
        icon_lbl = ctk.CTkLabel(tile, image=img, text="")
        icon_lbl.pack(pady=(12, 2))
        name = rule.get("name") or os.path.splitext(os.path.basename(rule.get("exe") or ""))[0]
        if len(name) > 8:
            name = name[:7] + "…"
        ctk.CTkLabel(
            tile, text=name, font=ctk.CTkFont(family="Microsoft YaHei UI", size=12),
            text_color="#e2e8f0",
        ).pack()
        dot = "● 运行" if running else ""
        ctk.CTkLabel(tile, text=dot, font=ctk.CTkFont(family="Microsoft YaHei UI", size=10),
                     text_color="#34d399" if running else "#475569").pack()

        for w in (tile, icon_lbl):
            w.bind("<ButtonPress-1>", lambda e, r=rule, t=tile: self._drag_start(e, r, t))
            w.bind("<B1-Motion>", self._drag_move)
            w.bind("<ButtonRelease-1>", lambda e, r=rule: self._drag_end(e, r))
            w.bind("<Double-Button-1>", lambda e, r=rule: self.ctrl.start_rule(r))
            w.bind("<Button-3>", lambda e, r=rule: self._tile_menu(e, r))
        tile.bind("<Enter>", lambda e, t=tile: t.configure(fg_color=BG_TILE_HOT))
        tile.bind("<Leave>", lambda e, t=tile: t.configure(fg_color=BG_TILE) if not self._drag else None)
        return tile

    def _tile_menu(self, event, rule):
        menu = tk.Menu(self, tearoff=0, bg="#1e293b", fg="#f8fafc", activebackground="#334155",
                       font=("Microsoft YaHei UI", 11), bd=0)
        menu.add_command(label="启动", command=lambda: self.ctrl.start_rule(rule))
        menu.add_command(label="放到桌面（快捷方式）", command=lambda: self.ctrl.make_one_rule_shortcut(rule))
        menu.add_command(label="详细设置", command=lambda: self.ctrl.edit_rule(rule))
        menu.add_separator()
        menu.add_command(label="移除", command=lambda: self.ctrl.delete_rule(rule))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _drag_start(self, event, rule, tile):
        self._drag = {
            "rule": rule, "tile": tile,
            "x": event.x_root, "y": event.y_root,
            "moved": False, "press": (event.x_root, event.y_root),
        }

    def _drag_move(self, event):
        if not self._drag:
            return
        dx = event.x_root - self._drag["press"][0]
        dy = event.y_root - self._drag["press"][1]
        if (dx * dx + dy * dy) < 36:
            return
        self._drag["moved"] = True
        if self._ghost is None:
            self._ghost = tk.Toplevel(self)
            self._ghost.overrideredirect(True)
            self._ghost.attributes("-topmost", True)
            try:
                self._ghost.attributes("-alpha", 0.88)
            except Exception:
                pass
            self._ghost.configure(bg="#1b2330")
            name = self._drag["rule"].get("name") or "软件"
            tk.Label(
                self._ghost, text="  %s  " % name, bg="#1b2330", fg="#f8fafc",
                font=("Microsoft YaHei UI", 12), padx=10, pady=8,
            ).pack()
        self._ghost.geometry("+%d+%d" % (event.x_root + 12, event.y_root + 12))
        hit = self._zone_at(event.x_root, event.y_root)
        guid = (hit._guid if hit is not None else None)
        if guid != self._hot_guid:
            self._set_hot(guid)

    def _drag_end(self, event, rule):
        moved = bool(self._drag and self._drag.get("moved"))
        self._destroy_ghost()
        self._set_hot(None)
        self._drag = None
        if not moved:
            return
        zone = self._zone_at(event.x_root, event.y_root)
        if zone is None:
            return
        self.ctrl.assign_rule_to_adapter(rule, zone._adapter)

    def _cancel_drag(self, event=None):
        self._destroy_ghost()
        self._set_hot(None)
        self._drag = None

    def _destroy_ghost(self):
        if self._ghost is not None:
            try:
                self._ghost.destroy()
            except Exception:
                pass
            self._ghost = None

    def _set_hot(self, guid):
        self._hot_guid = guid
        for g, zone in self._zones.items():
            zone.configure(fg_color=BG_ZONE_HOT if g == guid else BG_ZONE,
                           border_color=KIND_STYLE.get((zone._adapter or {}).get("kind"), KIND_STYLE["other"])["color"] if g == guid else "#243044")

    def _zone_at(self, x_root, y_root):
        for zone in self._zones.values():
            try:
                x, y = zone.winfo_rootx(), zone.winfo_rooty()
                w, h = zone.winfo_width(), zone.winfo_height()
            except Exception:
                continue
            if x <= x_root <= x + w and y <= y_root <= y + h:
                return zone
        return None

    def _bind_zone_drop(self, widget, adapter):
        if not getattr(self.ctrl, "_has_dnd", False):
            return
        try:
            from tkinterdnd2 import DND_FILES
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", lambda e, a=adapter: self._on_os_drop(e, a))
        except Exception:
            pass

    def _on_os_drop(self, event, adapter):
        files = _parse_drop_files(self, getattr(event, "data", ""))
        if not files:
            self.set_status("只支持拖入 .exe 程序")
            return
        for path in files:
            self.ctrl.add_exe_to_adapter(adapter, exe_path=path)
