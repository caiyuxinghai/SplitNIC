# -*- coding: utf-8 -*-
"""Simple drag-and-drop board: drop desktop app icons onto a network."""
from __future__ import print_function

import os
import tkinter as tk
import customtkinter as ctk

from icons import exe_icon, placeholder_icon
from launcher import is_rule_running

KIND_STYLE = {
    "wired": {"color": "#3ee0a0", "soft": "#163328", "title": "有线网", "hint": "WorkBuddy、VPN 拖到这里"},
    "wifi": {"color": "#4cc4ff", "soft": "#0f2a3a", "title": "无线网", "hint": "抖音、浏览器拖到这里"},
    "vpn": {"color": "#c4b5fd", "soft": "#241b3a", "title": "VPN", "hint": "要走隧道的软件拖到这里"},
    "virtual": {"color": "#fbbf24", "soft": "#2a2414", "title": "虚拟网卡", "hint": "拖到这里使用这张卡"},
    "other": {"color": "#94a3b8", "soft": "#1b222c", "title": "其他网卡", "hint": "拖到这里使用这张卡"},
}

BG = "#0b0e14"
BG_ZONE = "#121821"
BG_ZONE_HOT = "#1a2432"
BG_TILE = "#1a222e"
BG_TILE_HOT = "#243044"


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
            text="从桌面把应用图标拖进左边或右边的网络  ·  点图标启动",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=15),
            text_color="#9fb0c8",
        )
        self.hint.pack(anchor="w", padx=6, pady=(0, 12))

        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True)

        self.status = ctk.CTkLabel(
            self, text="支持直接拖桌面上的快捷方式（抖音、Chrome…）",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=13),
            text_color="#6b7c93",
        )
        self.status.pack(fill="x", pady=(12, 0))

        try:
            self.ctrl.bind("<Escape>", self._cancel_drag)
        except Exception:
            pass

    def set_status(self, text):
        self.status.configure(text=text or "")

    def flash_zones(self):
        for zone in self._zones.values():
            color = KIND_STYLE.get((zone._adapter or {}).get("kind"), KIND_STYLE["other"])["color"]
            zone.configure(border_color=color, border_width=2)
        self.after(700, lambda: self._set_hot(None))

    def refresh(self):
        for w in self.body.winfo_children():
            w.destroy()
        self._zones = {}
        adapters = [a for a in (self.ctrl.adapters or []) if a.get("up") and a.get("ipv4")]
        if not adapters:
            empty = ctk.CTkFrame(self.body, fg_color=BG_ZONE, corner_radius=22)
            empty.pack(fill="both", expand=True)
            ctk.CTkLabel(
                empty, text="还没有可用网络",
                font=ctk.CTkFont(family="Microsoft YaHei UI", size=24, weight="bold"),
                text_color="#f1f5f9",
            ).pack(pady=(90, 8))
            ctk.CTkLabel(
                empty, text="请同时连上有线网和无线网，然后按 F5",
                font=ctk.CTkFont(family="Microsoft YaHei UI", size=15),
                text_color="#8b9bb4",
            ).pack()
            return

        n = max(len(adapters), 1)
        for i, adapter in enumerate(adapters):
            col = self._make_zone(self.body, adapter)
            col.grid(row=0, column=i, sticky="nsew", padx=10, pady=0)
            self.body.grid_columnconfigure(i, weight=1, uniform="nic")
        self.body.grid_rowconfigure(0, weight=1)

        leftover = self._unassigned_rules(adapters)
        if leftover:
            bar = ctk.CTkFrame(self.body, fg_color=BG_ZONE, corner_radius=16)
            bar.grid(row=1, column=0, columnspan=n, sticky="ew", padx=10, pady=(14, 0))
            ctk.CTkLabel(bar, text="还没放到网上 — 拖进上面任意一张网",
                         text_color="#8b9bb4",
                         font=ctk.CTkFont(family="Microsoft YaHei UI", size=12)).pack(anchor="w", padx=16, pady=(10, 4))
            row = ctk.CTkFrame(bar, fg_color="transparent")
            row.pack(fill="x", padx=10, pady=(0, 12))
            for rule in leftover:
                tile = self._make_tile(row, rule, None)
                tile.pack(side="left", padx=6, pady=4)
        self.bind_os_drops()

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
        zone = ctk.CTkFrame(parent, fg_color=BG_ZONE, corner_radius=24, border_width=1, border_color="#243044")
        zone._adapter = adapter
        zone._guid = adapter.get("guid")

        accent = ctk.CTkFrame(zone, height=6, fg_color=color, corner_radius=24)
        accent.pack(fill="x", padx=1, pady=(1, 0))

        head = ctk.CTkFrame(zone, fg_color="transparent")
        head.pack(fill="x", padx=22, pady=(16, 4))
        net_name = adapter.get("network_name") or adapter.get("name") or style["title"]
        ctk.CTkLabel(
            head, text=net_name,
            anchor="w",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=28, weight="bold"),
            text_color="#f8fafc",
        ).pack(anchor="w")
        bits = [style["title"]]
        if adapter.get("name") and adapter.get("name") != net_name:
            bits.append(adapter.get("name"))
        ctk.CTkLabel(
            head, text="  ·  ".join(bits),
            anchor="w", text_color=color,
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=15),
        ).pack(anchor="w", pady=(2, 0))
        ip = (adapter.get("ipv4") or ["-"])[0]
        pub = self.ctrl._adapter_pub.get(adapter.get("guid"))
        sub = ip if not pub else "%s   出口 %s" % (ip, pub)
        ctk.CTkLabel(head, text=sub, anchor="w", text_color="#64748b",
                     font=ctk.CTkFont(family="Consolas", size=13)).pack(anchor="w", pady=(2, 0))

        well = tk.Canvas(zone, bg=style["soft"], highlightthickness=0, height=320, cursor="hand2")
        well.pack(fill="both", expand=True, padx=16, pady=(10, 8))
        zone._well = well
        zone._color = color

        def _paint(event=None, c=well, col=color, ad=adapter):
            c.delete("all")
            w = max(c.winfo_width(), 40)
            h = max(c.winfo_height(), 40)
            pad = 10
            c.create_rectangle(pad, pad, w - pad, h - pad, outline=col, width=2, dash=(10, 7))
            rules = self._rules_for(ad)
            net_name = ad.get("network_name") or ad.get("name") or style["title"]
            c.create_text(
                w / 2, 36,
                text=net_name,
                fill=col, font=("Microsoft YaHei UI", 20, "bold"),
            )
            if not rules:
                c.create_text(
                    w / 2, h / 2 - 4,
                    text="把桌面上的应用图标拖到这里",
                    fill="#dbeafe", font=("Microsoft YaHei UI", 16, "bold"),
                )
                c.create_text(
                    w / 2, h / 2 + 26,
                    text=style["hint"],
                    fill="#8aa0b8", font=("Microsoft YaHei UI", 12),
                )
            c._drop_rect = (pad, pad, w - pad, h - pad)

        well.bind("<Configure>", _paint)
        zone._paint = _paint

        rules = self._rules_for(adapter)
        wrap = ctk.CTkFrame(zone, fg_color="transparent")
        wrap.pack(fill="x", padx=12, pady=(0, 6))
        zone._wrap = wrap
        if rules:
            for i, rule in enumerate(rules):
                tile = self._make_tile(wrap, rule, adapter)
                tile.grid(row=i // 4, column=i % 4, padx=6, pady=6, sticky="nw")

        add = ctk.CTkButton(
            zone, text="+  或点这里选择程序", height=38, corner_radius=12,
            fg_color="#1e293b", hover_color="#334155", text_color="#cbd5e1",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=13),
            command=lambda a=adapter: self.ctrl.add_exe_to_adapter(a),
        )
        add.pack(fill="x", padx=16, pady=(0, 16))

        self._zones[adapter.get("guid")] = zone
        self.after(20, _paint)
        self._bind_adapter_drop(well, adapter)
        self._bind_adapter_drop(zone, adapter)
        return zone

    def bind_os_drops(self):
        from dropfiles import bind_drop
        bind_drop(self, lambda e: self.ctrl._on_tk_drop(e))
        bind_drop(self.body, lambda e: self.ctrl._on_tk_drop(e))
        for zone in self._zones.values():
            adapter = zone._adapter
            self._bind_adapter_drop(zone, adapter)
            well = getattr(zone, "_well", None)
            if well is not None:
                self._bind_adapter_drop(well, adapter)

    def _bind_adapter_drop(self, widget, adapter):
        from dropfiles import files_from_drop
        try:
            from tkinterdnd2 import DND_FILES
            widget.drop_target_register(DND_FILES)
        except Exception:
            return

        def handler(event, ad=adapter):
            data = getattr(event, "data", "") or ""
            try:
                parts = list(widget.tk.splitlist(data))
            except Exception:
                parts = [data]
            exes = files_from_drop(parts)
            if not exes:
                self.set_status("没认出程序。请拖桌面上的快捷方式（会自动找到对应软件）")
                return
            for exe in exes:
                self.ctrl.add_exe_to_adapter(ad, exe_path=exe)

        try:
            widget.dnd_bind("<<Drop>>", handler)
        except Exception:
            widget.bind("<<Drop>>", handler)

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
        if path in self._icon_cache:
            return self._icon_cache[path]
        img = exe_icon(path, size=96)
        if img is None:
            img = placeholder_icon(96)
        cimg = ctk.CTkImage(light_image=img, dark_image=img, size=(56, 56))
        self._icon_cache[path] = cimg
        return cimg

    def _make_tile(self, parent, rule, adapter):
        running = is_rule_running(rule)
        tile = ctk.CTkFrame(parent, width=108, height=124, fg_color=BG_TILE, corner_radius=16)
        tile.pack_propagate(False)
        tile._rule = rule
        img = self._ctk_image(rule.get("exe") or "")
        icon_lbl = ctk.CTkLabel(tile, image=img, text="")
        icon_lbl.pack(pady=(14, 4))
        name = rule.get("name") or os.path.splitext(os.path.basename(rule.get("exe") or ""))[0]
        if len(name) > 9:
            name = name[:8] + "…"
        ctk.CTkLabel(
            tile, text=name, font=ctk.CTkFont(family="Microsoft YaHei UI", size=13),
            text_color="#f1f5f9",
        ).pack()
        ctk.CTkLabel(
            tile, text="运行中" if running else "点击启动",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=11),
            text_color="#34d399" if running else "#64748b",
        ).pack()

        for w in (tile, icon_lbl):
            w.bind("<ButtonPress-1>", lambda e, r=rule, t=tile: self._drag_start(e, r, t))
            w.bind("<B1-Motion>", self._drag_move)
            w.bind("<ButtonRelease-1>", lambda e, r=rule: self._drag_end(e, r))
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
                self._ghost.attributes("-alpha", 0.9)
            except Exception:
                pass
            self._ghost.configure(bg="#1a222e")
            name = self._drag["rule"].get("name") or "软件"
            tk.Label(
                self._ghost, text="  %s  " % name, bg="#1a222e", fg="#f8fafc",
                font=("Microsoft YaHei UI", 13), padx=12, pady=10,
            ).pack()
        self._ghost.geometry("+%d+%d" % (event.x_root + 14, event.y_root + 14))
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
            self.ctrl.start_rule(rule)
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
            color = KIND_STYLE.get((zone._adapter or {}).get("kind"), KIND_STYLE["other"])["color"]
            hot = g == guid
            zone.configure(
                fg_color=BG_ZONE_HOT if hot else BG_ZONE,
                border_color=color if hot else "#243044",
                border_width=2 if hot else 1,
            )

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
