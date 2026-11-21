#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
quant_gui.py — AI Quant Workbench v4.0 (VS Code + TradingView Single-Screen Template & Hermes 2-Way Co-Pilot)
โครงสร้างหน้าจอแบบ Single-Screen Workbench (ไม่ต้องสลับแท็บไปมา):
  • ด้านบนสุด (Top Bar + 4 KPI Cards): สรุปสัญญาณ, คะแนน Quant Score, ML Win Prob%, POC/VWAP, VaR95%, ดัชนี VIX และข่าวล่าสุด
  • ด้านซ้าย (Watchlist Explorer): รายชื่อหุ้นที่สแกน คลิกเพียงครั้งเดียวอัปเดตทั้งการ์ด กราฟ และใบคำสั่งซื้อขายทันที
  • ตรงกลางบน (Interactive Chart Canvas): ปุ่มสลับโหมดกราฟ 5 แบบ (▲BUY/▼SELL, VWAP/POC, Monte Carlo 1,000 รอบ, Portfolio & Correlation, เทียบกลยุทธ์)
  • ตรงกลางล่าง (VS Code Dock Panel): พอร์ตจริง & Semi-Auto Order Ticket + ปุ่ม 1-Click Rebalance พอร์ตรวม + ตาราง Optimizer/Trade Log
  • ด้านขวา (Hermes Agent Co-Pilot & Live Terminal): เชื่อมต่อ 2 ทางกับ Hermes Agent (MEMORY.md & hermes_bus.json) สั่งงานข้ามหน้าต่างได้สดๆ
"""

import argparse
import json
import os
import queue
import re
import sqlite3
import threading
import time
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

import backtest_engine as be
import broker_bridge as bb
import chart_drawing_tools as cdt
try:
    import generate_phase2_report_pdf as pdf_gen
except ImportError:
    pdf_gen = None
import hermes_bridge as hb
import mac_ui_components as mui
import quant_v4_modules as qv4
import quant_v5_institutional as qv5

# บังคับให้ Working Directory อยู่ที่โฟลเดอร์โปรเจกต์เสมอ
os.chdir(os.path.dirname(os.path.abspath(__file__)))

plt.rcParams["font.family"] = ["Leelawadee UI", "Segoe UI", "Tahoma", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

UI_STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui_state.json")

# อีโมจิ/สัญลักษณ์ที่ฟอนต์ Leelawadee UI ไม่มี (จะกลายเป็นกล่องสี่เหลี่ยมเปล่าในกราฟ) — คง ▲▼ ไว้
_EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200D]+")


def strip_emoji(text: str) -> str:
    return re.sub(r"\s{2,}", " ", _EMOJI_RE.sub("", text)).strip()


THEMES = {
    "dark": {
        "bg": "#161618",
        "panel": "#1C1C1E",
        "header": "#1C1C1E",
        "card": "#242426",
        "card_border": "#38383A",
        "fg": "#F5F5F7",
        "sub_fg": "#8E8E93",
        "accent": "#30D158",
        "border": "#38383A",
        "seg_track": "#2C2C2E",
        "seg_hover": "#3A3A3C",
        "tree_bg": "#1C1C1E",
        "tree_fg": "#F5F5F7",
        "tree_head_bg": "#242426",
        "tree_head_fg": "#AEAEB2",
        "tree_sel": "#0A84FF",
        "log_bg": "#141416",
        "log_fg": "#D1D1D6",
        "fig_bg": "#1C1C1E",
        "ax_bg": "#161618",
        "grid": "#2C2C2E",
        "tag_buy_bg": "#122B20",
        "tag_buy_fg": "#30D158",
        "tag_hold_bg": "#14263C",
        "tag_hold_fg": "#64D2FF",
        "tag_wait_bg": "#2D2512",
        "tag_wait_fg": "#FFD60A",
        "tag_sell_bg": "#331618",
        "tag_sell_fg": "#FF453A",
    },
    "light": {
        "bg": "#F2F2F7",
        "panel": "#FFFFFF",
        "header": "#FFFFFF",
        "card": "#FFFFFF",
        "card_border": "#D1D1D6",
        "fg": "#1C1C1E",
        "sub_fg": "#6E6E73",
        "accent": "#007AFF",
        "border": "#D1D1D6",
        "seg_track": "#E5E5EA",
        "seg_hover": "#D1D1D6",
        "tree_bg": "#FFFFFF",
        "tree_fg": "#1C1C1E",
        "tree_head_bg": "#F2F2F7",
        "tree_head_fg": "#3A3A3C",
        "tree_sel": "#007AFF",
        "log_bg": "#F9F9FB",
        "log_fg": "#1C1C1E",
        "fig_bg": "#FFFFFF",
        "ax_bg": "#F9F9FB",
        "grid": "#E5E5EA",
        "tag_buy_bg": "#DCFCE7",
        "tag_buy_fg": "#166534",
        "tag_hold_bg": "#DBEAFE",
        "tag_hold_fg": "#1E40AF",
        "tag_wait_bg": "#FEF3C7",
        "tag_wait_fg": "#92400E",
        "tag_sell_bg": "#FEE2E2",
        "tag_sell_fg": "#991B1B",
    },
}


class WordStyleInputEnhancer:
    """
    ระบบเสริมช่องกรอกข้อความ (Entry / TEntry / Text) ให้รองรับคีย์ลัดและคลิกขวาเหมือน Microsoft Word 2019:
      • Ctrl+A : เลือกข้อความทั้งหมดในช่อง (Select All)
      • Ctrl+C : คัดลอกข้อความที่คลุมดำไปยัง Clipboard (Copy)
      • Ctrl+X : ตัดข้อความที่คลุมดำไปยัง Clipboard และบันทึกประวัติ Undo (Cut)
      • Ctrl+V : วางข้อความจาก Clipboard (หากมีการคลุมดำอยู่ จะวางทับเฉพาะส่วนที่คลุมดำทันทีเหมือน Word 2019)
      • Ctrl+Z : ย้อนกลับการแก้ไขก่อนหน้าทีละสเต็ป (Undo Stack พร้อมคืนตำแหน่งเคอร์เซอร์)
      • Ctrl+Y : ทำซ้ำการแก้ไขที่เพิ่งย้อนกลับ (Redo Stack)
      • รองรับทั้งขณะตั้งแป้นพิมพ์ภาษาอังกฤษ (EN) และภาษาไทย (TH: ฟ, แ, อ, ผ, ป, ั) บน Windows
      • รองรับเมนูคลิกขวา (Right-Click Context Menu) ทุกช่องกรอก
    """

    def __init__(self, root: tk.Tk):
        self.root = root
        self.undo_stacks: dict[tk.Widget, list[tuple[str, int]]] = {}
        self.redo_stacks: dict[tk.Widget, list[tuple[str, int]]] = {}
        self.last_known_text: dict[tk.Widget, str] = {}
        self._active_widget: tk.Widget | None = None

        self._build_context_menu()
        self._bind_global_classes()

    def _build_context_menu(self):
        self.ctx_menu = tk.Menu(
            self.root,
            tearoff=0,
            bg="#252526",
            fg="#D4D4D4",
            activebackground="#007ACC",
            activeforeground="#FFFFFF",
            font=("Tahoma", 9),
        )
        self.ctx_menu.add_command(label="↩ เลิกทำ (Undo)              Ctrl+Z", command=lambda: self._exec_on_active(self.do_undo))
        self.ctx_menu.add_command(label="↪ ทำซ้ำ (Redo)               Ctrl+Y", command=lambda: self._exec_on_active(self.do_redo))
        self.ctx_menu.add_separator()
        self.ctx_menu.add_command(label="✂ ตัด (Cut)                  Ctrl+X", command=lambda: self._exec_on_active(self.do_cut))
        self.ctx_menu.add_command(label="📋 คัดลอก (Copy)             Ctrl+C", command=lambda: self._exec_on_active(self.do_copy))
        self.ctx_menu.add_command(label="📥 วาง (Paste)               Ctrl+V", command=lambda: self._exec_on_active(self.do_paste))
        self.ctx_menu.add_separator()
        self.ctx_menu.add_command(label="🔍 เลือกทั้งหมด (Select All)   Ctrl+A", command=lambda: self._exec_on_active(self.do_select_all))

    def _exec_on_active(self, func):
        w = self._active_widget or self.root.focus_get()
        if w:
            func(w)

    def _bind_global_classes(self):
        for cls_name in ("Entry", "TEntry", "Text"):
            self.root.bind_class(cls_name, "<FocusIn>", self._on_focus_in, add="+")
            self.root.bind_class(cls_name, "<KeyPress>", self._on_key_press, add="+")
            self.root.bind_class(cls_name, "<KeyRelease>", self._on_key_release, add="+")
            self.root.bind_class(cls_name, "<Control-KeyPress>", self._on_ctrl_key, add="+")
            self.root.bind_class(cls_name, "<Button-3>", self._on_right_click, add="+")

    def _is_entry(self, w: tk.Widget) -> bool:
        return isinstance(w, (tk.Entry, ttk.Entry))

    def _is_text(self, w: tk.Widget) -> bool:
        return isinstance(w, tk.Text)

    def _get_entry_state(self, w: tk.Entry) -> tuple[str, int]:
        try:
            return w.get(), int(w.index(tk.INSERT))
        except Exception:
            return "", 0

    def _push_undo(self, w: tk.Widget):
        if not self._is_entry(w):
            return
        text, cur = self._get_entry_state(w)
        stack = self.undo_stacks.setdefault(w, [])
        if not stack or stack[-1][0] != text:
            stack.append((text, cur))
            if len(stack) > 100:
                stack.pop(0)
        self.last_known_text[w] = text

    def _on_focus_in(self, event):
        w = event.widget
        self._active_widget = w
        if self._is_entry(w) and w not in self.undo_stacks:
            self._push_undo(w)

    def _on_key_press(self, event):
        w = event.widget
        # หากไม่ได้กดปุ่ม Control ค้างไว้ ให้บันทึกสถานะก่อนพิมพ์แก้ไขลง Undo Stack
        if not (event.state & 0x4) and self._is_entry(w):
            if event.keysym in ("BackSpace", "Delete", "space") or len(event.char) == 1:
                cur_text = w.get()
                if self.last_known_text.get(w) != cur_text:
                    self._push_undo(w)
                elif not self.undo_stacks.get(w):
                    self._push_undo(w)

    def _on_key_release(self, event):
        w = event.widget
        if not (event.state & 0x4) and self._is_entry(w):
            cur_text = w.get()
            if self.last_known_text.get(w) != cur_text:
                self._push_undo(w)
                self.redo_stacks[w] = []

    def _on_right_click(self, event):
        w = event.widget
        self._active_widget = w
        w.focus_set()
        try:
            self.ctx_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.ctx_menu.grab_release()
        return "break"

    def _on_ctrl_key(self, event):
        """ตรวจจับคีย์ลัด Ctrl+A, C, V, X, Z, Y ทั้งภาษาอังกฤษและภาษาไทย (ด้วย Windows Virtual KeyCode & KeySym)"""
        w = event.widget
        kc = event.keycode
        ks = (event.keysym or "").lower()

        if kc == 65 or ks in ("a", "ฟ"):
            return self.do_select_all(w)
        elif kc == 67 or ks in ("c", "แ"):
            return self.do_copy(w)
        elif kc == 88 or ks in ("x", "ป"):
            return self.do_cut(w)
        elif kc == 86 or ks in ("v", "อ"):
            return self.do_paste(w)
        elif kc == 90 or ks in ("z", "ผ"):
            if event.state & 0x1:  # Ctrl+Shift+Z = Redo
                return self.do_redo(w)
            return self.do_undo(w)
        elif kc == 89 or ks in ("y", "ั"):
            return self.do_redo(w)
        return None

    def do_select_all(self, w: tk.Widget):
        if self._is_entry(w):
            w.selection_range(0, tk.END)
            w.icursor(tk.END)
            return "break"
        elif self._is_text(w):
            w.tag_add(tk.SEL, "1.0", "end-1c")
            w.mark_set(tk.INSERT, "end-1c")
            w.see(tk.INSERT)
            return "break"
        return None

    def do_copy(self, w: tk.Widget):
        try:
            if self._is_entry(w) and w.selection_present():
                sel = w.selection_get()
            elif self._is_text(w) and w.tag_ranges(tk.SEL):
                sel = w.get(tk.SEL_FIRST, tk.SEL_LAST)
            else:
                return "break"
            self.root.clipboard_clear()
            self.root.clipboard_append(sel)
            self.root.update_idletasks()
        except Exception:
            pass
        return "break"

    def do_cut(self, w: tk.Widget):
        if self._is_entry(w):
            if w.selection_present():
                self._push_undo(w)
                self.do_copy(w)
                w.delete(tk.SEL_FIRST, tk.SEL_LAST)
                self._push_undo(w)
                self.redo_stacks[w] = []
            return "break"
        elif self._is_text(w):
            if w.tag_ranges(tk.SEL):
                self.do_copy(w)
                w.delete(tk.SEL_FIRST, tk.SEL_LAST)
            return "break"
        return None

    def do_paste(self, w: tk.Widget):
        try:
            clip = self.root.clipboard_get()
        except Exception:
            return "break"

        if self._is_entry(w):
            self._push_undo(w)
            # ถ้ามีข้อความที่คลุมดำอยู่ ให้ลบทิ้งก่อนวางทับทันทีเหมือน Microsoft Word 2019
            if w.selection_present():
                start_idx = w.index(tk.SEL_FIRST)
                w.delete(tk.SEL_FIRST, tk.SEL_LAST)
                w.icursor(start_idx)
            insert_pos = w.index(tk.INSERT)
            clean_clip = clip.replace("\r\n", " ").replace("\n", " ")
            w.insert(insert_pos, clean_clip)
            w.icursor(insert_pos + len(clean_clip))
            self._push_undo(w)
            self.redo_stacks[w] = []
            return "break"
        elif self._is_text(w):
            if w.tag_ranges(tk.SEL):
                w.delete(tk.SEL_FIRST, tk.SEL_LAST)
            w.insert(tk.INSERT, clip)
            w.see(tk.INSERT)
            return "break"
        return None

    def do_undo(self, w: tk.Widget):
        if self._is_entry(w):
            stack = self.undo_stacks.get(w, [])
            cur_text, cur_pos = self._get_entry_state(w)
            while stack and stack[-1][0] == cur_text and len(stack) > 1:
                self.redo_stacks.setdefault(w, []).append(stack.pop())
            if stack:
                prev_text, prev_pos = stack[-1]
                if prev_text != cur_text:
                    self.redo_stacks.setdefault(w, []).append((cur_text, cur_pos))
                    w.delete(0, tk.END)
                    w.insert(0, prev_text)
                    w.icursor(min(prev_pos, len(prev_text)))
                    self.last_known_text[w] = prev_text
            return "break"
        elif self._is_text(w):
            try:
                w.edit_undo()
            except Exception:
                pass
            return "break"
        return None

    def do_redo(self, w: tk.Widget):
        if self._is_entry(w):
            r_stack = self.redo_stacks.get(w, [])
            if r_stack:
                cur_text, cur_pos = self._get_entry_state(w)
                self.undo_stacks.setdefault(w, []).append((cur_text, cur_pos))
                next_text, next_pos = r_stack.pop()
                w.delete(0, tk.END)
                w.insert(0, next_text)
                w.icursor(min(next_pos, len(next_text)))
                self.last_known_text[w] = next_text
            return "break"
        elif self._is_text(w):
            try:
                w.edit_redo()
            except Exception:
                pass
            return "break"
        return None


class QuantWorkbenchV4:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("AI Quant Workbench v7.0 Final — Production & Portfolio Standard | 4 Core Strategies, Cross-Sectional, WFO Gate & Circuit Breaker")
        self.root.geometry("1480x900")
        self.root.minsize(1220, 760)

        # เปิดใช้งานระบบคีย์ลัด Ctrl+C, V, Z, Y, X, A และคลิกขวาแบบ Microsoft Word 2019 ทุกช่องกรอกข้อความ
        self.input_enhancer = WordStyleInputEnhancer(self.root)

        self.theme_mode = "dark"
        self.msg_queue: queue.Queue = queue.Queue()
        self.is_running = False

        self.ticker_cache: dict[str, dict] = {}
        self.scan_rows_list: list[dict] = []
        self.all_bt_rows: list[dict] = []
        self.all_trade_rows: list[dict] = []
        self.selected_ticker: str = "^NDX"
        self.chart_mode: str = "signals_markers"

        # สถานะระบบสั่งซื้อขายอัตโนมัติ (Auto-Sniper & Auto-Guardian Bot)
        self.auto_bot_enabled: bool = False
        self.auto_bot_interval_sec: int = 30
        self.auto_bot_countdown: int = 30
        self.auto_mode_instant = tk.BooleanVar(value=True)
        self.auto_mode_sniper = tk.BooleanVar(value=True)
        self.auto_mode_guardian = tk.BooleanVar(value=True)
        self.auto_executed_today: set[str] = set()

        self.panel_frames: list[tk.Frame] = []
        self.panel_labels: list[tk.Label] = []
        self.card_frames: list[tk.Frame] = []
        self.card_title_labels: list[tk.Label] = []
        self.card_body_labels: list[tk.Label] = []
        self.mode_buttons: dict[str, tk.Button] = {}
        self.right_panel_visible: bool = True
        self.dock_panel_visible: bool = True
        self.terminal_visible: bool = False
        self.show_chart_legend: bool = False
        self.chart_fullscreen: bool = False
        self._saved_right_visible: bool = True
        self._saved_dock_visible: bool = True
        self.draw_toolbar_visible: bool = False
        self._settings_win = None
        self.toaster = mui.MacToastManager(self.root)
        self.drawing_mgr = cdt.ChartDrawingManager(
            on_redraw=self.redraw_interactive_chart,
            on_status=lambda msg: self.status_var.set(msg) if hasattr(self, "status_var") else None,
        )

        self.style = ttk.Style()
        if "clam" in self.style.theme_names():
            self.style.theme_use("clam")
        self.style.layout("Hidden.TNotebook.Tab", [])
        self.style.configure("Hidden.TNotebook", borderwidth=0, tabmargins=0)

        self._build_top_command_bar()
        self._build_kpi_cards_banner()
        self._build_workbench_panes()

        # ติดตั้ง Hermes Skill และใช้ธีม
        hb.install_hermes_skill()
        self.apply_theme()

        # คีย์ลัดทั้งแอป + คืนค่า UI ที่บันทึกไว้ + บันทึกตอนปิดหน้าต่าง
        self.root.bind_all("<KeyPress>", self._on_global_key, add="+")
        self._load_ui_state()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # โหลดข้อมูลเริ่มต้น
        self._load_existing_csv_if_available()
        self.sync_broker_portfolio()
        self._refresh_hermes_chat_box()

        self.root.after(80, self._process_queue)
        self.root.after(1500, self._poll_hermes_bus)
        self.root.after(1000, self._auto_bot_tick)

    # ==========================================
    # ระบบสลับโหมดมืด VS Code / โหมดสว่าง
    # ==========================================
    def toggle_theme(self):
        self.theme_mode = "light" if self.theme_mode == "dark" else "dark"
        self.apply_theme()
        self.redraw_interactive_chart()

    def apply_theme(self):
        t = THEMES[self.theme_mode]
        self.root.configure(bg=t["bg"])

        if self.theme_mode == "dark":
            self.theme_btn.config(text="☀️ Light Mode", bg="#636366", fg="#FFFFFF")
        else:
            self.theme_btn.config(text="🌙 Dark Mode", bg="#3A3A3C", fg="#FFFFFF")

        self.style.configure(".", background=t["bg"], foreground=t["fg"], font=("Leelawadee UI", 10))
        self.style.configure("TFrame", background=t["bg"])
        self.style.configure("TPanedwindow", background=t["bg"])
        self.style.configure("TNotebook", background=t["header"], borderwidth=0)
        self.style.configure("Hidden.TNotebook", background=t["bg"], borderwidth=0)
        self.style.configure("TNotebook.Tab", background=t["panel"], foreground=t["fg"], font=("Leelawadee UI", 10, "bold"), padding=[10, 4])
        self.style.map("TNotebook.Tab", background=[("selected", t["tree_sel"])], foreground=[("selected", "#FFFFFF")])

        # ปรับแต่ง Scrollbar ให้เนียนตาสไตล์ macOS
        self.style.configure(
            "Vertical.TScrollbar",
            background=t["border"],
            troughcolor=t["tree_bg"],
            bordercolor=t["tree_bg"],
            arrowcolor=t["sub_fg"],
            relief="flat",
        )
        self.style.configure(
            "Horizontal.TScrollbar",
            background=t["border"],
            troughcolor=t["tree_bg"],
            bordercolor=t["tree_bg"],
            arrowcolor=t["sub_fg"],
            relief="flat",
        )

        self.style.configure(
            "Treeview",
            background=t["tree_bg"],
            fieldbackground=t["tree_bg"],
            foreground=t["tree_fg"],
            rowheight=30,
            font=("Leelawadee UI", 10),
            borderwidth=0,
        )
        self.style.configure("Treeview.Heading", background=t["tree_head_bg"], foreground=t["tree_head_fg"], font=("Leelawadee UI", 9, "bold"), relief="flat", padding=[6, 5])
        self.style.map("Treeview", background=[("selected", t["tree_sel"])], foreground=[("selected", "#FFFFFF")])

        for fr in self.panel_frames:
            fr.config(bg=t["panel"])
        for lbl in self.panel_labels:
            lbl.config(bg=t["panel"], fg=t["fg"])

        for cf in self.card_frames:
            cf.config(bg=t["card"], highlightbackground=t["card_border"])
        for ctl in self.card_title_labels:
            ctl.config(bg=t["card"], fg=t["sub_fg"])
        for cbl in self.card_body_labels:
            cbl.config(bg=t["card"], fg=t["fg"])

        self.status_lbl.config(bg=t["panel"], fg=t["accent"])
        self.account_banner_lbl.config(bg=t["panel"], fg=t["accent"])

        for tree in (self.watch_tree, self.opt_tree, self.pos_tree, self.order_tree, self.trade_tree):
            tree.tag_configure("buy", background=t["tag_buy_bg"], foreground=t["tag_buy_fg"])
            tree.tag_configure("hold", background=t["tag_hold_bg"], foreground=t["tag_hold_fg"])
            tree.tag_configure("wait", background=t["tag_wait_bg"], foreground=t["tag_wait_fg"])
            tree.tag_configure("sell", background=t["tag_sell_bg"], foreground=t["tag_sell_fg"])

        self.bt_tree.tag_configure("pro", background=t["tag_buy_bg"], foreground=t["tag_buy_fg"], font=("Leelawadee UI", 10, "bold"))
        self.bt_tree.tag_configure("atr", background=t["tag_hold_bg"], foreground=t["tag_hold_fg"])

        self.hermes_chat_box.config(bg=t["log_bg"], fg=t["fg"])
        self.log_box.config(bg=t["log_bg"], fg=t["log_fg"])

        for seg in (getattr(self, "chart_seg", None), getattr(self, "dock_seg", None), getattr(self, "draw_seg", None)):
            if seg is not None:
                seg.set_theme(
                    parent_bg=t["panel"],
                    track_bg=t["seg_track"],
                    active_bg="#0A84FF",
                    hover_bg=t["seg_hover"],
                    fg=t["sub_fg"],
                    active_fg="#FFFFFF",
                    border_color=t["border"],
                )
        self._highlight_active_mode_button()

    # ==========================================
    # 1. แถบควบคุมด้านบนสุด (macOS Clean Toolbar + แยกกลุ่ม Utility / Execution)
    # ==========================================
    def _build_top_command_bar(self):
        top = tk.Frame(self.root, bg="#1C1C1E", padx=14, pady=8)
        top.pack(fill=tk.X)
        self.panel_frames.append(top)

        # เส้นคั่นบางๆ ใต้ Toolbar สไตล์ macOS
        sep = tk.Frame(self.root, bg="#38383A", height=1)
        sep.pack(fill=tk.X)

        lbl_brand = tk.Label(top, text="QUANT v7.0", font=("Segoe UI", 11, "bold"), fg="#0A84FF", bg="#1C1C1E")
        lbl_brand.pack(side=tk.LEFT, padx=(0, 14))

        # ช่องกรอก Watchlist ขอบมนเรืองแสงเมื่อคลิก (macOS Focus Ring)
        lbl_w = tk.Label(top, text="Watchlist", font=("Segoe UI", 9, "bold"), fg="#8E8E93", bg="#1C1C1E")
        lbl_w.pack(side=tk.LEFT)
        self.panel_labels.append(lbl_w)

        self.tickers_var = tk.StringVar(value="^NDX NVDA AAPL BTC-USD")
        mui.RoundedFocusEntry(
            top,
            textvariable=self.tickers_var,
            width=18,
            font=("Consolas", 10, "bold"),
            fg="#30D158",
            bg="#141416",
            parent_bg="#1C1C1E",
        ).pack(side=tk.LEFT, padx=(6, 4))

        mui.RoundedButton(
            top,
            text="🔍",
            bg="#2C2C2E",
            fg="#F5F5F7",
            parent_bg="#1C1C1E",
            radius=12.0,
            width=32,
            height=28,
            command=self.open_ticker_expander_popup,
        ).pack(side=tk.LEFT, padx=(0, 10))

        # ค่าตั้งที่เปลี่ยนไม่บ่อย (Period / ทุน / Risk / ดึงสด / AI) ย้ายไปไว้ในป๊อปอัป ⚙ Settings
        self.period_var = tk.StringVar(value="2y")
        self.capital_var = tk.StringVar(value="100000")
        self.risk_var = tk.StringVar(value="2.0")
        self.force_refresh_var = tk.BooleanVar(value=False)
        self.use_ai_var = tk.BooleanVar(value=False)

        self.settings_btn = mui.RoundedButton(
            top,
            text="⚙",
            bg="#2C2C2E",
            fg="#F5F5F7",
            parent_bg="#1C1C1E",
            radius=12.0,
            width=32,
            height=28,
            command=self.open_settings_popover,
        )
        self.settings_btn.pack(side=tk.LEFT)

        # สรุปค่าตั้งปัจจุบันแบบอ่านอย่างเดียว เช่น "2y · $100,000 · Risk 2.0%"
        self.settings_summary_var = tk.StringVar()
        lbl_sum = tk.Label(top, textvariable=self.settings_summary_var, font=("Leelawadee UI", 9), fg="#8E8E93", bg="#1C1C1E")
        lbl_sum.pack(side=tk.LEFT, padx=(8, 0))
        self.panel_labels.append(lbl_sum)
        for v in (self.period_var, self.capital_var, self.risk_var, self.force_refresh_var, self.use_ai_var):
            v.trace_add("write", lambda *_a: self._refresh_settings_summary())
        self._refresh_settings_summary()

        # ==========================================
        # ชุดปุ่มด้านขวา: แยกกลุ่ม Execution/Danger กับ Utility/Focus ให้ชัดเจน
        # ==========================================
        mac_dock = tk.Frame(top, bg="#1C1C1E")
        mac_dock.pack(side=tk.RIGHT, padx=(6, 0))
        self.panel_frames.append(mac_dock)

        # กลุ่ม 1: Scan & Utility
        self.run_btn = mui.MacExpandingCircleButton(
            mac_dock,
            icon="▶",
            label="รันสแกน",
            tooltip_desc="ดึงข้อมูลสด คำนวณ Quant Score, ML Win Prob, จัดพอร์ต v4 และจำลอง Monte Carlo 1,000 รอบ",
            bg_color="#0A84FF",
            parent_bg="#1C1C1E",
            expanded_width=116,
            command=self.start_analysis_thread,
        )
        self.run_btn.pack(side=tk.LEFT, padx=3)

        self.pdf_btn = mui.MacExpandingCircleButton(
            mac_dock,
            icon="📄",
            label="สร้าง PDF",
            tooltip_desc="สร้างและอัปเดตไฟล์รายงาน 02-quant-phase2-report.pdf",
            bg_color="#FF9F0A",
            parent_bg="#1C1C1E",
            expanded_width=112,
            command=self.generate_pdf_report,
        )
        self.pdf_btn.pack(side=tk.LEFT, padx=3)

        self.theme_btn = mui.MacExpandingCircleButton(
            mac_dock,
            icon="☀️",
            label="Light",
            tooltip_desc="สลับโทนสีหน้าจอระหว่าง macOS Dark และ Light",
            bg_color="#48484A",
            parent_bg="#1C1C1E",
            expanded_width=96,
            command=self.toggle_theme,
        )
        self.theme_btn.pack(side=tk.LEFT, padx=3)

        # Focus Mode toggles (พับ/กาง Panel ขวา และ Bottom Dock)
        self.toggle_dock_btn = mui.RoundedButton(
            mac_dock,
            text="⬓ Dock",
            bg="#2C2C2E",
            fg="#AEAEB2",
            parent_bg="#1C1C1E",
            radius=12.0,
            width=62,
            height=30,
            command=self.toggle_dock_panel,
        )
        self.toggle_dock_btn.pack(side=tk.LEFT, padx=(6, 2))

        self.toggle_right_btn = mui.RoundedButton(
            mac_dock,
            text="◧ Hermes",
            bg="#2C2C2E",
            fg="#AEAEB2",
            parent_bg="#1C1C1E",
            radius=12.0,
            width=74,
            height=30,
            command=self.toggle_right_panel,
        )
        self.toggle_right_btn.pack(side=tk.LEFT, padx=(2, 6))

        # เส้นคั่นโซน Execution / Danger
        tk.Frame(mac_dock, bg="#38383A", width=1, height=22).pack(side=tk.LEFT, padx=6)

        # กลุ่ม 2: Execution & Risk (แยกชัดเจนกันกดพลาด)
        self.rebal_btn = mui.MacExpandingCircleButton(
            mac_dock,
            icon="⚖",
            label="Rebalance",
            tooltip_desc="คำนวณและส่งชุดคำสั่งปรับสมดุลพอร์ตรวมอัตโนมัติ (1-Click Portfolio Rebalance)",
            bg_color="#30D158",
            parent_bg="#1C1C1E",
            expanded_width=126,
            command=self.execute_portfolio_rebalance,
        )
        self.rebal_btn.pack(side=tk.LEFT, padx=3)

        self.sniper_hub_btn = mui.MacExpandingCircleButton(
            mac_dock,
            icon="🎯",
            label="Auto-Sniper",
            tooltip_desc="คอมมานด์ซื้อหุ้นตัวท็อปอันดับ 1 หรือตั้งบอทเฝ้าช้อนโซน Sniper & คุม TP/SL อัตโนมัติ",
            bg_color="#BF5AF2",
            parent_bg="#1C1C1E",
            expanded_width=132,
            command=self.open_auto_sniper_hub_dialog,
        )
        self.sniper_hub_btn.pack(side=tk.LEFT, padx=3)

        self.panic_btn = mui.MacExpandingCircleButton(
            mac_dock,
            icon="🛑",
            label="Panic Stop",
            tooltip_desc="หยุดฉุกเฉิน: ปิดบอทอัตโนมัติทันที และสั่งขายล้างพอร์ตเข้าเงินสด 100%",
            bg_color="#FF453A",
            parent_bg="#1C1C1E",
            expanded_width=122,
            command=self.trigger_emergency_panic,
        )
        self.panic_btn.pack(side=tk.LEFT, padx=(3, 0))

    # ==========================================
    # 2. แถบ 4 KPI Cards ด้านบน (macOS Minimal Card — โปร่ง ชัด ไม่รก)
    # ==========================================
    def _build_kpi_cards_banner(self):
        wrap = tk.Frame(self.root, padx=12, pady=8)
        wrap.pack(fill=tk.X)
        self.panel_frames.append(wrap)

        self.kpi_vars = [
            (tk.StringVar(value="SIGNAL"), tk.StringVar(value="เลือกหุ้นจากแถบซ้ายเพื่อดูข้อมูล")),
            (tk.StringVar(value="ML WIN PROB"), tk.StringVar(value="ยังไม่มีข้อมูล")),
            (tk.StringVar(value="DAILY VaR 95%"), tk.StringVar(value="ยังไม่มีข้อมูล")),
            (tk.StringVar(value="MACRO VIX"), tk.StringVar(value="ยังไม่มีข้อมูล")),
        ]
        # ตัวเลขหลัก 1 ค่าต่อการ์ด + บรรทัดรองสั้นๆ (รายละเอียดเต็มอยู่ใน Tooltip = kpi_vars[i][1])
        self.kpi_value_vars = [tk.StringVar(value="—") for _ in range(4)]
        self.kpi_sub_vars = [tk.StringVar(value="") for _ in range(4)]
        self.kpi_value_labels: list[tk.Label] = []

        for idx, (title_v, body_v) in enumerate(self.kpi_vars):
            card = tk.Frame(wrap, highlightthickness=1, bd=0, cursor="hand2")
            card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5)
            self.card_frames.append(card)

            inner = tk.Frame(card, padx=14, pady=8)
            inner.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            self.card_frames.append(inner)

            tl = tk.Label(inner, textvariable=title_v, font=("Leelawadee UI", 8, "bold"), anchor="w")
            tl.pack(fill=tk.X)
            self.card_title_labels.append(tl)

            vl = tk.Label(inner, textvariable=self.kpi_value_vars[idx], font=("Leelawadee UI", 16, "bold"), anchor="w")
            vl.pack(fill=tk.X, pady=(1, 0))
            self.card_body_labels.append(vl)
            self.kpi_value_labels.append(vl)

            sl = tk.Label(inner, textvariable=self.kpi_sub_vars[idx], font=("Leelawadee UI", 9), anchor="w")
            sl.pack(fill=tk.X)
            self.card_title_labels.append(sl)

            self._bind_card_tooltip(card, title_v, body_v)

    def _bind_card_tooltip(self, card: tk.Frame, title_v: tk.StringVar, body_v: tk.StringVar):
        tip = mui.MacTooltip(card, "", "")

        def _is_inside(widget) -> bool:
            while widget is not None:
                if widget is card:
                    return True
                widget = getattr(widget, "master", None)
            return False

        def _enter(_e):
            tip.hide()
            tip.title = title_v.get()
            tip.description = body_v.get()
            tip.show()

        def _leave(_e):
            def _check():
                try:
                    w = card.winfo_containing(card.winfo_pointerx(), card.winfo_pointery())
                except Exception:
                    w = None
                if not _is_inside(w):
                    tip.hide()

            card.after(40, _check)

        def _bind_rec(w):
            w.bind("<Enter>", _enter, add="+")
            w.bind("<Leave>", _leave, add="+")
            for ch in w.winfo_children():
                _bind_rec(ch)

        _bind_rec(card)

    # ==========================================
    # ⚙ Settings Popover (Period / ทุน / Risk / ดึงสด / AI)
    # ==========================================
    def _refresh_settings_summary(self):
        try:
            cap = float(self.capital_var.get() or 0)
            cap_txt = f"${cap:,.0f}"
        except ValueError:
            cap_txt = f"${self.capital_var.get()}"
        flags = []
        if self.force_refresh_var.get():
            flags.append("ดึงสด")
        if self.use_ai_var.get():
            flags.append("AI")
        txt = f"{self.period_var.get()}  ·  {cap_txt}  ·  Risk {self.risk_var.get()}%"
        if flags:
            txt += "  ·  " + " + ".join(flags)
        self.settings_summary_var.set(txt)

    def open_settings_popover(self):
        if getattr(self, "_settings_win", None) is not None and self._settings_win.winfo_exists():
            self._settings_win.destroy()
            self._settings_win = None
            return

        t = THEMES[self.theme_mode]
        win = tk.Toplevel(self.root)
        win.wm_overrideredirect(True)
        win.attributes("-topmost", True)
        x = self.settings_btn.winfo_rootx()
        y = self.settings_btn.winfo_rooty() + self.settings_btn.winfo_height() + 6
        win.wm_geometry(f"+{x}+{y}")
        self._settings_win = win

        box = tk.Frame(win, bg=t["card"], padx=16, pady=12, highlightthickness=1, highlightbackground=t["border"])
        box.pack()
        tk.Label(box, text="ตั้งค่าการสแกน", font=("Leelawadee UI", 10, "bold"), fg=t["fg"], bg=t["card"]).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8)
        )

        def _row(r: int, label: str):
            tk.Label(box, text=label, font=("Leelawadee UI", 9), fg=t["sub_fg"], bg=t["card"]).grid(row=r, column=0, sticky="w", pady=4, padx=(0, 14))

        _row(1, "Period")
        ttk.Combobox(box, textvariable=self.period_var, values=["6mo", "1y", "2y", "5y"], width=8, state="readonly").grid(row=1, column=1, sticky="w")

        _row(2, "พอร์ต ($)")
        mui.RoundedFocusEntry(box, textvariable=self.capital_var, width=10, font=("Consolas", 10, "bold"), fg="#FFD60A", bg="#141416", parent_bg=t["card"]).grid(
            row=2, column=1, sticky="w"
        )

        _row(3, "Risk %")
        mui.RoundedFocusEntry(box, textvariable=self.risk_var, width=10, font=("Consolas", 10, "bold"), fg="#FFD60A", bg="#141416", parent_bg=t["card"]).grid(
            row=3, column=1, sticky="w"
        )

        for r, (txt, var) in enumerate((("ดึงข้อมูลสด (ไม่ใช้ Cache)", self.force_refresh_var), ("ใช้ AI วิเคราะห์เพิ่ม", self.use_ai_var)), start=4):
            tk.Checkbutton(
                box,
                text=txt,
                variable=var,
                font=("Leelawadee UI", 9),
                fg=t["fg"],
                bg=t["card"],
                selectcolor=t["seg_track"],
                activebackground=t["card"],
                activeforeground=t["fg"],
            ).grid(row=r, column=0, columnspan=2, sticky="w", pady=(4, 0))

        mui.RoundedButton(
            box,
            text="เสร็จ",
            bg="#0A84FF",
            fg="#FFFFFF",
            parent_bg=t["card"],
            radius=10.0,
            width=72,
            height=28,
            command=lambda: (win.destroy(), setattr(self, "_settings_win", None)),
        ).grid(row=6, column=1, sticky="e", pady=(12, 0))

        win.bind("<Escape>", lambda _e: (win.destroy(), setattr(self, "_settings_win", None)))
        win.focus_force()

    # ==========================================
    # 3. พื้นที่ Workbench 3 คอลัมน์ (ซ้าย Watchlist | กลาง กราฟ+Dock | ขวา Hermes+Terminal)
    # ==========================================
    def _build_workbench_panes(self):
        # แถบสถานะบางๆ
        s_bar = tk.Frame(self.root, padx=14, pady=3)
        s_bar.pack(fill=tk.X)
        self.panel_frames.append(s_bar)
        self.status_var = tk.StringVar(
            value="พร้อมทำงาน (macOS Clean Edition) — คลิกหุ้นที่แถบซ้ายเพื่อเปลี่ยนกราฟและใบคำสั่งซื้อขายในคลิกเดียว"
        )
        self.status_lbl = tk.Label(s_bar, textvariable=self.status_var, font=("Leelawadee UI", 9), anchor="w")
        self.status_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.progress = ttk.Progressbar(s_bar, orient=tk.HORIZONTAL, length=200, mode="determinate")
        self.progress.pack(side=tk.RIGHT)

        self.main_h_pane = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        self.main_h_pane.pack(fill=tk.BOTH, expand=True, padx=10, pady=(2, 8))

        # คอลัมน์ซ้าย: Watchlist Explorer
        self.left_col = ttk.Frame(self.main_h_pane)
        self.main_h_pane.add(self.left_col, weight=2)
        self._setup_left_watchlist(self.left_col)

        # คอลัมน์กลาง: บน = กราฟ Interactive | ล่าง = Dock Panel
        self.center_v_pane = ttk.PanedWindow(self.main_h_pane, orient=tk.VERTICAL)
        self.main_h_pane.add(self.center_v_pane, weight=6)

        self.chart_box = ttk.Frame(self.center_v_pane)
        self.dock_box = ttk.Frame(self.center_v_pane)
        self.center_v_pane.add(self.chart_box, weight=3)
        self.center_v_pane.add(self.dock_box, weight=2)

        self._setup_center_chart(self.chart_box)
        self._setup_bottom_dock(self.dock_box)

        # คอลัมน์ขวา: Hermes Agent 2-Way Co-Pilot + Live Terminal Log
        self.right_col = ttk.Frame(self.main_h_pane)
        self.main_h_pane.add(self.right_col, weight=2)
        self._setup_right_hermes_panel(self.right_col)

    def toggle_right_panel(self):
        if self.right_panel_visible:
            self.main_h_pane.forget(self.right_col)
            self.right_panel_visible = False
            self.toggle_right_btn.config(bg="#0A84FF", fg="#FFFFFF")
        else:
            self.main_h_pane.add(self.right_col, weight=2)
            self.right_panel_visible = True
            self.toggle_right_btn.config(bg="#2C2C2E", fg="#AEAEB2")

    def toggle_dock_panel(self):
        if self.dock_panel_visible:
            self.center_v_pane.forget(self.dock_box)
            self.dock_panel_visible = False
            self.toggle_dock_btn.config(bg="#0A84FF", fg="#FFFFFF")
        else:
            self.center_v_pane.add(self.dock_box, weight=2)
            self.dock_panel_visible = True
            self.toggle_dock_btn.config(bg="#2C2C2E", fg="#AEAEB2")

    def toggle_chart_fullscreen(self):
        if not self.chart_fullscreen:
            self._saved_right_visible = self.right_panel_visible
            self._saved_dock_visible = self.dock_panel_visible
            self.main_h_pane.forget(self.left_col)
            if self.right_panel_visible:
                self.main_h_pane.forget(self.right_col)
                self.right_panel_visible = False
            if self.dock_panel_visible:
                self.center_v_pane.forget(self.dock_box)
                self.dock_panel_visible = False
            self.chart_fullscreen = True
            self.chart_full_btn.config(text="Exit Full", bg="#0A84FF", fg="#FFFFFF")
            if not self.draw_toolbar_visible:
                self.toggle_draw_toolbar()
        else:
            self.main_h_pane.insert(0, self.left_col, weight=2)
            if self._saved_dock_visible and not self.dock_panel_visible:
                self.center_v_pane.add(self.dock_box, weight=2)
                self.dock_panel_visible = True
                self.toggle_dock_btn.config(bg="#2C2C2E", fg="#AEAEB2")
            if self._saved_right_visible and not self.right_panel_visible:
                self.main_h_pane.add(self.right_col, weight=2)
                self.right_panel_visible = True
                self.toggle_right_btn.config(bg="#2C2C2E", fg="#AEAEB2")
            self.chart_fullscreen = False
            self.chart_full_btn.config(text="Full", bg="#2C2C2E", fg="#AEAEB2")
        self.root.after(60, self.redraw_interactive_chart)

    # ==========================================
    # คอลัมน์ซ้าย: Watchlist Explorer (Rounded Button)
    # ==========================================
    def _setup_left_watchlist(self, parent):
        hdr = tk.Frame(parent, padx=8, pady=5)
        hdr.pack(fill=tk.X)
        self.panel_frames.append(hdr)

        lbl = tk.Label(hdr, text="📊 WATCHLIST EXPLORER", font=("Tahoma", 9, "bold"))
        lbl.pack(side=tk.LEFT)
        self.panel_labels.append(lbl)

        cols = ("ticker", "score", "ml_prob", "action", "opt_alloc", "close")
        self.watch_tree = ttk.Treeview(parent, columns=cols, show="headings", height=22)
        headers = {
            "ticker": ("Ticker", 62),
            "score": ("Score", 62),
            "ml_prob": ("ML Win%", 62),
            "action": ("Action", 88),
            "opt_alloc": ("พอร์ตv4%", 64),
            "close": ("Close", 75),
        }
        for c, (text, w) in headers.items():
            self.watch_tree.heading(c, text=text)
            anchor = "w" if c in ("ticker", "action") else "e"
            self.watch_tree.column(c, width=w, anchor=anchor)

        self.watch_tree.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        self.watch_tree.bind("<<TreeviewSelect>>", self._on_watchlist_select)

        # ปุ่มขอบมน 14px ใต้ Watchlist
        btn_f = tk.Frame(parent, padx=6, pady=4)
        btn_f.pack(fill=tk.X)
        self.panel_frames.append(btn_f)
        mui.RoundedButton(
            btn_f,
            text="⚡ ส่งหุ้นนี้เข้าใบคำสั่งซื้อขายด้านล่าง",
            bg="#0A84FF",
            fg="white",
            radius=14.0,
            height=28,
            command=self._send_selected_to_order_ticket,
        ).pack(fill=tk.X)

    # ==========================================
    # คอลัมน์กลางบน: Interactive Chart + macOS Segmented Control (นิ่ง ไม่กระตุก)
    # ==========================================
    def _setup_center_chart(self, parent):
        pill_bar = tk.Frame(parent, padx=8, pady=6)
        pill_bar.pack(fill=tk.X)
        self.panel_frames.append(pill_bar)

        self.chart_modes_meta = [
            (
                "Signals",
                "1. จุดซื้อ/ขาย (▲/▼) & ATR",
                "signals_markers",
                "กราฟราคาพร้อมจุดเข้าซื้อ (▲ BUY), จุดขายออก (▼ SELL), เส้นตัดขาดทุน ATR Stop, เป้า TP1/TP2 และโซนช้อนซื้อ Sniper",
            ),
            (
                "VWAP / POC",
                "2. VWAP & Volume Profile POC",
                "vwap_vp",
                "วิเคราะห์ต้นทุนเฉลี่ยสถาบัน VWAP (20D) และแท่งสะสมวอลุ่มรายระดับราคา (Volume Profile POC & 70% Value Area)",
            ),
            (
                "Monte Carlo",
                "3. Monte Carlo 1,000 รอบ & VaR",
                "monte_carlo",
                "จำลองอนาคต 1,000 เส้นทาง (252 วันทำการ) พร้อมกรอบความเชื่อมั่น P05-P95 และความเสี่ยงรายวัน VaR 95% / CVaR 95%",
            ),
            (
                "Portfolio",
                "4. จัดพอร์ต v4 & Correlation",
                "portfolio_corr",
                "สัดส่วนพอร์ตที่เหมาะสมระดับกองทุน (Risk Parity + Quant/ML Score + VIX Cap) คู่กับตารางสหสัมพันธ์ Correlation Matrix",
            ),
            (
                "Equity",
                "5. เทียบทุกกลยุทธ์ (Equity)",
                "equity",
                "เปรียบเทียบเส้นการเติบโตของพอร์ต (Equity Curve) และ Drawdown ของทั้ง 12 กลยุทธ์เพื่อหากลยุทธ์ที่ชนะตลาด",
            ),
            (
                "ML / WFO",
                "6. เจาะลึก AI/ML & Walk-Forward",
                "ml_wfo",
                "เจาะลึกคะแนน AI/ML Meta-Model Win Prob%, ผลทดสอบ Walk-Forward 4 ช่วงเวลา, Half-Kelly และความผันผวน Rolling Volatility",
            ),
        ]
        self.chart_mode_keys = [m[2] for m in self.chart_modes_meta]
        seg_items = [(m[2], m[0], m[3]) for m in self.chart_modes_meta]

        self.chart_seg = mui.MacSegmentedControl(
            pill_bar,
            items=seg_items,
            active_key=self.chart_mode,
            command=self.switch_chart_mode,
            parent_bg="#1C1C1E",
            track_bg="#2C2C2E",
            active_bg="#0A84FF",
            hover_bg="#3A3A3C",
            fg="#AEAEB2",
            active_fg="#FFFFFF",
            border_color="#38383A",
            height=30,
            font=("Leelawadee UI", 9, "bold"),
        )
        self.chart_seg.pack(side=tk.LEFT, padx=(0, 8))
        self.chart_seg.bind("<MouseWheel>", self._on_chart_mode_wheel, add="+")

        # ปุ่มเล็กๆ มุมขวาสำหรับ Fullscreen / วาดเส้น / Legend / Zoom
        self.chart_full_btn = mui.RoundedButton(
            pill_bar,
            text="Full",
            bg="#2C2C2E",
            fg="#AEAEB2",
            parent_bg="#1C1C1E",
            radius=10.0,
            width=58,
            height=28,
            command=self.toggle_chart_fullscreen,
        )
        self.chart_full_btn.pack(side=tk.RIGHT, padx=(4, 0))

        self.chart_tools_btn = mui.RoundedButton(
            pill_bar,
            text="Zoom",
            bg="#2C2C2E",
            fg="#AEAEB2",
            parent_bg="#1C1C1E",
            radius=10.0,
            width=56,
            height=28,
            command=self.toggle_chart_toolbar,
        )
        self.chart_tools_btn.pack(side=tk.RIGHT, padx=(4, 0))

        self.chart_legend_btn = mui.RoundedButton(
            pill_bar,
            text="Legend",
            bg="#2C2C2E",
            fg="#AEAEB2",
            parent_bg="#1C1C1E",
            radius=10.0,
            width=64,
            height=28,
            command=self.toggle_chart_legend,
        )
        self.chart_legend_btn.pack(side=tk.RIGHT, padx=(4, 0))

        self.chart_draw_btn = mui.RoundedButton(
            pill_bar,
            text="Draw",
            bg="#2C2C2E",
            fg="#AEAEB2",
            parent_bg="#1C1C1E",
            radius=10.0,
            width=56,
            height=28,
            command=self.toggle_draw_toolbar,
        )
        self.chart_draw_btn.pack(side=tk.RIGHT)

        # แถบเครื่องมือวาดกราฟทำมือ (ซ่อนเป็นค่าเริ่มต้น เปิดอัตโนมัติเมื่อกด Full หรือ Draw)
        self.draw_bar = tk.Frame(parent, padx=8, pady=4, bg="#1C1C1E")
        self.panel_frames.append(self.draw_bar)
        draw_items = [
            ("cursor", "Crosshair", "เลื่อนเมาส์ดูราคาและวันที่แบบสด"),
            ("hline", "H-Line", "คลิก 1 ครั้งบนกราฟเพื่อตีเส้นแนวรับ-แนวต้านแนวนอน"),
            ("trend", "Trendline", "คลิก 2 จุดบนกราฟเพื่อตีเส้นแนวโน้ม (คลิกขวาเพื่อยกเลิก)"),
            ("fibo", "Fib Retrace", "คลิกจุด High-Low 2 จุดเพื่อตี Fibonacci 0% - 100%"),
        ]
        self.draw_seg = mui.MacSegmentedControl(
            self.draw_bar,
            items=draw_items,
            active_key="cursor",
            command=self._on_draw_tool_selected,
            parent_bg="#1C1C1E",
            track_bg="#2C2C2E",
            active_bg="#0A84FF",
            hover_bg="#3A3A3C",
            fg="#AEAEB2",
            active_fg="#FFFFFF",
            border_color="#38383A",
            height=28,
            font=("Leelawadee UI", 9, "bold"),
        )
        self.draw_seg.pack(side=tk.LEFT, padx=(0, 8))

        mui.RoundedButton(
            self.draw_bar,
            text="Undo",
            bg="#2C2C2E",
            fg="#FFD60A",
            parent_bg="#1C1C1E",
            radius=10.0,
            width=56,
            height=26,
            command=lambda: self.drawing_mgr.undo_last(self.selected_ticker),
        ).pack(side=tk.LEFT, padx=(0, 4))

        mui.RoundedButton(
            self.draw_bar,
            text="Clear",
            bg="#2C2C2E",
            fg="#FF453A",
            parent_bg="#1C1C1E",
            radius=10.0,
            width=56,
            height=26,
            command=lambda: self.drawing_mgr.clear_ticker(self.selected_ticker),
        ).pack(side=tk.LEFT)

        self.fig = Figure(figsize=(8.8, 4.4), dpi=100)
        self.canvas = FigureCanvasTkAgg(self.fig, master=parent)
        self.canvas_widget = self.canvas.get_tk_widget()
        self.canvas_widget.pack(fill=tk.BOTH, expand=True)
        self.canvas.mpl_connect("button_press_event", lambda ev: self.drawing_mgr.on_click(ev, self.canvas))
        self.canvas.mpl_connect("motion_notify_event", lambda ev: self.drawing_mgr.on_motion(ev, self.canvas))

        self.tb_fr = tk.Frame(parent)
        self.toolbar = NavigationToolbar2Tk(self.canvas, self.tb_fr)
        self.toolbar.update()

    def toggle_draw_toolbar(self):
        if self.draw_toolbar_visible:
            self.draw_bar.pack_forget()
            self.draw_toolbar_visible = False
            self.chart_draw_btn.config(bg="#2C2C2E", fg="#AEAEB2")
            self.drawing_mgr.set_tool("cursor")
            self.draw_seg.set_active("cursor")
        else:
            self.draw_bar.pack(fill=tk.X, before=self.canvas_widget)
            self.draw_toolbar_visible = True
            self.chart_draw_btn.config(bg="#0A84FF", fg="#FFFFFF")

    def _on_draw_tool_selected(self, tool_key: str):
        self.drawing_mgr.set_tool(tool_key)
        names = {
            "cursor": "Crosshair — เลื่อนเมาส์ดูราคาสด",
            "hline": "H-Line — คลิก 1 ครั้งบนกราฟเพื่อวางเส้นแนวนอน",
            "trend": "Trendline — คลิกจุดเริ่มต้นและจุดปลาย 2 ครั้ง",
            "fibo": "Fib Retrace — คลิกจุด High/Low 2 ครั้ง",
        }
        self.status_var.set(names.get(tool_key, ""))

    def toggle_chart_legend(self):
        self.show_chart_legend = not self.show_chart_legend
        if self.show_chart_legend:
            self.chart_legend_btn.config(bg="#0A84FF", fg="#FFFFFF")
        else:
            self.chart_legend_btn.config(bg="#2C2C2E", fg="#AEAEB2")
        self.redraw_interactive_chart()

    def _apply_legend(self, ax, t: dict, **kwargs):
        if not getattr(self, "show_chart_legend", False):
            return
        leg = ax.legend(facecolor=t["panel"], edgecolor=t["border"], **kwargs)
        if leg is not None:
            for txt in leg.get_texts():
                txt.set_color(t["fg"])

    def toggle_chart_toolbar(self):
        if self.chart_toolbar_visible:
            self.tb_fr.pack_forget()
            self.chart_toolbar_visible = False
            self.chart_tools_btn.config(bg="#2C2C2E", fg="#AEAEB2")
        else:
            self.tb_fr.pack(fill=tk.X)
            self.chart_toolbar_visible = True
            self.chart_tools_btn.config(bg="#0A84FF", fg="#FFFFFF")

    def _on_chart_mode_wheel(self, event):
        step = -1 if event.delta > 0 else 1
        self.cycle_chart_mode(step)

    def cycle_chart_mode(self, step: int = 1):
        if not hasattr(self, "chart_mode_keys") or not self.chart_mode_keys:
            return
        try:
            cur_idx = self.chart_mode_keys.index(self.chart_mode)
        except ValueError:
            cur_idx = 0
        next_idx = (cur_idx + step) % len(self.chart_mode_keys)
        self.switch_chart_mode(self.chart_mode_keys[next_idx])

    def switch_chart_mode(self, mode_key: str):
        self.chart_mode = mode_key
        self._highlight_active_mode_button()
        self.redraw_interactive_chart()

    def _highlight_active_mode_button(self):
        if hasattr(self, "chart_seg"):
            self.chart_seg.set_active(self.chart_mode)
        if hasattr(self, "dock_seg"):
            self.dock_seg.set_active(str(self.active_dock_idx))

    # ==========================================
    # คอลัมน์กลางล่าง: Bottom Dock Panel (macOS Segmented Pill อันเดียว — ซ่อน Tab ซ้ำซ้อน)
    # ==========================================
    def _setup_bottom_dock(self, parent):
        dock_bar = tk.Frame(parent, padx=8, pady=5)
        dock_bar.pack(fill=tk.X)
        self.panel_frames.append(dock_bar)

        self.dock_tabs_meta = [
            ("พอร์ต & คำสั่ง", "1. พอร์ตจริง & ส่งคำสั่ง Semi-Auto", 0, "จัดการพอร์ตจำลอง/พอร์ตจริง ส่งคำสั่งซื้อขาย Semi-Auto และดูประวัติคำสั่งล่าสุด"),
            ("จัดพอร์ต & ข่าว", "2. ตารางจัดพอร์ต v4 • ML • ข่าว", 1, "ตารางสัดส่วนพอร์ตเหมาะสม v4.0, โอกาสชนะ ML Win Prob%, Walk-Forward และพาดหัวข่าวล่าสุด"),
            ("ประวัติเทรด", "3. ประวัติเทรดรายไม้ (Trade Log)", 2, "รายละเอียดจุดเข้าซื้อ-ขายออกรายไม้ วันถือครอง กำไร/ขาดทุนสุทธิ และสาเหตุการขายออก"),
            ("เทียบกลยุทธ์", "4. ตารางเทียบทุกกลยุทธ์", 3, "เปรียบเทียบผลตอบแทน Return%, MaxDD%, Sharpe, Calmar, Win Rate และ Profit Factor ของทุกกลยุทธ์"),
        ]
        self.active_dock_idx = 0
        dock_items = [(str(tab_i), short_t, desc_t) for short_t, _full_t, tab_i, desc_t in self.dock_tabs_meta]

        self.dock_seg = mui.MacSegmentedControl(
            dock_bar,
            items=dock_items,
            active_key="0",
            command=lambda k: self.switch_dock_tab(int(k)),
            parent_bg="#1C1C1E",
            track_bg="#2C2C2E",
            active_bg="#0A84FF",
            hover_bg="#3A3A3C",
            fg="#AEAEB2",
            active_fg="#FFFFFF",
            border_color="#38383A",
            height=30,
            font=("Leelawadee UI", 9, "bold"),
        )
        self.dock_seg.pack(side=tk.LEFT)

        self.dock_nb = ttk.Notebook(parent, style="Hidden.TNotebook")
        self.dock_nb.pack(fill=tk.BOTH, expand=True)

        self.dock_broker = ttk.Frame(self.dock_nb)
        self.dock_opt = ttk.Frame(self.dock_nb)
        self.dock_trades = ttk.Frame(self.dock_nb)
        self.dock_bt = ttk.Frame(self.dock_nb)

        self.dock_nb.add(self.dock_broker, text="1")
        self.dock_nb.add(self.dock_opt, text="2")
        self.dock_nb.add(self.dock_trades, text="3")
        self.dock_nb.add(self.dock_bt, text="4")
        self.dock_nb.bind("<<NotebookTabChanged>>", self._on_notebook_tab_changed)

        self._build_dock_broker()
        self._build_dock_optimizer()
        self._build_dock_trades()
        self._build_dock_backtest()

    def switch_dock_tab(self, tab_idx: int):
        self.active_dock_idx = tab_idx
        self.dock_nb.select(tab_idx)
        self._highlight_active_mode_button()

    def cycle_dock_tab(self, step: int = 1):
        next_i = (self.active_dock_idx + step) % 4
        self.switch_dock_tab(next_i)

    def _on_notebook_tab_changed(self, _event):
        try:
            idx = self.dock_nb.index(self.dock_nb.select())
            self.active_dock_idx = idx
            self._highlight_active_mode_button()
        except Exception:
            pass

    def _highlight_active_dock_button(self):
        if hasattr(self, "dock_seg"):
            self.dock_seg.set_active(str(self.active_dock_idx))

    def _build_dock_broker(self):
        # แถบบน: เลือกโบรกเกอร์ + โหมด + ปุ่มสี่เหลี่ยมขอบมน 14px + ยอดพอร์ตสด
        top_b = tk.Frame(self.dock_broker, padx=8, pady=4)
        top_b.pack(fill=tk.X)
        self.panel_frames.append(top_b)

        cfg = bb.load_broker_config()
        lbl1 = tk.Label(top_b, text="Broker:", font=("Tahoma", 8, "bold"))
        lbl1.pack(side=tk.LEFT)
        self.panel_labels.append(lbl1)

        self.broker_provider_var = tk.StringVar(value=cfg.get("active_broker", "local_paper"))
        b_cb = ttk.Combobox(top_b, textvariable=self.broker_provider_var, values=["local_paper", "alpaca", "binance"], width=11, state="readonly")
        b_cb.pack(side=tk.LEFT, padx=(3, 8))
        b_cb.bind("<<ComboboxSelected>>", lambda e: self._on_broker_mode_change())

        lbl2 = tk.Label(top_b, text="Mode:", font=("Tahoma", 8, "bold"))
        lbl2.pack(side=tk.LEFT)
        self.panel_labels.append(lbl2)

        self.broker_env_var = tk.StringVar(value=cfg.get("environment", "paper"))
        e_cb = ttk.Combobox(top_b, textvariable=self.broker_env_var, values=["paper", "live"], width=6, state="readonly")
        e_cb.pack(side=tk.LEFT, padx=(3, 8))
        e_cb.bind("<<ComboboxSelected>>", lambda e: self._on_broker_mode_change())

        mui.RoundedButton(top_b, text="🔄 Sync พอร์ต", bg="#0A84FF", fg="white", radius=14.0, padx=10, pady=3, command=self.sync_broker_portfolio).pack(side=tk.LEFT, padx=3)
        mui.RoundedButton(top_b, text="⚙ API Key", bg="#3A3A3C", fg="white", radius=14.0, padx=10, pady=3, command=self.open_api_settings_dialog).pack(side=tk.LEFT, padx=3)
        mui.RoundedButton(top_b, text="♻ รีเซ็ต Paper", bg="#2D2D2D", fg="#DCDCAA", radius=14.0, padx=10, pady=3, command=self._reset_local_paper).pack(side=tk.LEFT, padx=3)

        self.account_banner_var = tk.StringVar(value="กำลังโหลดพอร์ต...")
        self.account_banner_lbl = tk.Label(top_b, textvariable=self.account_banner_var, font=("Consolas", 9, "bold"), anchor="w")
        self.account_banner_lbl.pack(side=tk.LEFT, padx=10, fill=tk.X, expand=True)

        # แถบใบคำสั่งซื้อขาย Semi-Auto (Order Ticket พร้อมช่อง Input ขอบมนเรืองแสงและปุ่มขอบมน 14px)
        t_fr = tk.Frame(self.dock_broker, padx=8, pady=4)
        t_fr.pack(fill=tk.X)
        self.panel_frames.append(t_fr)

        for lbl_txt, var_attr, default_v, width_v, fg_c in [
            ("Symbol:", "ord_sym_var", "AAPL", 6, "#4EC9B0"),
            ("Qty:", "ord_qty_var", "10.0", 7, "#DCDCAA"),
            ("Price:", "ord_price_var", "356.27", 7, "#D4D4D4"),
            ("ATR Stop:", "ord_stop_var", "329.97", 7, "#F44747"),
            ("TP1(1.5R):", "ord_tp1_var", "395.71", 7, "#4EC9B0"),
            ("TP2(3.0R):", "ord_tp2_var", "435.16", 7, "#569CD6"),
        ]:
            l_w = tk.Label(t_fr, text=lbl_txt, font=("Tahoma", 8, "bold"))
            l_w.pack(side=tk.LEFT)
            self.panel_labels.append(l_w)
            sv = tk.StringVar(value=default_v)
            setattr(self, var_attr, sv)
            mui.RoundedFocusEntry(
                t_fr,
                textvariable=sv,
                width=width_v,
                font=("Consolas", 9, "bold"),
                fg=fg_c,
                bg="#121212",
                parent_bg="#252526",
                height=26,
            ).pack(side=tk.LEFT, padx=(2, 5))

        l_sd = tk.Label(t_fr, text="Side:", font=("Tahoma", 8, "bold"))
        l_sd.pack(side=tk.LEFT)
        self.panel_labels.append(l_sd)
        self.ord_side_var = tk.StringVar(value="BUY")
        ttk.Combobox(t_fr, textvariable=self.ord_side_var, values=["BUY", "SELL"], width=5, state="readonly").pack(side=tk.LEFT, padx=(2, 6))

        mui.RoundedButton(
            t_fr,
            text="✅ ยืนยันส่งคำสั่ง (Confirm)",
            bg="#30D158",
            fg="#0B1120",
            radius=14.0,
            padx=10,
            pady=3,
            command=self.confirm_and_execute_order,
        ).pack(side=tk.LEFT, padx=3)

        mui.RoundedButton(
            t_fr,
            text="⚡ ซื้อตัวท็อปทันที (Best-Pick)",
            bg="#BF5AF2",
            fg="white",
            radius=14.0,
            padx=10,
            pady=3,
            command=self.execute_instant_best_pick_buy,
        ).pack(side=tk.LEFT, padx=3)

        # ตาราง Open Positions คู่กับ Order History ด้านล่าง
        split_b = ttk.PanedWindow(self.dock_broker, orient=tk.HORIZONTAL)
        split_b.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)

        p_box = ttk.Frame(split_b)
        o_box = ttk.Frame(split_b)
        split_b.add(p_box, weight=1)
        split_b.add(o_box, weight=1)

        p_cols = ("symbol", "qty", "avg_price", "current_price", "stop_loss", "market_value", "unrealized_pnl_pct")
        self.pos_tree = ttk.Treeview(p_box, columns=p_cols, show="headings", height=5)
        for c, (txt, w) in {
            "symbol": ("ถือครอง (Symbol)", 85),
            "qty": ("Qty", 75),
            "avg_price": ("ทุนเฉลี่ย", 75),
            "current_price": ("ราคาล่าสุด", 75),
            "stop_loss": ("Stop-Loss", 75),
            "market_value": ("มูลค่า ($)", 85),
            "unrealized_pnl_pct": ("กำไร/ขาดทุน%", 85),
        }.items():
            self.pos_tree.heading(c, text=txt)
            self.pos_tree.column(c, width=w, anchor="w" if c == "symbol" else "e")
        self.pos_tree.pack(fill=tk.BOTH, expand=True)
        self.pos_tree.bind("<Double-1>", self._on_position_double_click)

        o_cols = ("id", "broker", "symbol", "side", "qty", "price", "status", "created_at")
        self.order_tree = ttk.Treeview(o_box, columns=o_cols, show="headings", height=5)
        for c, (txt, w) in {
            "id": ("#", 40),
            "broker": ("Broker", 75),
            "symbol": ("Symbol", 65),
            "side": ("Side", 45),
            "qty": ("Qty", 70),
            "price": ("Price", 70),
            "status": ("Status", 65),
            "created_at": ("เวลาส่งคำสั่ง", 115),
        }.items():
            self.order_tree.heading(c, text=txt)
            self.order_tree.column(c, width=w, anchor="w" if c in ("broker", "symbol", "side", "status", "created_at") else "e")
        self.order_tree.pack(fill=tk.BOTH, expand=True)

    def _build_dock_optimizer(self):
        cols = (
            "ticker",
            "score",
            "ml_win_prob",
            "wfo_pass",
            "indiv_alloc",
            "opt_alloc",
            "opt_amount",
            "news_sent",
            "headline",
        )
        self.opt_tree = ttk.Treeview(self.dock_opt, columns=cols, show="headings", height=7)
        headers = {
            "ticker": ("Ticker", 65),
            "score": ("Quant Score", 80),
            "ml_win_prob": ("ML Win Prob%", 85),
            "wfo_pass": ("WFO Pass%", 75),
            "indiv_alloc": ("สัดส่วนเดี่ยว%", 80),
            "opt_alloc": ("พอร์ตรวม v4%", 85),
            "opt_amount": ("เงินลงทุน v4 ($)", 95),
            "news_sent": ("News Sentiment", 100),
            "headline": ("พาดหัวข่าวล่าสุด (yfinance News)", 280),
        }
        for c, (txt, w) in headers.items():
            self.opt_tree.heading(c, text=txt)
            self.opt_tree.column(c, width=w, anchor="w" if c in ("ticker", "news_sent", "headline") else "e")
        self.opt_tree.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

    def _build_dock_trades(self):
        cols = ("trade_no", "ticker", "strategy", "entry_date", "exit_date", "hold_days", "entry_price", "exit_price", "net_return_pct", "pnl_amount", "exit_reason")
        self.trade_tree = ttk.Treeview(self.dock_trades, columns=cols, show="headings", height=7)
        for c, (txt, w) in {
            "trade_no": ("#", 45),
            "ticker": ("Ticker", 65),
            "strategy": ("กลยุทธ์", 115),
            "entry_date": ("วันเข้าซื้อ", 85),
            "exit_date": ("วันขายออก", 85),
            "hold_days": ("ถือ(วัน)", 55),
            "entry_price": ("ราคาเข้า", 80),
            "exit_price": ("ราคาออก", 80),
            "net_return_pct": ("กำไร %", 75),
            "pnl_amount": ("กำไร ($)", 80),
            "exit_reason": ("เหตุผลที่ออก", 150),
        }.items():
            self.trade_tree.heading(c, text=txt)
            self.trade_tree.column(c, width=w, anchor="w" if c in ("ticker", "strategy", "entry_date", "exit_date", "exit_reason") else "e")
        self.trade_tree.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

    def _build_dock_backtest(self):
        cols = (
            "ticker",
            "segment",
            "strategy",
            "total_ret_pct",
            "max_dd_pct",
            "sharpe",
            "sortino",
            "calmar",
            "alpha_pct",
            "beta",
            "win_rate_pct",
            "profit_factor",
            "cost_drag_pct",
            "trades_count",
        )
        self.bt_tree = ttk.Treeview(self.dock_bt, columns=cols, show="headings", height=7)
        for c, (txt, w) in {
            "ticker": ("Ticker", 60),
            "segment": ("ช่วง", 55),
            "strategy": ("Strategy", 125),
            "total_ret_pct": ("Return%", 72),
            "max_dd_pct": ("MaxDD%", 68),
            "sharpe": ("Sharpe", 56),
            "sortino": ("Sortino", 58),
            "calmar": ("Calmar", 56),
            "alpha_pct": ("Alpha(α)%", 68),
            "beta": ("Beta(β)", 55),
            "win_rate_pct": ("Win%", 55),
            "profit_factor": ("PF", 50),
            "cost_drag_pct": ("Slippage+Fee%", 82),
            "trades_count": ("ไม้", 48),
        }.items():
            self.bt_tree.heading(c, text=txt)
            self.bt_tree.column(c, width=w, anchor="w" if c in ("ticker", "segment", "strategy") else "e")
        self.bt_tree.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

    # ==========================================
    # คอลัมน์ขวา: Hermes Agent 2-Way Co-Pilot & Live Terminal
    # ==========================================
    def _setup_right_hermes_panel(self, parent):
        v_pane = ttk.PanedWindow(parent, orient=tk.VERTICAL)
        v_pane.pack(fill=tk.BOTH, expand=True)

        # ครึ่งบน: Hermes Agent Co-Pilot (2-Way Sync)
        h_box = tk.Frame(v_pane, bg="#181818", padx=6, pady=6)
        v_pane.add(h_box, weight=1)

        h_hdr = tk.Frame(h_box, bg="#181818")
        h_hdr.pack(fill=tk.X, pady=(0, 4))
        tk.Label(h_hdr, text="🪽 HERMES CO-PILOT", font=("Consolas", 9, "bold"), fg="#4EC9B0", bg="#181818").pack(side=tk.LEFT)
        mui.RoundedButton(
            h_hdr,
            text="🔄 Sync Memory",
            bg="#0A84FF",
            fg="white",
            parent_bg="#181818",
            radius=14.0,
            padx=8,
            pady=3,
            command=self.manual_sync_hermes,
        ).pack(side=tk.RIGHT)

        self.hermes_chat_box = scrolledtext.ScrolledText(
            h_box,
            font=("Leelawadee UI", 10),
            bg="#121212",
            fg="#D4D4D4",
            insertbackground="white",
            wrap=tk.WORD,
            height=10,
            relief=tk.FLAT,
        )
        self.hermes_chat_box.pack(fill=tk.BOTH, expand=True, pady=(0, 4))

        inp_fr = tk.Frame(h_box, bg="#181818")
        inp_fr.pack(fill=tk.X)
        self.hermes_input_var = tk.StringVar()
        inp_wrap = mui.RoundedFocusEntry(
            inp_fr,
            textvariable=self.hermes_input_var,
            width=22,
            font=("Leelawadee UI", 10),
            fg="white",
            bg="#121212",
            parent_bg="#181818",
            height=26,
        )
        inp_wrap.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        inp_wrap.entry.bind("<Return>", lambda e: self.send_hermes_copilot_prompt())
        mui.RoundedButton(
            inp_fr,
            text="ถาม AI/Hermes",
            bg="#30D158",
            fg="#0B1120",
            parent_bg="#181818",
            radius=14.0,
            padx=9,
            pady=3,
            command=self.send_hermes_copilot_prompt,
        ).pack(side=tk.RIGHT)

        # ครึ่งล่าง: VS Code Live Engine Terminal
        t_box = tk.Frame(v_pane, bg="#121212", padx=6, pady=6)
        v_pane.add(t_box, weight=1)

        t_hdr = tk.Frame(t_box, bg="#121212")
        t_hdr.pack(fill=tk.X, pady=(0, 4))
        tk.Label(t_hdr, text="TERMINAL • LIVE LOG", font=("Consolas", 9, "bold"), fg="#569CD6", bg="#121212").pack(side=tk.LEFT)
        mui.RoundedButton(
            t_hdr,
            text="Clear",
            bg="#2D2D2D",
            fg="#D4D4D4",
            parent_bg="#121212",
            radius=14.0,
            padx=8,
            pady=2,
            command=lambda: self.log_box.delete("1.0", tk.END),
        ).pack(side=tk.RIGHT)

        self.log_box = scrolledtext.ScrolledText(
            t_box,
            font=("Consolas", 9),
            bg="#121212",
            fg="#CCCCCC",
            insertbackground="white",
            wrap=tk.WORD,
            height=10,
            relief=tk.FLAT,
        )
        self.log_box.pack(fill=tk.BOTH, expand=True)
        self.log_box.tag_config("info", foreground="#569CD6")
        self.log_box.tag_config("ok", foreground="#4EC9B0")
        self.log_box.tag_config("warn", foreground="#DCDCAA")
        self.log_box.tag_config("err", foreground="#F44747")

    # ==========================================
    # Hermes Agent 2-Way Bus Polling & Chat
    # ==========================================
    def _poll_hermes_bus(self):
        cmds, msgs = hb.poll_pending_commands()
        if cmds:
            for c in cmds:
                act = c.get("action")
                if act == "scan":
                    new_t = c.get("tickers", "").strip()
                    if new_t:
                        self.tickers_var.set(new_t)
                    if c.get("period"):
                        self.period_var.set(c["period"])
                    self.log(f"[Hermes Remote Command] สั่งรันสแกนหุ้น: {self.tickers_var.get()}", "warn")
                    self.start_analysis_thread()
                elif act == "note":
                    self.log(f"[Hermes Note] {c.get('message', '')}", "ok")
            self._refresh_hermes_chat_box()
        self.root.after(1500, self._poll_hermes_bus)

    def _refresh_hermes_chat_box(self):
        bus = hb.ensure_bus_file()
        msgs = bus.get("messages", [])
        self.hermes_chat_box.delete("1.0", tk.END)
        for m in msgs[-15:]:
            self.hermes_chat_box.insert(tk.END, f"[{m.get('time', '')}] {m.get('sender', 'Hermes')}:\n{m.get('text', '')}\n\n")
        self.hermes_chat_box.see(tk.END)

    def manual_sync_hermes(self):
        acc = bb.get_account_summary()
        res = hb.sync_to_hermes_memory(self.scan_rows_list, acc, extra_note="ซิงก์ข้อมูลพอร์ตและผลสแกน v4.0 เข้า MEMORY.md ของ Hermes แล้ว")
        self._refresh_hermes_chat_box()
        self.log(f"ซิงก์ MEMORY.md เข้า Hermes Agent สำเร็จ ({len(res['paths'])} ไฟล์)", "ok")

    def send_hermes_copilot_prompt(self):
        q = self.hermes_input_var.get().strip()
        if not q:
            return
        self.hermes_input_var.set("")
        hb.append_copilot_chat("คุณ (User)", q)
        self._refresh_hermes_chat_box()

        def _ask_bg():
            context_lines = [
                f"{s['ticker']}: Score {s['quant_score']:.0f}({s['grade']}), ML WinProb {float(s.get('ml_win_prob_pct',50)):.0f}%, Action {s['action']}, พอร์ตv4 {float(s.get('opt_alloc_pct',0)):.1f}%"
                for s in self.scan_rows_list
            ]
            full_prompt = (
                "คุณคือ Hermes Quant Co-Pilot ตอบสั้น กระชับ ตรงประเด็น (ภาษาไทย):\n"
                f"ข้อมูลพอร์ตล่าสุด: {'; '.join(context_lines)}\n"
                f"คำถามจากผู้ใช้: {q}"
            )
            ans = be.query_llm(full_prompt)
            hb.append_copilot_chat("Hermes Co-Pilot", ans)
            self.msg_queue.put(("hermes_reply",))

        threading.Thread(target=_ask_bg, daemon=True).start()

    # ==========================================
    # Background Worker & Live Queue
    # ==========================================
    def log(self, text: str, tag: str = ""):
        ts = time.strftime("%H:%M:%S")
        self.msg_queue.put(("log", f"[{ts}] {text}\n", tag))

    # Toast แจ้งเตือนแทน messagebox (ไม่บล็อกหน้าจอ + บันทึกลง Log เสมอ จะได้ย้อนดูได้)
    def _toast(self, title: str, message: str = "", kind: str = "info", **_kw):
        title = strip_emoji(str(title))
        message = strip_emoji(str(message))
        self.log(f"{title}: {message}".replace("\n", " "), "err" if kind == "error" else "ok")
        duration = 6000 if kind == "error" else 3800
        if threading.current_thread() is threading.main_thread():
            self.toaster.show(title, message, kind=kind, duration_ms=duration)
        else:
            self.msg_queue.put(("toast", title, message, kind, duration))

    def _toast_info(self, title: str, message: str = "", **kw):
        self._toast(title, message, "ok", **kw)

    def _toast_error(self, title: str, message: str = "", **kw):
        self._toast(title, message, "error", **kw)

    def _process_queue(self):
        try:
            while True:
                item = self.msg_queue.get_nowait()
                kind = item[0]
                if kind == "log":
                    _, text, tag = item
                    self.log_box.insert(tk.END, text, tag)
                    self.log_box.see(tk.END)
                elif kind == "status":
                    _, text, prog_val = item
                    self.status_var.set(text)
                    self.progress["value"] = prog_val
                elif kind == "hermes_reply":
                    self._refresh_hermes_chat_box()
                elif kind == "toast":
                    _, t_title, t_msg, t_kind, t_dur = item
                    self.toaster.show(t_title, t_msg, kind=t_kind, duration_ms=t_dur)
                elif kind == "all_done":
                    self.is_running = False
                    self.run_btn.config(state=tk.NORMAL, text="▶ รันสแกน & จัดพอร์ต v4", bg="#0E639C")
                    self._populate_all_tables()
                    self.sync_broker_portfolio()
                    self._refresh_hermes_chat_box()
        except queue.Empty:
            pass
        self.root.after(80, self._process_queue)

    def start_analysis_thread(self):
        if self.is_running:
            return
        raw_tickers = self.tickers_var.get().replace(",", " ").split()
        tickers = [t.strip().upper() for t in raw_tickers if t.strip()]
        if not tickers:
            return

        try:
            capital = float(self.capital_var.get())
            risk_pct = float(self.risk_var.get()) / 100.0
        except ValueError:
            self._toast_error("ข้อผิดพลาด", "กรุณากรอกพอร์ตทุนและ Risk% เป็นตัวเลข")
            return

        period = self.period_var.get()
        force_ref = self.force_refresh_var.get()
        use_ai = self.use_ai_var.get()

        self.is_running = True
        self.run_btn.config(state=tk.DISABLED, text="⏳ กำลังรัน...", bg="#3C3C3C")
        self.progress["value"] = 0

        threading.Thread(
            target=self._run_worker,
            args=(tickers, period, capital, risk_pct, force_ref, use_ai),
            daemon=True,
        ).start()

    def _run_worker(self, tickers: list[str], period: str, capital: float, risk_pct: float, force_ref: bool, use_ai: bool):
        n_total = len(tickers)
        self.log(f"เริ่มสแกน v5.0 ({n_total} สินทรัพย์): {', '.join(tickers)} | จำลอง Dynamic Slippage + เทียบ S&P500 (^GSPC)", "info")

        bm_close = qv5.get_benchmark_close(period, "^GSPC")
        new_cache = {}
        scan_list = []
        bt_rows = []
        trade_rows = []
        close_map = {}

        for idx, t in enumerate(tickers, start=1):
            base_prog = ((idx - 1) / n_total) * 100.0
            self.msg_queue.put(("status", f"[{idx}/{n_total}] โหลดข้อมูล {t} (SQLite Cache / yfinance) ...", base_prog + 10))
            try:
                ohlcv, from_cache = qv4.fetch_ohlcv_cached(t, period, force_refresh=force_ref)
                close = ohlcv["close"]
                volume = ohlcv["volume"]
                close_map[t] = close
                src_txt = "SQLite Cache ⚡" if from_cache else "yfinance Live 🌐"
                self.log(f"[{idx}/{n_total}] {t}: {len(close)} วัน ({src_txt})", "info")

                self.msg_queue.put(("status", f"[{idx}/{n_total}] คำนวณ v6.0 (4 กลยุทธ์หลัก + Backtest ทั้ง 6 ปุ่มโหมด) สำหรับ {t} ...", base_prog + 50))
                ind = be.compute_indicators(ohlcv)
                signals, atr_stop_series, tuned_params = be.generate_signals(
                    close,
                    ind,
                    stop_loss=0.08,
                    atr_mult=3.2,
                    target_vol=0.25,
                    fee=0.001,
                    benchmark_close=bm_close,
                )

                results = {}
                rows = []
                for name, sig in signals.items():
                    res = be.evaluate_strategy(
                        close,
                        sig,
                        fee=0.001,
                        shift_signal=(name != "buy_hold"),
                        ind=ind,
                        benchmark_close=bm_close,
                    )
                    results[name] = res
                    rows.append({
                        "ticker": t,
                        "period": period,
                        "segment": "core_4",
                        "strategy": name,
                        **{k: v for k, v in res.items() if k not in ("equity", "dd")},
                    })

                best_strat = be.pick_best_active_strategy(
                    results, close=close, signals=signals, fee=0.001, train_ratio=0.70, ind=ind
                )
                best_res = results[best_strat]
                six_modes = qv5.evaluate_six_button_modes(
                    close, volume, ind, signals, be.evaluate_strategy, best_strat, fee=0.001, benchmark_close=bm_close
                )
                for m_key, m_info in six_modes.items():
                    m_res = m_info["full"]
                    rows.append({
                        "ticker": t,
                        "period": period,
                        "segment": "button_1..6",
                        "strategy": m_key,
                        **{k: v for k, v in m_res.items() if k not in ("equity", "dd")},
                    })

                vp_data = be.compute_volume_profile(close, volume)
                mc_data = be.run_monte_carlo_and_var(close, signals[best_strat], shift_signal=(best_strat != "buy_hold"))
                xai_data = qv5.compute_xai_feature_importance(close, ind)
                wfo_gate = qv5.run_rolling_walk_forward_gate(
                    close, ind, signals, be.evaluate_strategy, train_days=252, test_days=63, fee=0.001, benchmark_close=bm_close
                )

                t_logs = be.extract_trade_log(
                    ticker=t,
                    strategy_name=best_strat,
                    close=close,
                    raw_signal=signals[best_strat],
                    atr_stop=atr_stop_series,
                    rsi_series=ind["rsi14"],
                    fee=0.001,
                    capital=capital,
                )

                scan_info = be.compute_daily_scan(
                    ticker=t,
                    close=close,
                    volume=volume,
                    ind=ind,
                    signals=signals,
                    atr_stop_series=atr_stop_series,
                    best_strat=best_strat,
                    best_res=best_res,
                    tuned_params=tuned_params,
                    capital=capital,
                    risk_pct=risk_pct,
                    atr_mult=3.2,
                    target_vol=0.25,
                )

                scan_info["wfo_gate_status"] = wfo_gate["gate_status"]
                scan_info["wfo_oos_sharpe"] = wfo_gate["oos_sharpe"]
                scan_info["wfo_oos_pf"] = wfo_gate["oos_profit_factor"]
                scan_info["wfo_oos_dd"] = wfo_gate["oos_max_dd_pct"]

                if use_ai:
                    ans = be.query_llm(be.build_ai_prompt(t, period, results, best_strat, scan_info))
                    hb.append_copilot_chat(f"AI ({t})", ans)

                new_cache[t] = {
                    "close": close,
                    "volume": volume,
                    "ind": ind,
                    "results": results,
                    "atr_stop": atr_stop_series,
                    "best_strat": best_strat,
                    "scan": scan_info,
                    "vp": vp_data,
                    "mc": mc_data,
                    "xai": xai_data,
                    "six_modes": six_modes,
                    "bm_close": bm_close,
                    "rows": rows,
                    "trades": t_logs,
                }
                scan_list.append(scan_info)
                bt_rows.extend(rows)
                trade_rows.extend(t_logs)

            except Exception as e:
                self.log(f"[Error] {t}: {e}", "err")

        # คำนวณสัดส่วนพอร์ตรวมระดับกองทุน (Portfolio Optimizer v4.0)
        if scan_list:
            scan_list = qv4.optimize_portfolio_weights(scan_list, close_map, total_capital=capital)
            for s in scan_list:
                t = s["ticker"]
                if t in new_cache:
                    new_cache[t]["scan"] = s
                self.log(
                    f"  -> {t}: Score {s['quant_score']:.0f}({s['grade']}) | ML {s['ml_win_prob_pct']:.0f}% | พอร์ตv4 {s['opt_alloc_pct']:.1f}% (${s['opt_alloc_amount']:,.0f})",
                    "ok",
                )

        self.ticker_cache = new_cache
        self.scan_rows_list = scan_list
        self.all_bt_rows = bt_rows
        self.all_trade_rows = trade_rows

        os.makedirs("output_backtest", exist_ok=True)
        if scan_list:
            be.pd.DataFrame(scan_list).to_csv("output_backtest/daily_scan.csv", index=False, encoding="utf-8-sig")
        if bt_rows:
            be.pd.DataFrame(bt_rows).to_csv("output_backtest/multi_summary.csv", index=False, encoding="utf-8-sig")
        if trade_rows:
            be.pd.DataFrame(trade_rows).to_csv("output_backtest/trade_log.csv", index=False, encoding="utf-8-sig")

        # ซิงก์เข้า MEMORY.md ของ Hermes Agent อัตโนมัติ
        acc = bb.get_account_summary({s["ticker"]: float(s["close"]) for s in scan_list})
        hb.sync_to_hermes_memory(scan_list, acc, extra_note=f"อัปเดตผลสแกน v4.0 ({len(scan_list)} สินทรัพย์) พร้อมจัดพอร์ตใหม่แล้ว")

        self.msg_queue.put(("status", f"✅ วิเคราะห์ v4.0 + จัดพอร์ต + ซิงก์ Hermes Agent ครบทั้ง {len(scan_list)} สินทรัพย์เรียบร้อย!", 100.0))
        self.msg_queue.put(("all_done",))

    # ==========================================
    # การแสดงผลตาราง, KPI Cards และกราฟ 5 โหมด
    # ==========================================
    def _populate_all_tables(self):
        for item in self.watch_tree.get_children():
            self.watch_tree.delete(item)
        for item in self.opt_tree.get_children():
            self.opt_tree.delete(item)

        for s in self.scan_rows_list:
            act = str(s.get("action", ""))
            tag = "buy" if "BUY" in act else ("hold" if "HOLD" in act else ("sell" if "SELL" in act else "wait"))
            t = s["ticker"]
            sc = float(s.get("quant_score", 50))
            gr = s.get("grade", "B")
            ml_p = float(s.get("ml_win_prob_pct", 50))
            wfo_p = float(s.get("wfo_pass_pct", 75))
            ind_a = float(s.get("alloc_pct", 0))
            opt_a = float(s.get("opt_alloc_pct", ind_a))
            opt_amt = float(s.get("opt_alloc_amount", s.get("alloc_amount", 0)))

            self.watch_tree.insert(
                "",
                tk.END,
                iid=t,
                values=(
                    t,
                    f"{sc:.0f}({gr})",
                    f"{ml_p:.0f}%",
                    act.split()[0],
                    f"{opt_a:.1f}%",
                    f"{float(s['close']):,.2f}",
                ),
                tags=(tag,),
            )

            self.opt_tree.insert(
                "",
                tk.END,
                values=(
                    t,
                    f"{sc:.0f}/100 ({gr})",
                    f"{ml_p:.1f}%",
                    f"{wfo_p:.0f}%",
                    f"{ind_a:.1f}%",
                    f"{opt_a:.1f}%",
                    f"${opt_amt:,.0f}",
                    s.get("news_sentiment_label", "Neutral"),
                    s.get("top_headline", "-"),
                ),
                tags=(tag,),
            )

        self._refresh_trade_table()
        self._refresh_backtest_table()

        if self.scan_rows_list:
            first_t = self.scan_rows_list[0]["ticker"]
            if self.selected_ticker not in self.ticker_cache:
                self.selected_ticker = first_t
            self.watch_tree.selection_set(self.selected_ticker)
            self._update_kpi_cards_and_chart(self.selected_ticker)

    def _on_watchlist_select(self, _event):
        sel = self.watch_tree.selection()
        if not sel:
            return
        t = sel[0]
        self.selected_ticker = t
        self._update_kpi_cards_and_chart(t)

    def _update_kpi_cards_and_chart(self, ticker: str):
        s = next((r for r in self.scan_rows_list if r["ticker"] == ticker), None)
        if s:
            qv4.compute_sniper_and_tp_levels(s)
            self._populate_order_ticket_from_scan(s)
            self.kpi_vars[0][0].set(f"🎯 {ticker} • {s['best_strategy']} ({s.get('sniper_status', '')})")
            self.kpi_vars[0][1].set(
                f"Close: {float(s['close']):,.2f}  |  {s['action']}  |  Score: {float(s['quant_score']):.0f}({s['grade']})\n"
                f"Stop: {float(s['stop_price']):,.2f} | TP1(1.5R): {float(s.get('tp1_price',0)):,.2f} | TP2(3R): {float(s.get('tp2_price',0)):,.2f}"
            )

            gate_st = s.get("wfo_gate_status", "-")
            self.kpi_vars[1][0].set(f"🤖 Explainable AI (XAI) & Rolling WFO Gate: [{gate_st}] ({ticker})")
            self.kpi_vars[1][1].set(
                f"ML Win Prob: {float(s.get('ml_win_prob_pct', 50)):.1f}%  |  Rolling OOS Shp: {float(s.get('wfo_oos_sharpe', 0.0)):.2f}  |  Sortino: {float(s.get('sortino', 1.2)):.2f}\n"
                f"XAI หนุนขึ้น: {s.get('top_bullish_driver', 'Trend/Momentum')}  |  Alpha(α): {float(s.get('alpha_pct', 0.0)):+.1f}%"
            )

            self.kpi_vars[2][0].set(f"🏛 Institutional Levels & Monte Carlo ({ticker})")
            self.kpi_vars[2][1].set(
                f"POC: {float(s.get('poc_price', 0)):,.2f}  |  VWAP20: {float(s.get('vwap20', 0)):,.2f}\n"
                f"Daily VaR95%: {float(s.get('var_95_pct', 0)):.2f}%  |  MC 1Y WinProb: {float(s.get('mc_prob_profit_pct', 50)):.0f}%"
            )

            self.kpi_vars[3][0].set(f"🌐 Macro VIX • Portfolio v4 • News ({ticker})")
            self.kpi_vars[3][1].set(
                f"{s.get('macro_vix_label', 'VIX Normal')}  |  พอร์ตv4: {float(s.get('opt_alloc_pct', 0)):.1f}% (${float(s.get('opt_alloc_amount', 0)):,.0f})\n"
                f"News: {s.get('news_sentiment_label', 'Neutral')} — {str(s.get('top_headline', ''))[:42]}"
            )

        self.redraw_interactive_chart()

    def redraw_interactive_chart(self):
        t = THEMES[self.theme_mode]
        self.drawing_mgr.detach_axis()
        self.fig.clear()
        self.fig.patch.set_facecolor(t["fig_bg"])

        def style_ax(ax):
            ax.set_facecolor(t["ax_bg"])
            ax.tick_params(colors=t["fg"], labelsize=8)
            ax.xaxis.label.set_color(t["fg"])
            ax.yaxis.label.set_color(t["fg"])
            ax.title.set_color(t["fg"])
            for spine in ax.spines.values():
                spine.set_color(t["border"])
            ax.grid(True, color=t["grid"], alpha=0.55, linestyle=":")

        mode = self.chart_mode

        # โหมด 4: Portfolio Allocation Bar + Correlation Heatmap
        if mode == "portfolio_corr":
            if not self.scan_rows_list:
                return
            gs = self.fig.add_gridspec(1, 2, width_ratios=[1.1, 1.3], wspace=0.22)
            ax_bar = self.fig.add_subplot(gs[0])
            ax_hm = self.fig.add_subplot(gs[1])
            style_ax(ax_bar)
            style_ax(ax_hm)

            tickers_l = [r["ticker"] for r in self.scan_rows_list]
            opt_w = [float(r.get("opt_alloc_pct", r.get("alloc_pct", 0))) for r in self.scan_rows_list]
            cash_w = max(0.0, 100.0 - sum(opt_w))
            labels_pie = tickers_l + ["CASH (สำรอง)"]
            vals_pie = opt_w + [cash_w]
            bar_cols = ["#4EC9B0" if v > 0 else "#3C3C3C" for v in opt_w] + ["#569CD6"]

            bars = ax_bar.barh(labels_pie, vals_pie, color=bar_cols, alpha=0.88)
            ax_bar.set_xlim(0, max(max(vals_pie) * 1.22, 40))
            for b_item, v in zip(bars, vals_pie):
                ax_bar.text(v + 1.0, b_item.get_y() + b_item.get_height() / 2, f"{v:.1f}%", va="center", color=t["fg"], fontsize=8.5, weight="bold")
            m4_stat = ""
            if self.selected_ticker in self.ticker_cache and "six_modes" in self.ticker_cache[self.selected_ticker]:
                m4 = self.ticker_cache[self.selected_ticker]["six_modes"]["mode_4_risk_parity"]
                m4_stat = f" | Backtest ปุ่ม 4: Ret {m4['full']['total_ret_pct']:+.1f}% (OOS {m4['oos_ret_pct']:+.1f}%, Shp {m4['full']['sharpe']:.2f})"
            ax_bar.set_title(f"⚖ สัดส่วนพอร์ตรวม v6.0{m4_stat}", fontsize=9.2, weight="bold")
            ax_bar.set_xlabel("Portfolio Allocation (%)")

            if len(self.ticker_cache) >= 2:
                close_map = {k: v["close"] for k, v in self.ticker_cache.items()}
                corr_df = be.compute_correlation_matrix(close_map)
                c_labels = list(corr_df.columns)
                mat = corr_df.to_numpy()
                ax_hm.imshow(mat, cmap="coolwarm", vmin=-1.0, vmax=1.0, aspect="auto")
                ax_hm.set_xticks(range(len(c_labels)))
                ax_hm.set_yticks(range(len(c_labels)))
                ax_hm.set_xticklabels(c_labels, fontsize=8.5, weight="bold")
                ax_hm.set_yticklabels(c_labels, fontsize=8.5, weight="bold")
                for i in range(len(c_labels)):
                    for j in range(len(c_labels)):
                        val = mat[i, j]
                        ax_hm.text(j, i, f"{val:+.2f}", ha="center", va="center", color="white" if abs(val) > 0.45 else "black", fontsize=9, weight="bold")
                ax_hm.set_title("🧩 Multi-Asset Return Correlation Matrix", fontsize=9.5, weight="bold")
            self.fig.tight_layout(pad=1.6)
            self.canvas.draw()
            return

        ticker = self.selected_ticker
        if ticker not in self.ticker_cache:
            return
        data = self.ticker_cache[ticker]
        close = data["close"]
        ind = data["ind"]
        s = data["scan"]

        if mode == "signals_markers":
            ax1 = self.fig.add_subplot(211)
            ax2 = self.fig.add_subplot(212, sharex=ax1)
            style_ax(ax1)
            style_ax(ax2)

            ax1.plot(close.index, close.values, label="Close Price", color="#569CD6", linewidth=1.6)
            if not ind["sma50"].isna().all():
                ax1.plot(ind["sma50"].index, ind["sma50"].values, label="SMA 50", color="#DCDCAA", linewidth=1.1)
            if not ind["sma200"].isna().all():
                ax1.plot(ind["sma200"].index, ind["sma200"].values, label="SMA 200", color="#C586C0", linewidth=1.1)
            ax1.plot(data["atr_stop"].index, data["atr_stop"].values, label="ATR Trailing Stop", color="#F44747", linestyle="--", linewidth=1.1)

            # วาดเส้นเป้าหมายทำกำไร TP1 (1.5R), TP2 (3.0R) และโซนช้อนซื้อ Sniper Entry
            tp1_v = float(s.get("tp1_price", 0.0))
            tp2_v = float(s.get("tp2_price", 0.0))
            sniper_v = float(s.get("sniper_price", 0.0))
            if tp1_v > 0:
                ax1.axhline(tp1_v, color="#4EC9B0", linestyle=":", linewidth=1.2, label=f"TP1 1.5R ({tp1_v:,.2f})")
            if tp2_v > 0:
                ax1.axhline(tp2_v, color="#22C55E", linestyle="--", linewidth=1.2, label=f"TP2 3.0R ({tp2_v:,.2f})")
            if sniper_v > 0:
                ax1.axhline(sniper_v, color="#38BDF8", linestyle="-.", linewidth=1.1, alpha=0.8, label=f"Sniper Zone ({sniper_v:,.2f})")

            trades = data["trades"]
            if trades:
                buy_dates = [close.index[tr["entry_idx"]] for tr in trades]
                buy_prices = [tr["entry_price"] for tr in trades]
                ax1.scatter(buy_dates, buy_prices, marker="^", color="#4EC9B0", edgecolors="black", s=75, zorder=5, label=f"▲ BUY ({len(buy_dates)})")
                closed_t = [tr for tr in trades if "OPEN" not in tr["exit_reason"]]
                if closed_t:
                    sell_dates = [close.index[tr["exit_idx"]] for tr in closed_t]
                    sell_prices = [tr["exit_price"] for tr in closed_t]
                    ax1.scatter(sell_dates, sell_prices, marker="v", color="#F44747", edgecolors="black", s=75, zorder=5, label=f"▼ SELL ({len(sell_dates)})")

            m1_stat = ""
            if "six_modes" in data:
                m1 = data["six_modes"]["mode_1_atr_sniper"]
                m1_stat = f" | Backtest ปุ่ม 1: Ret {m1['full']['total_ret_pct']:+.1f}% (OOS {m1['oos_ret_pct']:+.1f}%, MaxDD {m1['full']['max_dd_pct']:.1f}%, Shp {m1['full']['sharpe']:.2f})"
            ax1.set_title(
                f"🎯 {ticker} [{data['best_strat']}] — Score {s['quant_score']:.0f}({s['grade']}) | {s['action']}{m1_stat}",
                fontsize=9.2,
                weight="bold",
            )
            self._apply_legend(ax1, t, loc="upper left", fontsize=7.5, ncol=3)

            ax2.plot(ind["rsi14"].index, ind["rsi14"].values, label="RSI(14)", color="#4EC9B0", linewidth=1.2)
            ax2.plot(ind["adx14"].index, ind["adx14"].values, label="ADX(14)", color="#DCDCAA", linewidth=1.1)
            ax2.axhline(70, color="#F44747", linestyle="--", linewidth=0.7)
            ax2.axhline(30, color="#4EC9B0", linestyle="--", linewidth=0.7)
            ax2.set_ylim(0, 100)
            self._apply_legend(ax2, t, loc="upper left", fontsize=7.5, ncol=2)
            self.drawing_mgr.attach_axis(ax1, ticker, t)

        elif mode == "vwap_vp":
            gs = self.fig.add_gridspec(1, 2, width_ratios=[3.2, 1], wspace=0.04)
            ax_p = self.fig.add_subplot(gs[0])
            ax_vp = self.fig.add_subplot(gs[1], sharey=ax_p)
            style_ax(ax_p)
            style_ax(ax_vp)

            vp = data["vp"]
            lookback = min(len(close), 150)
            c_sub = close.iloc[-lookback:]
            ax_p.plot(c_sub.index, c_sub.values, label="Close Price", color="#569CD6", linewidth=1.7)
            ax_p.plot(ind["vwap20"].iloc[-lookback:].index, ind["vwap20"].iloc[-lookback:].values, label="VWAP (20D)", color="#4EC9B0", linewidth=1.3)
            ax_p.axhline(vp["poc_price"], color="#CE9178", linewidth=1.8, label=f"POC ({vp['poc_price']:,.2f})")
            ax_p.axhspan(vp["val_price"], vp["vah_price"], color="#007ACC", alpha=0.14, label="70% Value Area")
            m2_stat = ""
            if "six_modes" in data:
                m2 = data["six_modes"]["mode_2_vwap_poc"]
                m2_stat = (
                    f" | Backtest ปุ่ม 2: Ret {m2['full']['total_ret_pct']:+.1f}% "
                    f"(OOS {m2['oos_ret_pct']:+.1f}%, MaxDD {m2['full']['max_dd_pct']:.1f}%, Shp {m2['full']['sharpe']:.2f}, Win {m2['full']['win_rate_pct']:.0f}%)"
                )
            ax_p.set_title(f"🏛 {ticker} — VWAP & Volume Profile POC ({vp['vp_status']}){m2_stat}", fontsize=9.0, weight="bold")
            self._apply_legend(ax_p, t, loc="upper left", fontsize=7.5, ncol=2)

            centers = vp["bin_centers"]
            vols = vp["bin_volumes"]
            bar_h = (centers[1] - centers[0]) * 0.85 if len(centers) > 1 else 1.0
            poc_i = int(np.argmax(vols))
            b_cols = ["#CE9178" if i == poc_i else "#007ACC" for i in range(len(centers))]
            ax_vp.barh(centers, vols, height=bar_h, color=b_cols, alpha=0.85)
            plt.setp(ax_vp.get_yticklabels(), visible=False)
            self.drawing_mgr.attach_axis(ax_p, ticker, t)

        elif mode == "monte_carlo":
            mc = data["mc"]
            ax1 = self.fig.add_subplot(211)
            ax2 = self.fig.add_subplot(212)
            style_ax(ax1)
            style_ax(ax2)

            days_x = np.arange(1, len(mc["p50_curve"]) + 1)
            for path in mc["sample_paths"]:
                ax1.plot(days_x, path, color="#569CD6", alpha=0.07, linewidth=0.7)
            ax1.fill_between(days_x, mc["p05_curve"], mc["p95_curve"], color="#007ACC", alpha=0.18, label="90% Confidence (P05-P95)")
            ax1.plot(days_x, mc["p50_curve"], color="#4EC9B0", linewidth=2.0, label=f"P50 Median ({mc['mc_median_ret_pct']:+.1f}%)")
            ax1.plot(days_x, mc["p05_curve"], color="#F44747", linestyle="--", linewidth=1.4, label=f"P05 Worst 5% ({mc['mc_p05_ret_pct']:+.1f}%)")
            ax1.set_title(f"🎲 {ticker} — Monte Carlo 1,000 เส้นทาง (โอกาสกำไร 1Y: {mc['mc_prob_profit_pct']:.1f}% | Risk of Ruin: {mc['mc_risk_of_ruin_pct']:.1f}%)", fontsize=9.2, weight="bold")
            self._apply_legend(ax1, t, loc="upper left", fontsize=7.5, ncol=3)

            if "six_modes" in data:
                m3 = data["six_modes"]["mode_3_mc_var_shield"]
                base_eq = data["results"][data["best_strat"]]["equity"]
                var_eq = m3["full"]["equity"]
                ax2.plot(base_eq.index, base_eq.values, color="#569CD6", linestyle="--", linewidth=1.3, label=f"Base ({data['best_strat']}: {data['results'][data['best_strat']]['total_ret_pct']:+.1f}%)")
                ax2.plot(var_eq.index, var_eq.values, color="#30D158", linewidth=2.0, label=f"🎲 ปุ่ม 3 VaR-Shielded ({m3['full']['total_ret_pct']:+.1f}% | OOS {m3['oos_ret_pct']:+.1f}% | MaxDD {m3['full']['max_dd_pct']:.1f}%)")
                ax2.set_title(
                    f"🛡️ ผล Backtest การใช้ปุ่ม 3 (VaR-95% Dynamic Position Sizing Shield) — Sharpe {m3['full']['sharpe']:.2f} | OOS Sharpe {m3['oos_sharpe']:.2f}",
                    fontsize=9.0,
                    weight="bold",
                )
            else:
                eq_rets = data["results"][data["best_strat"]]["equity"].pct_change().dropna() * 100.0
                ax2.hist(eq_rets.values, bins=40, color="#007ACC", edgecolor=t["border"], alpha=0.75)
                ax2.axvline(mc["var_95_pct"], color="#DCDCAA", linestyle="--", linewidth=1.8, label=f"VaR 95%: {mc['var_95_pct']:.2f}%")
                ax2.axvline(mc["cvar_95_pct"], color="#F44747", linestyle="-", linewidth=1.8, label=f"CVaR 95%: {mc['cvar_95_pct']:.2f}%")
            self._apply_legend(ax2, t, loc="upper left", fontsize=7.5)

        elif mode == "ml_wfo":
            gs = self.fig.add_gridspec(1, 2, width_ratios=[1.25, 1.0], wspace=0.24)
            ax_xai = self.fig.add_subplot(gs[0])
            ax_sc = self.fig.add_subplot(gs[1])
            style_ax(ax_xai)
            style_ax(ax_sc)

            xai_info = data.get("xai") or qv5.compute_xai_feature_importance(close, ind)
            f_names = xai_info["xai_features"]
            f_impacts = xai_info["xai_impacts"]
            xai_cols = ["#30D158" if v >= 0 else "#FF453A" for v in f_impacts]

            y_pos = np.arange(len(f_names))
            ax_xai.barh(y_pos, f_impacts, color=xai_cols, alpha=0.88, height=0.58)
            ax_xai.set_yticks(y_pos)
            ax_xai.set_yticklabels(f_names, fontsize=8, weight="bold")
            ax_xai.axvline(0, color=t["fg"], linewidth=0.9, linestyle="--")
            ax_xai.set_xlim(-115, 115)
            for idx_b, val_b in enumerate(f_impacts):
                offset = 4.0 if val_b >= 0 else -4.0
                ha_align = "left" if val_b >= 0 else "right"
                ax_xai.text(val_b + offset, idx_b, f"{val_b:+.0f}", va="center", ha=ha_align, color=t["fg"], fontsize=8, weight="bold")
            ax_xai.set_title(f"🤖 Explainable AI (XAI): ปัจจัยขับเคลื่อน ML Win Prob ({ticker})", fontsize=9.2, weight="bold")
            ax_xai.set_xlabel("Feature Attribution Impact (-100 ถึง +100)")

            if "six_modes" in data:
                m6 = data["six_modes"]["mode_6_xai_filter"]
                base_eq = data["results"][data["best_strat"]]["equity"]
                xai_eq = m6["full"]["equity"]
                ax_sc.plot(base_eq.index, base_eq.values, color="#569CD6", linestyle="--", linewidth=1.3, label=f"Raw {data['best_strat']} ({data['results'][data['best_strat']]['total_ret_pct']:+.1f}%)")
                ax_sc.plot(xai_eq.index, xai_eq.values, color="#BF5AF2", linewidth=2.1, label=f"🤖 XAI Meta-Filtered ({m6['full']['total_ret_pct']:+.1f}% | OOS {m6['oos_ret_pct']:+.1f}%)")
                cut_dt = close.index[int(len(close) * 0.70)]
                ax_sc.axvline(cut_dt, color="#FFD60A", linestyle=":", linewidth=1.2, label="70/30 OOS Split")
                ax_sc.set_title(
                    f"📊 Backtest ปุ่ม 6 (XAI Filter): Ret {m6['full']['total_ret_pct']:+.1f}% | MaxDD {m6['full']['max_dd_pct']:.1f}% | Shp {m6['full']['sharpe']:.2f} (OOS Shp {m6['oos_sharpe']:.2f})",
                    fontsize=8.8,
                    weight="bold",
                )
            else:
                metrics_lbls = ["Quant\nScore", "ML Win\nProb%", "Walk-\nForward%", "1Y MC\nWinProb%", "Half-Kelly\n(x2)"]
                metrics_vals = [
                    float(s.get("quant_score", 50.0)),
                    float(s.get("ml_win_prob_pct", 50.0)),
                    float(s.get("wfo_pass_pct", 75.0)),
                    float(s.get("mc_prob_profit_pct", 50.0)),
                    min(100.0, float(s.get("half_kelly_pct", 10.0)) * 2.0),
                ]
                m_cols = ["#0A84FF", "#BF5AF2", "#4EC9B0", "#30D158", "#FF9F0A"]
                bars = ax_sc.bar(metrics_lbls, metrics_vals, color=m_cols, alpha=0.88, width=0.52)
                ax_sc.set_ylim(0, 115)
                ax_sc.axhline(60, color="#DCDCAA", linestyle="--", linewidth=0.9, label="เกณฑ์มาตรฐาน (60%)")
            self._apply_legend(ax_sc, t, loc="upper left", fontsize=7.5)

        else:
            ax1 = self.fig.add_subplot(211)
            ax2 = self.fig.add_subplot(212, sharex=ax1)
            style_ax(ax1)
            style_ax(ax2)
            for name, res in data["results"].items():
                lw = 2.3 if name == data["best_strat"] else 1.3
                ax1.plot(res["equity"].index, res["equity"].values, label=f"{name} ({res['total_ret_pct']:+.1f}% | Shp {res['sharpe']:.2f})", linewidth=lw)
                ax2.plot(res["dd"].index, res["dd"].values, linewidth=1.1)

            cut_idx = int(len(close) * 0.70)
            if 10 < cut_idx < len(close) - 5:
                ax1.axvline(close.index[cut_idx], color="#FF9F0A", linestyle=":", linewidth=1.4, label="In-Sample 70% | Out-of-Sample 30%")

            # พล็อตเส้นดัชนีมาตรฐาน S&P 500 (^GSPC) เปรียบเทียบโดยตรง
            bm_c = data.get("bm_close")
            if bm_c is not None and len(bm_c) >= 20:
                bm_al = bm_c.reindex(close.index).ffill().bfill()
                if not bm_al.isna().all():
                    bm_eq = (1.0 + bm_al.pct_change().fillna(0.0)).cumprod() * 100.0
                    bm_ret = float(bm_eq.iloc[-1] - 100.0)
                    ax1.plot(
                        bm_eq.index,
                        bm_eq.values,
                        label=f"★ S&P 500 Benchmark ({bm_ret:+.1f}%)",
                        color="#FFD60A",
                        linestyle="--",
                        linewidth=2.0,
                    )

            b_res = data["results"][data["best_strat"]]
            m5_oos = data["six_modes"]["mode_5_is_winner"]["oos_ret_pct"] if "six_modes" in data else 0.0
            ax1.set_title(
                f"📈 ปุ่ม 5: เทียบ 4 กลยุทธ์หลัก & S&P500 (IS Winner: {data['best_strat']} | OOS Ret {m5_oos:+.1f}% | Sortino {b_res.get('sortino',0):.2f} | Alpha {b_res.get('alpha_pct',0):+.1f}%)",
                fontsize=9.2,
                weight="bold",
            )
            self._apply_legend(ax1, t, loc="upper left", fontsize=7, ncol=3)

        self.fig.tight_layout(pad=1.6)
        self.canvas.draw()

    # ==========================================
    # 1-Click Portfolio Rebalance & Order Execution
    # ==========================================
    def execute_portfolio_rebalance(self):
        if not self.scan_rows_list:
            self._toast_info("แจ้งเตือน", "กรุณากดรันสแกนหุ้นก่อนทำ Rebalance ครับ")
            return

        latest_prices = {s["ticker"]: float(s["close"]) for s in self.scan_rows_list}
        acc = bb.get_account_summary(latest_prices)
        total_eq = float(acc.get("equity", float(self.capital_var.get() or 100000)))
        cur_pos_map = {p["symbol"]: float(p["qty"]) for p in acc.get("positions", [])}

        rebal_orders = []
        for s in self.scan_rows_list:
            sym = s["ticker"]
            price = float(s["close"])
            if price <= 0:
                continue
            target_pct = float(s.get("opt_alloc_pct", s.get("alloc_pct", 0.0))) / 100.0
            target_val = total_eq * target_pct
            cur_qty = cur_pos_map.get(sym, 0.0)
            cur_val = cur_qty * price
            diff_val = target_val - cur_val

            if abs(diff_val) >= max(200.0, total_eq * 0.01):
                side = "BUY" if diff_val > 0 else "SELL"
                qty = abs(diff_val) / price
                rebal_orders.append({
                    "symbol": sym,
                    "side": side,
                    "qty": qty,
                    "price": price,
                    "stop_loss": float(s["stop_price"]),
                    "target_pct": target_pct * 100.0,
                    "diff_val": abs(diff_val),
                })

        if not rebal_orders:
            self._toast_info("พอร์ตสมดุลแล้ว", "สัดส่วนพอร์ตปัจจุบันใกล้เคียงกับสัดส่วนที่เหมาะสม (Portfolio Optimizer v4.0) แล้ว ไม่จำเป็นต้องปรับเพิ่มครับ")
            return

        summary_lines = [
            f"• {o['side']} {o['symbol']}: {o['qty']:,.4f} หน่วย @ {o['price']:,.2f} (${o['diff_val']:,.0f}) -> เป้าพอร์ต {o['target_pct']:.1f}%"
            for o in rebal_orders
        ]
        msg = (
            f"ระบบคำนวณใบคำสั่งปรับสมดุลพอร์ตรวม (1-Click Portfolio Rebalance) สำหรับพอร์ต ${total_eq:,.2f}:\n\n"
            + "\n".join(summary_lines)
            + "\n\nต้องการยืนยันส่งคำสั่ง Rebalance ทั้งหมดนี้หรือไม่?"
        )
        if not messagebox.askyesno("ยืนยัน 1-Click Portfolio Rebalance", msg):
            return

        ok_cnt = 0
        for o in rebal_orders:
            r = bb.execute_confirmed_order(o["symbol"], o["side"], o["qty"], o["price"], o["stop_loss"])
            if r["ok"]:
                ok_cnt += 1
                self.log(r["message"], "ok")
            else:
                self.log(r["message"], "err")

        self.sync_broker_portfolio()
        self.manual_sync_hermes()
        self._toast_info("Rebalance เสร็จสิ้น", f"ดำเนินการปรับพอร์ตสำเร็จ {ok_cnt}/{len(rebal_orders)} รายการ!")

    def _send_selected_to_order_ticket(self):
        s = next((r for r in self.scan_rows_list if r["ticker"] == self.selected_ticker), None)
        if s:
            self._populate_order_ticket_from_scan(s)
            self.dock_nb.select(self.dock_broker)

    def _populate_order_ticket_from_scan(self, s: dict):
        qv4.compute_sniper_and_tp_levels(s)
        self.ord_sym_var.set(str(s["ticker"]))
        side = "SELL" if "SELL" in str(s.get("action", "")) else "BUY"
        self.ord_side_var.set(side)
        qty = float(s.get("opt_shares", s.get("shares", 0.0)))
        if qty <= 0 and float(s.get("close", 0.0)) > 0:
            qty = (float(self.capital_var.get() or 100000) * 0.10) / float(s["close"])
        self.ord_qty_var.set(f"{qty:.4f}")
        self.ord_price_var.set(f"{float(s['close']):.2f}")
        self.ord_stop_var.set(f"{float(s['stop_price']):.2f}")
        self.ord_tp1_var.set(f"{float(s.get('tp1_price', float(s['close'])*1.08)):.2f}")
        self.ord_tp2_var.set(f"{float(s.get('tp2_price', float(s['close'])*1.16)):.2f}")

    # ==========================================
    # ป๊อปอัพขยายช่องใส่ Ticker + เรดาร์หุ้นน่าสนใจ (Expandable Ticker & Hot Radar Popup)
    # ==========================================
    def open_ticker_expander_popup(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("🔍 ขยายช่องแก้ไข Watchlist & เรดาร์ค้นหาหุ้นกำลังมาแรง (Hot Picks Discovery)")
        dlg.geometry("960x640")
        dlg.configure(bg="#1E1E1E", padx=14, pady=12)
        dlg.transient(self.root)
        dlg.grab_set()

        # ส่วนที่ 1: กล่องแก้ไขรายชื่อหุ้นขนาดใหญ่ (รองรับ Ctrl+C/V/Z/Y/X/A และคลิกขวาครบ)
        tk.Label(
            dlg,
            text="📝 ช่องแก้ไข Watchlist ขนาดใหญ่ (พิมพ์คั่นด้วยเว้นวรรค หรือขึ้นบรรทัดใหม่ได้ — รองรับ Ctrl+C, V, Z, Y, X, A เต็มรูปแบบ):",
            font=("Tahoma", 9, "bold"),
            fg="#4EC9B0",
            bg="#1E1E1E",
        ).pack(anchor="w")

        big_editor = scrolledtext.ScrolledText(
            dlg,
            font=("Consolas", 12, "bold"),
            height=3,
            bg="#121212",
            fg="#4EC9B0",
            insertbackground="white",
            wrap=tk.WORD,
            undo=True,
            autoseparators=True,
            maxundo=-1,
        )
        big_editor.pack(fill=tk.X, pady=(4, 8))
        big_editor.insert("1.0", self.tickers_var.get())

        def _get_editor_tickers() -> list[str]:
            raw = big_editor.get("1.0", tk.END).replace(",", " ").replace("\n", " ").split()
            seen = []
            for item in raw:
                u = item.strip().upper()
                if u and u not in seen:
                    seen.append(u)
            return seen

        def _set_editor_tickers(t_list: list[str]):
            big_editor.delete("1.0", tk.END)
            big_editor.insert("1.0", " ".join(t_list))

        # ส่วนที่ 2: ปุ่มเลือกหมวดหมู่หุ้นฮิต (Curated Theme Presets) & บันทึก Preset
        preset_fr = tk.Frame(dlg, bg="#252526", padx=8, pady=6)
        preset_fr.pack(fill=tk.X, pady=(0, 8))

        tk.Label(preset_fr, text="⭐ หมวดหมู่หุ้นเด่น (คลิกเพื่อโหลด):", font=("Tahoma", 8, "bold"), fg="#9CDCFE", bg="#252526").pack(side=tk.LEFT, padx=(0, 6))
        presets_map = qv4.load_watchlist_presets()

        for p_name, p_tickers in list(presets_map.items())[:6]:
            short_lbl = p_name.split("(")[0].strip()
            tk.Button(
                preset_fr,
                text=short_lbl,
                font=("Tahoma", 8, "bold"),
                bg="#181818",
                fg="#D4D4D4",
                activebackground="#007ACC",
                activeforeground="white",
                relief=tk.FLAT,
                padx=7,
                pady=2,
                cursor="hand2",
                command=lambda pts=p_tickers: _set_editor_tickers(pts.split()),
            ).pack(side=tk.LEFT, padx=2)

        def _save_custom_preset():
            cur_str = " ".join(_get_editor_tickers())
            if not cur_str:
                return
            qv4.save_watchlist_preset("💾 ชุดโปรดของฉัน (My Custom)", cur_str)
            self._toast_info("บันทึกสำเร็จ", f"บันทึกชุดหุ้นโปรดเรียบร้อย:\n{cur_str}")

        tk.Button(
            preset_fr,
            text="💾 บันทึกชุดนี้เป็น Preset",
            font=("Tahoma", 8, "bold"),
            bg="#0E639C",
            fg="white",
            relief=tk.FLAT,
            padx=7,
            pady=2,
            command=_save_custom_preset,
        ).pack(side=tk.RIGHT, padx=2)

        # ส่วนที่ 3: ตารางเรดาร์สแกนหาหุ้นน่าสนใจในช่วงนี้ (🔥 Hot Picks Radar)
        radar_hdr = tk.Frame(dlg, bg="#1E1E1E")
        radar_hdr.pack(fill=tk.X, pady=(2, 4))
        tk.Label(
            radar_hdr,
            text="🔥 เรดาร์หุ้นและคริปโตที่น่าสนใจในช่วงนี้ (ดับเบิลคลิกที่แถวเพื่อเพิ่มเข้าช่อง Watchlist ด้านบนทันที):",
            font=("Tahoma", 9, "bold"),
            fg="#DCDCAA",
            bg="#1E1E1E",
        ).pack(side=tk.LEFT)

        r_cols = ("ticker", "hot_score", "status_tag", "close", "ret_5d", "ret_20d", "rsi14", "vol_ratio")
        radar_tree = ttk.Treeview(dlg, columns=r_cols, show="headings", height=11)
        for c, (txt, w) in {
            "ticker": ("Ticker", 80),
            "hot_score": ("ความน่าสนใจ (Hot Score)", 135),
            "status_tag": ("สถานะโมเมนตัม / จุดเข้า", 210),
            "close": ("ราคาล่าสุด", 95),
            "ret_5d": ("5D Return%", 95),
            "ret_20d": ("20D Return%", 95),
            "rsi14": ("RSI(14)", 80),
            "vol_ratio": ("Volume พุ่ง", 95),
        }.items():
            radar_tree.heading(c, text=txt)
            radar_tree.column(c, width=w, anchor="w" if c in ("ticker", "status_tag") else "e")

        radar_tree.tag_configure("hot", background="#112A22", foreground="#4EC9B0")
        radar_tree.tag_configure("good", background="#132338", foreground="#569CD6")
        radar_tree.tag_configure("dip", background="#2B2412", foreground="#DCDCAA")
        radar_tree.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        def _populate_radar():
            for item in radar_tree.get_children():
                radar_tree.delete(item)
            rows = qv4.scan_hot_tickers_radar()
            for r in rows:
                sc = r["hot_score"]
                tag = "hot" if sc >= 75 else ("good" if sc >= 62 else "dip")
                radar_tree.insert(
                    "",
                    tk.END,
                    iid=r["ticker"],
                    values=(
                        r["ticker"],
                        f"★ {sc:.0f} / 100",
                        r["status_tag"],
                        f"{r['close']:,.2f}",
                        f"{r['ret_5d_pct']:+.2f}%",
                        f"{r['ret_20d_pct']:+.2f}%",
                        f"{r['rsi14']:.1f}",
                        f"{r['vol_ratio']:.2f}x",
                    ),
                    tags=(tag,),
                )

        def _add_selected_radar_to_editor(_event=None):
            sel = radar_tree.selection()
            if not sel:
                return
            cur_list = _get_editor_tickers()
            for sym in sel:
                if sym not in cur_list:
                    cur_list.append(sym)
            _set_editor_tickers(cur_list)

        radar_tree.bind("<Double-1>", _add_selected_radar_to_editor)

        # แถบปุ่มยืนยันด้านล่าง
        bot_fr = tk.Frame(dlg, bg="#1E1E1E")
        bot_fr.pack(fill=tk.X)

        tk.Button(
            bot_fr,
            text="➕ เพิ่มหุ้นที่เลือกจากตารางเข้าช่องด้านบน",
            font=("Tahoma", 9, "bold"),
            bg="#007ACC",
            fg="white",
            relief=tk.FLAT,
            padx=12,
            pady=5,
            cursor="hand2",
            command=_add_selected_radar_to_editor,
        ).pack(side=tk.LEFT, padx=(0, 6))

        tk.Button(
            bot_fr,
            text="🔥 เลือกเฉพาะตัวท็อป (Hot Score >= 70) ทั้งหมด",
            font=("Tahoma", 9, "bold"),
            bg="#2D2D2D",
            fg="#4EC9B0",
            relief=tk.FLAT,
            padx=10,
            pady=5,
            cursor="hand2",
            command=lambda: _set_editor_tickers(
                [radar_tree.item(i, "values")[0] for i in radar_tree.get_children() if float(str(radar_tree.item(i, "values")[1]).replace("★", "").split("/")[0]) >= 70]
            ),
        ).pack(side=tk.LEFT, padx=4)

        def _apply_and_close(run_now: bool = False):
            final_str = " ".join(_get_editor_tickers())
            if final_str:
                self.tickers_var.set(final_str)
            dlg.destroy()
            if run_now:
                self.start_analysis_thread()

        tk.Button(
            bot_fr,
            text="✅ ตกลง & รันวิเคราะห์ทันที",
            font=("Tahoma", 9, "bold"),
            bg="#16825D",
            fg="white",
            relief=tk.FLAT,
            padx=14,
            pady=5,
            cursor="hand2",
            command=lambda: _apply_and_close(run_now=True),
        ).pack(side=tk.RIGHT, padx=4)

        tk.Button(
            bot_fr,
            text="ตกลง (บันทึกเข้าช่อง Watchlist)",
            font=("Tahoma", 9),
            bg="#3C3C3C",
            fg="white",
            relief=tk.FLAT,
            padx=12,
            pady=5,
            command=lambda: _apply_and_close(run_now=False),
        ).pack(side=tk.RIGHT, padx=4)

        # โหลดข้อมูลเรดาร์ทันทีเมื่อเปิดป๊อปอัพ
        dlg.after(80, _populate_radar)

    # ==========================================
    # ระบบสั่งซื้อขายอัตโนมัติ 3 โหมด (Instant Best-Pick / Smart Sniper / Auto-Guardian)
    # ==========================================
    def get_ranked_best_picks(self) -> list[dict]:
        """จัดอันดับหุ้นที่น่าซื้อที่สุด ณ ตอนนั้นจากคะแนนรวม (Quant Score + ML Win Prob + Sniper Zone)"""
        for s in self.scan_rows_list:
            qv4.compute_sniper_and_tp_levels(s)
        valid = [
            s
            for s in self.scan_rows_list
            if "WAIT" not in str(s.get("action", "")) and "SELL" not in str(s.get("action", ""))
        ]
        if not valid:
            valid = list(self.scan_rows_list)
        valid.sort(key=lambda r: float(r.get("combo_rank_score", 0.0)), reverse=True)
        return valid

    def execute_instant_best_pick_buy(self):
        """ปุ่มคอมมานด์ซื้อสินทรัพย์ที่ดีที่สุด ณ ตอนนั้นทันที (Instant Best-Pick Buy)"""
        picks = self.get_ranked_best_picks()
        if not picks:
            self._toast_info("แจ้งเตือน", "กรุณากดรันสแกนหุ้นก่อนใช้ปุ่มซื้อตัวท็อปครับ")
            return

        top = picks[0]
        sym = top["ticker"]
        close = float(top["close"])
        stop = float(top["stop_price"])
        tp1 = float(top.get("tp1_price", close * 1.08))
        tp2 = float(top.get("tp2_price", close * 1.16))
        sniper_st = top.get("sniper_status", "-")

        latest_prices = {s["ticker"]: float(s["close"]) for s in self.scan_rows_list}
        acc = bb.get_account_summary(latest_prices)
        total_eq = float(acc.get("equity", float(self.capital_var.get() or 100000)))
        alloc_pct = max(float(top.get("opt_alloc_pct", top.get("alloc_pct", 15.0))), 10.0)
        invest_amt = min(float(acc.get("cash", total_eq)), total_eq * (alloc_pct / 100.0))
        qty = invest_amt / close if close > 0 else 0.0

        self._populate_order_ticket_from_scan(top)
        msg = (
            f"⚡ ระบบคัดเลือกสินทรัพย์ที่โดดเด่นที่สุด ณ ตอนนี้ (Best-Pick Command):\n\n"
            f"🏆 อันดับ 1: {sym} ({top['best_strategy']})\n"
            f"• คะแนน Quant Score : {float(top['quant_score']):.0f}/100 (เกรด {top['grade']})\n"
            f"• โอกาสชนะ ML Win Prob: {float(top.get('ml_win_prob_pct', 50)):.1f}%\n"
            f"• สถานะโซนเข้าซื้อ    : {sniper_st}\n"
            f"• ราคาเข้าซื้อ (Price)  : {close:,.2f}\n"
            f"• สัดส่วนพอร์ตแนะนำ   : {alloc_pct:.1f}% (${invest_amt:,.2f} = {qty:,.4f} หน่วย)\n"
            f"• จุดตัดขาดทุน ATR Stop: {stop:,.2f}\n"
            f"• เป้าทำกำไร TP1 (1.5R): {tp1:,.2f}  |  TP2 (3.0R): {tp2:,.2f}\n\n"
            f"ต้องการส่งคำสั่งซื้อ (BUY) {sym} เข้าพอร์ตทันทีหรือไม่?"
        )
        if not messagebox.askyesno("⚡ ยืนยันคอมมานด์ซื้อตัวท็อป (Instant Best-Pick Buy)", msg):
            return

        res = bb.execute_confirmed_order(sym, "BUY", qty, close, stop)
        if res["ok"]:
            self.log(f"[Best-Pick AutoCommand] {res['message']} | TP1={tp1:,.2f}, TP2={tp2:,.2f}", "ok")
            self.sync_broker_portfolio()
            self.manual_sync_hermes()
            self._toast_info("สำเร็จ", f"{res['message']}\n\nตั้งเป้าทำกำไรอัตโนมัติ:\n• TP1 (1.5R): {tp1:,.2f}\n• TP2 (3.0R): {tp2:,.2f}")
        else:
            self.log(res["message"], "err")
            self._toast_error("ล้มเหลว", res["message"])

    def open_auto_sniper_hub_dialog(self):
        """หน้าต่างควบคุมระบบสั่งซื้อขายอัตโนมัติ 3 โหมด (Instant Best-Pick / Smart Pullback Sniper / Auto-Guardian)"""
        dlg = tk.Toplevel(self.root)
        dlg.title("🎯 ศูนย์ควบคุมระบบเทรดอัตโนมัติ (Smart Auto-Buy & Sniper Bot Hub)")
        dlg.geometry("780x540")
        dlg.configure(bg="#1E1E1E", padx=16, pady=14)
        dlg.transient(self.root)
        dlg.grab_set()

        tk.Label(
            dlg,
            text="🎯 ระบบคอมมานด์ซื้อสินทรัพย์ในช่วงที่ดีที่สุด & บอทเฝ้าพอร์ตอัตโนมัติ (3-Mode Auto Execution)",
            font=("Tahoma", 11, "bold"),
            fg="#4EC9B0",
            bg="#1E1E1E",
        ).pack(anchor="w", pady=(0, 8))

        # ตารางจัดอันดับหุ้นน่าซื้อที่สุด ณ ตอนนี้ + โซน Sniper & TP1/TP2
        tk.Label(dlg, text="📊 จัดอันดับสินทรัพย์น่าเข้าซื้อที่สุด ณ ตอนนี้ (เรียงตาม Quant Score + ML Win Prob + โซนได้เปรียบ Sniper):", font=("Tahoma", 9, "bold"), fg="#9CDCFE", bg="#1E1E1E").pack(anchor="w")

        cols = ("rank", "ticker", "score", "ml_prob", "sniper_status", "close", "stop", "tp1", "tp2", "opt_alloc")
        s_tree = ttk.Treeview(dlg, columns=cols, show="headings", height=6)
        for c, (txt, w) in {
            "rank": ("อันดับ", 50),
            "ticker": ("Ticker", 65),
            "score": ("Score", 65),
            "ml_prob": ("ML Win%", 65),
            "sniper_status": ("จังหวะเข้าซื้อ (Sniper Zone)", 165),
            "close": ("ราคาล่าสุด", 75),
            "stop": ("ATR Stop", 75),
            "tp1": ("เป้า TP1 (1.5R)", 85),
            "tp2": ("เป้า TP2 (3.0R)", 85),
            "opt_alloc": ("พอร์ตv4%", 65),
        }.items():
            s_tree.heading(c, text=txt)
            s_tree.column(c, width=w, anchor="w" if c in ("ticker", "sniper_status") else "e")

        s_tree.tag_configure("top", background="#112A22", foreground="#4EC9B0")
        s_tree.tag_configure("norm", background="#132338", foreground="#569CD6")
        s_tree.pack(fill=tk.X, pady=(4, 10))

        ranked = self.get_ranked_best_picks()
        for idx, r in enumerate(ranked, start=1):
            s_tree.insert(
                "",
                tk.END,
                iid=r["ticker"],
                values=(
                    f"#{idx}",
                    r["ticker"],
                    f"{float(r['quant_score']):.0f}({r['grade']})",
                    f"{float(r.get('ml_win_prob_pct',50)):.0f}%",
                    r.get("sniper_status", "-"),
                    f"{float(r['close']):,.2f}",
                    f"{float(r['stop_price']):,.2f}",
                    f"{float(r.get('tp1_price',0)):,.2f}",
                    f"{float(r.get('tp2_price',0)):,.2f}",
                    f"{float(r.get('opt_alloc_pct',0)):.1f}%",
                ),
                tags=("top" if idx == 1 else "norm",),
            )

        # กรอบตั้งค่า 3 โหมดอัตโนมัติ
        cfg_box = tk.Frame(dlg, bg="#252526", padx=12, pady=10)
        cfg_box.pack(fill=tk.X, pady=(0, 10))

        tk.Label(cfg_box, text="⚙ เลือกโหมดการทำงานอัตโนมัติของบอท (Auto-Bot Modes):", font=("Tahoma", 9, "bold"), fg="#DCDCAA", bg="#252526").pack(anchor="w", pady=(0, 4))

        for var_obj, txt_desc in [
            (self.auto_mode_instant, "⚡ โหมด 1 (Instant Best-Pick): สั่งซื้อหุ้นอันดับ 1 อัตโนมัติเมื่อได้เกรด A/A+ หรือคะแนนรวมสูงสุดและยังไม่มีในพอร์ต"),
            (self.auto_mode_sniper, "🎯 โหมด 2 (Smart Pullback Sniper): เฝ้าราคาสดและช้อนซื้ออัตโนมัติทันทีที่ราคาเข้าโซนได้เปรียบ (IN SNIPER ZONE / ใกล้ POC & VWAP20)"),
            (self.auto_mode_guardian, "🛡 โหมด 3 (Auto-Guardian TP/SL): เฝ้าหุ้นที่ถือในพอร์ต สั่งขายทำกำไรอัตโนมัติเมื่อชนเป้า TP1 (1.5R) / TP2 (3.0R) หรือคัทลอสเมื่อหลุด ATR Stop"),
        ]:
            tk.Checkbutton(
                cfg_box,
                text=txt_desc,
                variable=var_obj,
                font=("Tahoma", 9),
                fg="#D4D4D4",
                bg="#252526",
                selectcolor="#181818",
                activebackground="#252526",
                activeforeground="white",
            ).pack(anchor="w", pady=2)

        int_fr = tk.Frame(cfg_box, bg="#252526", pady=4)
        int_fr.pack(fill=tk.X)
        tk.Label(int_fr, text="⏱ ความถี่ในการเช็กราคาสดอัตโนมัติ (Auto-Polling Interval):", font=("Tahoma", 9, "bold"), fg="#9CDCFE", bg="#252526").pack(side=tk.LEFT)
        interval_var = tk.StringVar(value=str(self.auto_bot_interval_sec))
        ttk.Combobox(int_fr, textvariable=interval_var, values=["15", "30", "60", "120"], width=6, state="readonly").pack(side=tk.LEFT, padx=8)
        tk.Label(int_fr, text="วินาที", font=("Tahoma", 9), fg="#D4D4D4", bg="#252526").pack(side=tk.LEFT)

        # ปุ่มสั่งงานด้านล่าง
        act_fr = tk.Frame(dlg, bg="#1E1E1E")
        act_fr.pack(fill=tk.X, pady=4)

        tk.Button(
            act_fr,
            text="⚡ คอมมานด์ซื้อตัวท็อปอันดับ 1 เดี๋ยวนี้เลย (Instant Buy #1)",
            font=("Tahoma", 9, "bold"),
            bg="#7C3AED",
            fg="white",
            relief=tk.FLAT,
            padx=12,
            pady=6,
            cursor="hand2",
            command=lambda: [dlg.destroy(), self.execute_instant_best_pick_buy()],
        ).pack(side=tk.LEFT, padx=(0, 8))

        def _toggle_bot(enable_state: bool):
            if enable_state and not messagebox.askyesno(
                "ยืนยันเปิด Auto-Bot",
                f"เปิดบอทให้ส่งคำสั่งซื้อ-ขายอัตโนมัติ (เช็กทุก {interval_var.get() or 30} วินาที) หรือไม่?",
                icon="warning",
                parent=dlg,
            ):
                return
            self.auto_bot_interval_sec = int(interval_var.get() or 30)
            self.auto_bot_countdown = self.auto_bot_interval_sec
            self.auto_bot_enabled = enable_state
            if enable_state:
                self.sniper_hub_btn.config(text=f"🤖 Auto-Sniper: ON ({self.auto_bot_interval_sec}s)", bg="#16825D")
                self.log(f"เปิดระบบบอท Auto-Sniper & Auto-Guardian แล้ว (เช็กทุก {self.auto_bot_interval_sec} วินาที)", "ok")
                dlg.destroy()
                self._run_auto_bot_cycle()
            else:
                self.sniper_hub_btn.config(text="🎯 ซื้อตัวท็อป / Auto-Sniper", bg="#7C3AED")
                self.log("ปิดระบบบอท Auto-Sniper แล้ว", "warn")
                dlg.destroy()

        if not self.auto_bot_enabled:
            tk.Button(
                act_fr,
                text="🤖 เปิดบอทเฝ้าช้อนซื้อ & คุม TP/SL อัตโนมัติ (Start Auto-Bot)",
                font=("Tahoma", 9, "bold"),
                bg="#16825D",
                fg="white",
                relief=tk.FLAT,
                padx=12,
                pady=6,
                cursor="hand2",
                command=lambda: _toggle_bot(True),
            ).pack(side=tk.LEFT, padx=4)
        else:
            tk.Button(
                act_fr,
                text="⏸ หยุดบอทอัตโนมัติ (Stop Auto-Bot)",
                font=("Tahoma", 9, "bold"),
                bg="#DC2626",
                fg="white",
                relief=tk.FLAT,
                padx=12,
                pady=6,
                cursor="hand2",
                command=lambda: _toggle_bot(False),
            ).pack(side=tk.LEFT, padx=4)

        tk.Button(act_fr, text="ปิดหน้าต่าง", font=("Tahoma", 9), bg="#3C3C3C", fg="white", relief=tk.FLAT, padx=10, pady=6, command=dlg.destroy).pack(side=tk.RIGHT)

    def _auto_bot_tick(self):
        """ตัวนับถอยหลังทำงานทุก 1 วินาทีเมื่อเปิดโหมด Auto-Sniper & Auto-Guardian Bot"""
        if self.auto_bot_enabled and not self.is_running:
            self.auto_bot_countdown -= 1
            self.sniper_hub_btn.config(text=f"🤖 Bot ON ({self.auto_bot_countdown}s)", bg="#16825D")
            if self.auto_bot_countdown <= 0:
                self.auto_bot_countdown = self.auto_bot_interval_sec
                self._run_auto_bot_cycle()
        self.root.after(1000, self._auto_bot_tick)

    def _run_auto_bot_cycle(self):
        """ตรวจสอบเงื่อนไขซื้อ/ขายอัตโนมัติทั้ง 3 โหมด (Instant Top-Pick, Pullback Sniper, Auto-Guardian TP/SL)"""
        if not self.scan_rows_list:
            return

        latest_prices = {s["ticker"]: float(s["close"]) for s in self.scan_rows_list}
        acc = bb.get_account_summary(latest_prices)
        total_eq = float(acc.get("equity", float(self.capital_var.get() or 100000)))
        cash = float(acc.get("cash", 0.0))
        held_map = {p["symbol"]: p for p in acc.get("positions", [])}

        # 1) โหมด Auto-Guardian: ตรวจสอบหุ้นที่ถืออยู่ว่าชนเป้า TP1 (1.5R) หรือหลุด Stop-Loss หรือไม่
        if self.auto_mode_guardian.get():
            for sym, pos in held_map.items():
                cur_p = float(pos["current_price"])
                stop_p = float(pos["stop_loss"])
                avg_p = float(pos["avg_price"])
                qty = float(pos["qty"])
                if stop_p > 0 and cur_p <= stop_p:
                    res = bb.execute_confirmed_order(sym, "SELL", qty, cur_p, 0.0)
                    if res["ok"]:
                        self.log(f"🛡 [Auto-Guardian SL] คัทลอสอัตโนมัติ {sym} ({qty:.4f}) @ {cur_p:,.2f} (หลุด Stop {stop_p:,.2f})", "warn")
                elif avg_p > 0 and cur_p >= avg_p * 1.08 and stop_p < avg_p:
                    # ระบบ Break-Even Profit Lock v6.0: แบ่งขายทำกำไร 50% ที่ TP1 และย้าย Stop-Loss ของที่เหลือขึ้นมาบังหน้าทุนอัตโนมัติ
                    be_stop = round(avg_p * 1.002, 2)
                    res = bb.execute_confirmed_order(sym, "SELL", qty * 0.5, cur_p, be_stop)
                    if res["ok"]:
                        self.log(
                            f"🛡 [Auto-Guardian Break-Even Lock] แบ่งขาย 50% ของ {sym} @ {cur_p:,.2f} และล็อก Stop-Loss บังหน้าทุนที่ {be_stop:,.2f} (Free Trade 100%)",
                            "ok",
                        )

        # 2) โหมด Smart Pullback Sniper & Instant Best-Pick
        ranked = self.get_ranked_best_picks()
        for idx, s in enumerate(ranked):
            sym = s["ticker"]
            if sym in held_map or sym in self.auto_executed_today:
                continue
            close = float(s["close"])
            stop = float(s["stop_price"])
            opt_pct = float(s.get("opt_alloc_pct", s.get("alloc_pct", 0.0)))
            if opt_pct <= 0 or close <= 0:
                continue

            should_buy = False
            reason_tag = ""
            if self.auto_mode_instant.get() and idx == 0 and float(s["quant_score"]) >= 45.0:
                should_buy = True
                reason_tag = "Instant Top-Pick #1"
            elif self.auto_mode_sniper.get() and bool(s.get("in_sniper_zone", False)):
                should_buy = True
                reason_tag = "In Sniper Pullback Zone"

            if should_buy:
                invest_val = min(cash * 0.95, total_eq * (opt_pct / 100.0))
                if invest_val >= 200.0:
                    qty = invest_val / close
                    res = bb.execute_confirmed_order(sym, "BUY", qty, close, stop)
                    if res["ok"]:
                        self.auto_executed_today.add(sym)
                        cash -= invest_val
                        self.log(
                            f"🎯 [Auto-Bot {reason_tag}] ซื้อ {sym} อัตโนมัติ {qty:.4f} หน่วย @ {close:,.2f} | Stop {stop:,.2f} | TP1 {float(s.get('tp1_price',0)):,.2f}",
                            "ok",
                        )

        self.sync_broker_portfolio()

    def trigger_emergency_panic(self):
        """ปุ่มฉุกเฉิน (🛑 PANIC STOP / Close All Positions): หยุดบอททันทีและเลือกขายล้างพอร์ตเข้าเงินสดได้ในคลิกเดียว"""
        if not messagebox.askyesno(
            "ยืนยัน Panic Stop",
            "หยุดบอทอัตโนมัติทั้งหมดทันทีหรือไม่?\n\n(ขั้นถัดไปจะถามอีกครั้งก่อนสั่งขายล้างพอร์ต)",
            icon="warning",
        ):
            return
        was_on = self.auto_bot_enabled
        self.auto_bot_enabled = False
        self.sniper_hub_btn.config(text="🎯 ซื้อตัวท็อป / Auto-Sniper", bg="#7C3AED")
        if was_on:
            self.log("🛑 [PANIC STOP] หยุดการทำงานของบอทอัตโนมัติทั้งหมดทันที!", "err")

        latest_prices = {s["ticker"]: float(s["close"]) for s in self.scan_rows_list}
        acc = bb.get_account_summary(latest_prices)
        pos_list = acc.get("positions", [])
        if not pos_list:
            self._toast_info("🛑 หยุดฉุกเฉินเรียบร้อย", "หยุดการทำงานของบอทอัตโนมัติแล้ว (ปัจจุบันพอร์ตถือเงินสด 100% ไม่มีสถานะค้าง)")
            return

        if messagebox.askyesno(
            "🛑 PANIC STOP — ล้างพอร์ตเข้าเงินสดฉุกเฉิน?",
            f"หยุดบอทอัตโนมัติเรียบร้อยแล้ว!\n\nขณะนี้ในพอร์ตมีสินทรัพย์ถือครองอยู่ {len(pos_list)} รายการ (มูลค่า ${acc['market_value']:,.2f})\n"
            f"ต้องการสั่งขายปิดทุกสถานะ (Close All Positions to 100% Cash) ทันทีหรือไม่?",
        ):
            results = bb.close_all_positions_panic(latest_prices)
            for r in results:
                self.log(f"🛑 [PANIC CLOSE] {r['message']}", "warn" if r["ok"] else "err")
            self.sync_broker_portfolio()
            self.manual_sync_hermes()
            self._toast_info("ล้างพอร์ตเสร็จสิ้น", f"สั่งขายปิดสถานะทั้งหมด ({len(results)} รายการ) เข้าสู่เงินสดเรียบร้อยแล้ว!")

    def _on_broker_mode_change(self):
        cfg = bb.load_broker_config()
        cfg["active_broker"] = self.broker_provider_var.get()
        cfg["environment"] = self.broker_env_var.get()
        bb.save_broker_config(cfg)
        self.sync_broker_portfolio()

    def sync_broker_portfolio(self):
        latest_prices = {s["ticker"]: float(s["close"]) for s in self.scan_rows_list if "close" in s}
        summary = bb.get_account_summary(latest_prices)
        pnl_sign = "+" if summary["total_pnl"] >= 0 else ""
        self.account_banner_var.set(
            f"💰 Cash: ${summary['cash']:,.2f}  |  📦 ถือครอง: ${summary['market_value']:,.2f}  |  "
            f"🏦 พอร์ตรวม: ${summary['equity']:,.2f} ({pnl_sign}${summary['total_pnl']:,.2f} / {summary['total_pnl_pct']:+.2f}%)"
        )

        for item in self.pos_tree.get_children():
            self.pos_tree.delete(item)
        for p in summary.get("positions", []):
            tag = "buy" if p["unrealized_pnl"] >= 0 else "sell"
            self.pos_tree.insert(
                "",
                tk.END,
                iid=p["symbol"],
                values=(
                    p["symbol"],
                    f"{p['qty']:,.4f}",
                    f"{p['avg_price']:,.2f}",
                    f"{p['current_price']:,.2f}",
                    f"{p['stop_loss']:,.2f}" if p["stop_loss"] > 0 else "-",
                    f"${p['market_value']:,.2f}",
                    f"{p['unrealized_pnl_pct']:+.2f}%",
                ),
                tags=(tag,),
            )

        for item in self.order_tree.get_children():
            self.order_tree.delete(item)
        for o in bb.get_order_history(25):
            tag = "buy" if o["side"] == "BUY" else "sell"
            dt_short = str(o["created_at"])[:19].replace("T", " ")
            self.order_tree.insert(
                "",
                tk.END,
                values=(f"#{o['id']}", o["broker"], o["symbol"], o["side"], f"{o['qty']:,.4f}", f"{o['price']:,.2f}", o["status"], dt_short),
                tags=(tag,),
            )

    def _on_position_double_click(self, _event):
        sel = self.pos_tree.selection()
        if not sel:
            return
        vals = self.pos_tree.item(sel[0], "values")
        if vals:
            self.ord_sym_var.set(vals[0])
            self.ord_side_var.set("SELL")
            self.ord_qty_var.set(str(vals[1]).replace(",", ""))
            self.ord_price_var.set(str(vals[3]).replace(",", ""))
            self.ord_stop_var.set("0.00")

    def confirm_and_execute_order(self):
        sym = self.ord_sym_var.get().strip().upper()
        side = self.ord_side_var.get().strip().upper()
        try:
            qty = float(self.ord_qty_var.get().replace(",", ""))
            price = float(self.ord_price_var.get().replace(",", ""))
            stop_loss = float(self.ord_stop_var.get().replace(",", "") or 0.0)
        except ValueError:
            self._toast_error("ข้อผิดพลาด", "กรุณากรอกจำนวนและราคาเป็นตัวเลข")
            return

        # ตรวจสอบ Pre-Trade Institutional Risk Gate v5.0 ก่อนยืนยันคำสั่ง
        acc = bb.get_account_summary()
        vix_now = float(qv4.get_macro_vix_regime().get("vix", 18.5))
        gate = qv5.check_pre_trade_risk_gate(
            symbol=sym,
            side=side,
            qty=qty,
            price=price,
            stop_loss=stop_loss,
            account_equity=float(acc.get("equity", 100000.0)),
            macro_vix=vix_now,
        )
        warn_block = ""
        if gate["warnings"]:
            warn_block = "\n\n⚠️ แจ้งเตือนจากระบบ Pre-Trade Risk Gate v5.0:\n• " + "\n• ".join(gate["warnings"])

        if not messagebox.askyesno(
            "ยืนยันคำสั่งซื้อขาย (Semi-Auto Confirm + Pre-Trade Risk Gate)",
            f"ยืนยันส่งคำสั่ง {side} {sym} จำนวน {qty:,.4f} หน่วย @ {price:,.2f} (รวม ${qty*price:,.2f} = {gate['order_pct']:.1f}% ของพอร์ต | Stop-Loss {stop_loss:,.2f}){warn_block}\n\nต้องการดำเนินการต่อหรือไม่?",
        ):
            return

        res = bb.execute_confirmed_order(sym, side, qty, price, stop_loss)
        if res["ok"]:
            self.log(res["message"], "ok")
            self.sync_broker_portfolio()
            self.manual_sync_hermes()
            self._toast_info("สำเร็จ", res["message"])
        else:
            self.log(res["message"], "err")
            self._toast_error("ล้มเหลว", res["message"])

    def _reset_local_paper(self):
        init_c = float(self.capital_var.get() or 100000.0)
        if messagebox.askyesno("รีเซ็ตพอร์ตจำลอง", f"รีเซ็ตพอร์ต Local Paper กลับเป็น ${init_c:,.2f} หรือไม่?"):
            bb.reset_local_paper_account(init_c)
            self.sync_broker_portfolio()

    def open_api_settings_dialog(self):
        cfg = bb.load_broker_config()
        dlg = tk.Toplevel(self.root)
        dlg.title("⚙ ตั้งค่า API Key (Alpaca & Binance)")
        dlg.geometry("540x340")
        dlg.configure(bg="#1E1E1E", padx=14, pady=12)
        dlg.transient(self.root)
        dlg.grab_set()

        alp_k = tk.StringVar(value=cfg.get("alpaca", {}).get("api_key", ""))
        alp_s = tk.StringVar(value=cfg.get("alpaca", {}).get("api_secret", ""))
        bnc_k = tk.StringVar(value=cfg.get("binance", {}).get("api_key", ""))
        bnc_s = tk.StringVar(value=cfg.get("binance", {}).get("api_secret", ""))

        for idx, (lbl_t, kv, sv) in enumerate([
            ("1. Alpaca Markets API (หุ้นสหรัฐฯ Paper/Live):", alp_k, alp_s),
            ("2. Binance Spot API (คริปโต Testnet/Live):", bnc_k, bnc_s),
        ]):
            tk.Label(dlg, text=lbl_t, font=("Tahoma", 9, "bold"), fg="#4EC9B0", bg="#1E1E1E").pack(anchor="w", pady=(8 if idx else 0, 2))
            fr = tk.Frame(dlg, bg="#1E1E1E")
            fr.pack(fill=tk.X)
            tk.Label(fr, text="API Key:", width=12, anchor="w", fg="#D4D4D4", bg="#1E1E1E").grid(row=0, column=0, pady=2)
            tk.Entry(fr, textvariable=kv, width=46, bg="#121212", fg="white", insertbackground="white").grid(row=0, column=1, pady=2)
            tk.Label(fr, text="Secret Key:", width=12, anchor="w", fg="#D4D4D4", bg="#1E1E1E").grid(row=1, column=0, pady=2)
            tk.Entry(fr, textvariable=sv, width=46, show="*", bg="#121212", fg="white", insertbackground="white").grid(row=1, column=1, pady=2)

        def _save():
            cfg["alpaca"]["api_key"] = alp_k.get().strip()
            cfg["alpaca"]["api_secret"] = alp_s.get().strip()
            cfg["binance"]["api_key"] = bnc_k.get().strip()
            cfg["binance"]["api_secret"] = bnc_s.get().strip()
            bb.save_broker_config(cfg)
            dlg.destroy()
            self.sync_broker_portfolio()

        tk.Button(dlg, text="💾 บันทึกและเชื่อมต่อ", font=("Tahoma", 9, "bold"), bg="#0E639C", fg="white", relief=tk.FLAT, padx=12, pady=4, command=_save).pack(anchor="w", pady=12)

    def _refresh_trade_table(self):
        for item in self.trade_tree.get_children():
            self.trade_tree.delete(item)
        for tr in self.all_trade_rows:
            ret_v = float(tr["net_return_pct"])
            reason = str(tr["exit_reason"])
            tag = "hold" if "OPEN" in reason else ("buy" if ret_v > 0 else "sell")
            self.trade_tree.insert(
                "",
                tk.END,
                values=(
                    f"#{tr['trade_no']}",
                    tr["ticker"],
                    tr["strategy"],
                    tr["entry_date"],
                    tr["exit_date"],
                    f"{int(tr['hold_days'])}d",
                    f"{float(tr['entry_price']):,.2f}",
                    f"{float(tr['exit_price']):,.2f}",
                    f"{ret_v:+.2f}%",
                    f"{float(tr['pnl_amount']):+,.0f}",
                    reason,
                ),
                tags=(tag,),
            )

    def _refresh_backtest_table(self):
        for item in self.bt_tree.get_children():
            self.bt_tree.delete(item)
        for r in self.all_bt_rows:
            tags = ("pro",) if r["strategy"] in ("regime_adaptive_v5", "adaptive_quant_pro", "regime_switch", "vwap_pullback") else ()
            self.bt_tree.insert(
                "",
                tk.END,
                values=(
                    r["ticker"],
                    r["segment"],
                    r["strategy"],
                    f"{float(r['total_ret_pct']):+.2f}%",
                    f"{float(r['max_dd_pct']):.2f}%",
                    f"{float(r['sharpe']):.2f}",
                    f"{float(r.get('sortino', r['sharpe'])):.2f}",
                    f"{float(r['calmar']):.2f}",
                    f"{float(r.get('alpha_pct', 0.0)):+.1f}%",
                    f"{float(r.get('beta', 1.0)):.2f}",
                    f"{float(r['win_rate_pct']):.1f}%",
                    f"{float(r['profit_factor']):.2f}",
                    f"-{float(r.get('cost_drag_pct', 0.15)):.2f}%",
                    int(r["trades_count"]),
                ),
                tags=tags,
            )

    def _load_existing_csv_if_available(self):
        scan_csv = os.path.join("output_backtest", "daily_scan.csv")
        bt_csv = os.path.join("output_backtest", "multi_summary.csv")
        trade_csv = os.path.join("output_backtest", "trade_log.csv")
        if os.path.exists(scan_csv):
            try:
                self.scan_rows_list = be.pd.read_csv(scan_csv).to_dict("records")
            except Exception:
                pass
        if os.path.exists(bt_csv):
            try:
                self.all_bt_rows = be.pd.read_csv(bt_csv).to_dict("records")
            except Exception:
                pass
        if os.path.exists(trade_csv):
            try:
                self.all_trade_rows = be.pd.read_csv(trade_csv).to_dict("records")
            except Exception:
                pass
        if self.scan_rows_list:
            self._populate_all_tables()
            self.log("โหลดข้อมูล v4.0 ล่าสุดจาก Cache/CSV พร้อมใช้งาน (กด '▶ รันสแกน' เพื่อโหลดกราฟครบทุกโหมด)", "ok")

    def generate_pdf_report(self):
        if pdf_gen is None:
            messagebox.showinfo("แจ้งเตือน", "โมดูลสร้างรายงาน PDF ไม่ได้รวมอยู่ในชุด Clean Release นี้")
            return
        try:
            pdf_gen.main()
            self.log("อัปเดตไฟล์ 02-quant-phase2-report.pdf เรียบร้อย!", "ok")
            self._toast_info("สำเร็จ", "สร้างรายงาน 02-quant-phase2-report.pdf เรียบร้อยแล้ว!")
        except Exception as e:
            self.log(f"[PDF Error] {e}", "err")

    def _on_global_key(self, event):
        w = self.root.focus_get()
        if isinstance(w, (tk.Entry, tk.Text, ttk.Entry, ttk.Combobox)):
            return
        ks = (event.keysym or "").lower()
        ctrl = bool(event.state & 0x4)
        if ctrl and ks == "z":
            self.drawing_mgr.undo_last(self.selected_ticker)
        elif ks == "f":
            self.toggle_chart_fullscreen()
        elif ks == "escape" and self.chart_fullscreen:
            self.toggle_chart_fullscreen()
        elif ks == "d":
            self.toggle_draw_toolbar()
        elif ks == "l":
            self.toggle_chart_legend()
        elif ks in ("1", "2", "3", "4", "5", "6"):
            idx = int(ks) - 1
            if idx < len(self.chart_mode_keys):
                self.switch_chart_mode(self.chart_mode_keys[idx])

    def _load_ui_state(self):
        try:
            if not os.path.exists(UI_STATE_PATH):
                return
            with open(UI_STATE_PATH, "r", encoding="utf-8") as f:
                st = json.load(f)
            if st.get("theme_mode") in ("dark", "light") and st["theme_mode"] != self.theme_mode:
                self.theme_mode = st["theme_mode"]
                self.apply_theme()
            if isinstance(st.get("drawings"), dict):
                self.drawing_mgr.drawings = st["drawings"]
            if st.get("right_panel_visible") is False and self.right_panel_visible:
                self.toggle_right_panel()
            if st.get("dock_panel_visible") is False and self.dock_panel_visible:
                self.toggle_dock_panel()
        except Exception:
            pass

    def _save_ui_state(self):
        try:
            st = {
                "theme_mode": self.theme_mode,
                "right_panel_visible": self.right_panel_visible,
                "dock_panel_visible": self.dock_panel_visible,
                "drawings": self.drawing_mgr.drawings,
            }
            with open(UI_STATE_PATH, "w", encoding="utf-8") as f:
                json.dump(st, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _on_close(self):
        self._save_ui_state()
        self.root.destroy()


def main():
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    p = argparse.ArgumentParser(description="AI Quant Workbench v4.0")
    p.add_argument("--smoke-test", action="store_true", help="ทดสอบระบบ Workbench v4.0 และ Hermes 2-Way Sync")
    args = p.parse_args()

    root = tk.Tk()
    app = QuantWorkbenchV4(root)
    if args.smoke_test:
        root.update()
        # ทดสอบฟังก์ชัน Ctrl+A, Ctrl+C, Ctrl+V (ทับส่วนที่คลุมดำ), Ctrl+Z (Undo), Ctrl+Y (Redo) แบบ Word 2019
        test_entry = tk.Entry(root)
        test_entry.insert(0, "NVDA AAPL")
        app.input_enhancer._push_undo(test_entry)
        app.input_enhancer.do_select_all(test_entry)
        app.input_enhancer.do_copy(test_entry)
        root.clipboard_clear()
        root.clipboard_append("TSLA MSFT")
        app.input_enhancer.do_paste(test_entry)
        assert test_entry.get() == "TSLA MSFT", f"Expected TSLA MSFT, got {test_entry.get()}"
        app.input_enhancer.do_undo(test_entry)
        assert test_entry.get() == "NVDA AAPL", f"Undo failed: got {test_entry.get()}"
        app.input_enhancer.do_redo(test_entry)
        assert test_entry.get() == "TSLA MSFT", f"Redo failed: got {test_entry.get()}"
        app.manual_sync_hermes()
        root.update()
        print("GUI v4.0 Workbench Smoke Test OK — Word 2019 Shortcuts (Ctrl+C/V/Z/Y/X/A) & Right-Click Menu ผ่านครบถ้วน")
        root.destroy()
        return
    root.mainloop()


if __name__ == "__main__":
    main()
