#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mac_ui_components.py — ชุดคอมโพเนนต์ UI สไตล์ MacBook (macOS) + VS Code Pure Dark:
  1) MacExpandingCircleButton : ปุ่มไอคอนทรงกลม (34x34 px) สำหรับแถบคำสั่งบนขวา เมื่อเอาเมาส์ไปชี้จะยืดออกเป็นทรงแคปซูล (Expanding Pill) พร้อมแสดงชื่อคำสั่งและกล่อง Tooltip อธิบายหน้าที่ละเอียด
  2) RoundedButton            : ปุ่มสี่เหลี่ยมขอบมนโค้งนุ่มนวล (รัศมีโค้ง 14px) สำหรับปุ่มทั่วไปในหน้าจอ พร้อมเอฟเฟกต์ Hover Highlight
  3) RoundedFocusEntry        : ช่องกรอกข้อความ (Input Box) ล้อมด้วยกรอบสี่เหลี่ยมขอบมน เรืองแสงสีฟ้า (#0A84FF) เมื่อคลิกพิมพ์ (macOS Focus Ring)
  4) RoundedKPICard           : การ์ดสรุปผล KPI ขอบมนโค้ง พร้อมแถบสี Accent ด้านซ้ายและฟอนต์ตัวเลขชัดเจน
  5) MacTrafficLights         : จุดไฟสถานะ 3 สีสไตล์หน้าต่าง MacBook (🔴 #FF5F56, 🟡 #FFBD2E, 🟢 #27C93F) สำหรับหัวกรอบ Panel หลัก
"""

import tkinter as tk
import tkinter.font as tkfont


def _brighten_hex(hex_color: str, factor: float = 1.18) -> str:
    """เพิ่มความสว่างของสี Hex เมื่อเอาเมาส์ชี้ (Hover Effect)"""
    try:
        h = hex_color.lstrip("#")
        if len(h) != 6:
            return hex_color
        r = min(255, int(int(h[0:2], 16) * factor))
        g = min(255, int(int(h[2:4], 16) * factor))
        b = min(255, int(int(h[4:6], 16) * factor))
        return f"#{r:02X}{g:02X}{b:02X}"
    except Exception:
        return hex_color


def draw_rounded_rect(
    canvas: tk.Canvas,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    radius: float = 14.0,
    fill: str = "#252526",
    outline: str = "",
    width: float = 1.0,
):
    """วาดสี่เหลี่ยมขอบมนโค้งเนียนบน tk.Canvas ด้วยวงกลม 4 มุม + สี่เหลี่ยมผืนผ้า"""
    w = max(x2 - x1, 4.0)
    h = max(y2 - y1, 4.0)
    r = min(radius, w / 2.0, h / 2.0)

    if r <= 1.0:
        canvas.create_rectangle(x1, y1, x2, y2, fill=fill, outline=outline or fill, width=width)
        return

    # หากเป็นทรงแคปซูลเต็มตัว (2*r == h)
    if abs(2.0 * r - h) < 1.5:
        canvas.create_oval(x1, y1, x1 + h, y2, fill=fill, outline=fill)
        canvas.create_oval(x2 - h, y1, x2, y2, fill=fill, outline=fill)
        if x2 - r > x1 + r:
            canvas.create_rectangle(x1 + r, y1, x2 - r, y2, fill=fill, outline=fill)
        if outline and outline != fill and width > 0:
            canvas.create_arc(x1, y1, x1 + h, y2, start=90, extent=180, style=tk.ARC, outline=outline, width=width)
            canvas.create_arc(x2 - h, y1, x2, y2, start=-90, extent=180, style=tk.ARC, outline=outline, width=width)
            canvas.create_line(x1 + r, y1, x2 - r, y1, fill=outline, width=width)
            canvas.create_line(x1 + r, y2, x2 - r, y2, fill=outline, width=width)
        return

    # วาดเนื้อสี่เหลี่ยมขอบมน
    d = 2.0 * r
    canvas.create_oval(x1, y1, x1 + d, y1 + d, fill=fill, outline=fill)
    canvas.create_oval(x2 - d, y1, x2, y1 + d, fill=fill, outline=fill)
    canvas.create_oval(x1, y2 - d, x1 + d, y2, fill=fill, outline=fill)
    canvas.create_oval(x2 - d, y2 - d, x2, y2, fill=fill, outline=fill)
    canvas.create_rectangle(x1 + r, y1, x2 - r, y2, fill=fill, outline=fill)
    canvas.create_rectangle(x1, y1 + r, x2, y2 - r, fill=fill, outline=fill)

    # วาดเส้นขอบรอบนอกถ้ากำหนด outline
    if outline and outline != fill and width > 0:
        canvas.create_arc(x1, y1, x1 + d, y1 + d, start=90, extent=90, style=tk.ARC, outline=outline, width=width)
        canvas.create_arc(x2 - d, y1, x2, y1 + d, start=0, extent=90, style=tk.ARC, outline=outline, width=width)
        canvas.create_arc(x1, y2 - d, x1 + d, y2, start=180, extent=90, style=tk.ARC, outline=outline, width=width)
        canvas.create_arc(x2 - d, y2 - d, x2, y2, start=270, extent=90, style=tk.ARC, outline=outline, width=width)
        canvas.create_line(x1 + r, y1, x2 - r, y1, fill=outline, width=width)
        canvas.create_line(x1 + r, y2, x2 - r, y2, fill=outline, width=width)
        canvas.create_line(x1, y1 + r, x1, y2 - r, fill=outline, width=width)
        canvas.create_line(x2, y1 + r, x2, y2 - r, fill=outline, width=width)


TOOLTIP_THEME = {
    "bg": "#121721",
    "border": "#2F81F7",
    "title_fg": "#58A6FF",
    "body_fg": "#E6EDF3",
}


def set_tooltip_theme(is_dark: bool):
    """อัปเดตสีกล่อง Tooltip ให้สอดคล้องกับโหมด Dark/Light ปัจจุบัน"""
    if is_dark:
        TOOLTIP_THEME.update({
            "bg": "#121721",
            "border": "#2F81F7",
            "title_fg": "#58A6FF",
            "body_fg": "#E6EDF3",
        })
    else:
        TOOLTIP_THEME.update({
            "bg": "#FFFFFF",
            "border": "#007AFF",
            "title_fg": "#0066CC",
            "body_fg": "#1C1C1E",
        })


class MacTooltip:
    """กล่องคำอธิบายลอยรองรับทั้ง Dark/Light Mode แสดงเมื่อเอาเมาส์ชี้ปุ่มคำสั่ง"""

    def __init__(self, widget: tk.Widget, title: str, description: str):
        self.widget = widget
        self.title = title
        self.description = description
        self.tip_win: tk.Toplevel | None = None

    def show(self):
        if self.tip_win or not self.description:
            return
        try:
            x = self.widget.winfo_rootx()
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
            # ป้องกันไม่ให้กล่อง Tooltip ล้นขอบขวาของหน้าจอ
            screen_w = self.widget.winfo_screenwidth()
            if x + 260 > screen_w:
                x = max(10, screen_w - 270)

            self.tip_win = tw = tk.Toplevel(self.widget)
            tw.wm_overrideredirect(True)
            tw.wm_geometry(f"+{x}+{y}")
            tw.attributes("-topmost", True)

            frame = tk.Frame(
                tw,
                bg=TOOLTIP_THEME["bg"],
                padx=10,
                pady=6,
                highlightthickness=1,
                highlightbackground=TOOLTIP_THEME["border"],
            )
            frame.pack()
            tk.Label(
                frame,
                text=self.title,
                font=("Leelawadee UI", 9, "bold"),
                fg=TOOLTIP_THEME["title_fg"],
                bg=TOOLTIP_THEME["bg"],
                anchor="w",
            ).pack(fill=tk.X)
            tk.Label(
                frame,
                text=self.description,
                font=("Leelawadee UI", 9),
                fg=TOOLTIP_THEME["body_fg"],
                bg=TOOLTIP_THEME["bg"],
                anchor="w",
                justify=tk.LEFT,
            ).pack(fill=tk.X, pady=(2, 0))
        except Exception:
            self.tip_win = None

    def hide(self):
        if self.tip_win:
            try:
                self.tip_win.destroy()
            except Exception:
                pass
            self.tip_win = None


class MacExpandingCircleButton(tk.Canvas):
    """
    ปุ่มคำสั่งขนาดคงที่สไตล์ Quant Terminal (Zero Horizontal Reflow):
      - ไม่ขยายความกว้างขณะ Hover เพื่อไม่ให้แถบปุ่มข้างเคียงกระตุก
      - รองรับทั้งโหมดไอคอนล้วนขนาดกะทัดรัด (show_label=False) และปุ่มป้ายชื่อคงที่สำหรับ Primary/Danger CTA (show_label=True)
      - แสดงกล่อง Tooltip อธิบายรายละเอียดทันทีเมื่อเอาเมาส์ชี้
    """

    def __init__(
        self,
        parent: tk.Widget,
        icon: str,
        label: str,
        tooltip_desc: str,
        bg_color: str = "#2F81F7",
        fg_color: str = "#FFFFFF",
        parent_bg: str = "#121721",
        command=None,
        circle_size: int = 32,
        expanded_width: int = 112,
        show_label: bool = False,
        border_color: str = "",
        fixed_width: int | None = None,
    ):
        self.circle_size = max(circle_size, 32)
        self.expanded_width = expanded_width
        self.show_label = show_label
        self.icon_str = icon
        self.label_str = label
        if show_label:
            full_txt = f"{icon} {label}".strip()
            measurer = tkfont.Font(font=("Leelawadee UI", 9, "bold"))
            min_w = measurer.measure(full_txt) + 24
            base_w = fixed_width if fixed_width is not None else expanded_width
            self.fixed_width = max(base_w, min_w)
        else:
            self.fixed_width = fixed_width if fixed_width is not None else self.circle_size
        self.cur_width = self.fixed_width
        self.bg_color = bg_color
        self.hover_color = _brighten_hex(bg_color, 1.18)
        self.border_color = border_color
        self.fg_color = fg_color
        self.parent_bg = parent_bg
        self.command = command
        self.state_mode = tk.NORMAL
        self.is_hovered = False
        self._anim_job = None

        super().__init__(
            parent,
            width=self.cur_width,
            height=circle_size,
            bg=parent_bg,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )

        self.tooltip = MacTooltip(self, f"{icon} {label}", tooltip_desc)
        self._redraw()

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonRelease-1>", self._on_click)

    def _redraw(self):
        self.delete("all")
        w = self.cur_width
        h = self.circle_size
        r = 8.0

        fill_c = "#21262D" if self.state_mode == tk.DISABLED else (self.hover_color if self.is_hovered else self.bg_color)
        if self.state_mode == tk.DISABLED:
            outline_c = "#30363D"
        elif self.is_hovered:
            outline_c = "#58A6FF"
        else:
            outline_c = self.border_color or fill_c

        draw_rounded_rect(self, 1, 1, w - 1, h - 1, radius=r, fill=fill_c, outline=outline_c, width=1.0)
        if self.show_label:
            full_txt = f"{self.icon_str} {self.label_str}".strip()
            self.create_text(w / 2.0, h / 2.0, text=full_txt, fill=self.fg_color, font=("Leelawadee UI", 9, "bold"))
        else:
            self.create_text(w / 2.0, h / 2.0, text=self.icon_str, fill=self.fg_color, font=("Segoe UI Symbol", 11, "bold"))

    def _on_enter(self, _event):
        self.is_hovered = True
        self._redraw()
        self.tooltip.show()

    def _on_leave(self, _event):
        self.is_hovered = False
        self.tooltip.hide()
        self._redraw()

    def _on_click(self, _event):
        if self.state_mode != tk.DISABLED and callable(self.command):
            self.tooltip.hide()
            self.command()

    def config(self, **kwargs):
        if "state" in kwargs:
            self.state_mode = kwargs.pop("state")
        if "bg" in kwargs:
            self.bg_color = kwargs.pop("bg")
            self.hover_color = _brighten_hex(self.bg_color, 1.18)
        if "parent_bg" in kwargs:
            self.parent_bg = kwargs.pop("parent_bg")
            super().configure(bg=self.parent_bg)
        if "border_color" in kwargs:
            self.border_color = kwargs.pop("border_color")
        if "fg" in kwargs:
            self.fg_color = kwargs.pop("fg")
        if "text" in kwargs:
            raw_t = str(kwargs.pop("text")).strip()
            parts = raw_t.split(" ", 1)
            if len(parts) == 2 and len(parts[0]) <= 3:
                self.icon_str, self.label_str = parts[0], parts[1]
            else:
                self.label_str = raw_t
            self.tooltip.title = f"{self.icon_str} {self.label_str}".strip()
        if kwargs:
            super().configure(**kwargs)
        self._redraw()

    configure = config


class MacExpandingRectButton(tk.Canvas):
    """
    ปุ่มสี่เหลี่ยมขอบมนยืดหดได้ (Expanding Rounded-Rectangle Button, รัศมีโค้ง 14px):
      - คงรูปทรงสี่เหลี่ยมขอบมนตลอดเวลา (ไม่เป็นวงกลม)
      - เวลาปกติ (เมื่อไม่ได้เลือกและไม่ได้ชี้เมาส์): หดเป็นสี่เหลี่ยมขอบมนขนาดกะทัดรัด แสดงไอคอน + เลขหัวข้อ (เช่น '🎯 1', '🏛 2') ประหยัดพื้นที่และดูง่าย
      - เวลาเอาเมาส์ไปชี้ (<Enter>) หรือเป็นโหมดที่กำลังเลือกอยู่ (Active): ยืดออกเป็นสี่เหลี่ยมขอบมนขนาดเต็ม แสดงชื่อการวิเคราะห์ครบถ้วน พร้อมกล่อง Tooltip อธิบายรายละเอียด
    """

    def __init__(
        self,
        parent: tk.Widget,
        short_text: str,
        full_text: str,
        tooltip_desc: str = "",
        bg_color: str = "#2D2D2D",
        active_bg: str = "#0A84FF",
        fg_color: str = "#D4D4D4",
        active_fg: str = "#FFFFFF",
        parent_bg: str | None = None,
        command=None,
        compact_width: int = 66,
        expanded_width: int = 205,
        height: int = 30,
        radius: float = 14.0,
        is_active: bool = False,
    ):
        self.short_text = short_text
        self.full_text = full_text
        self.bg_color = bg_color
        self.hover_color = _brighten_hex(bg_color, 1.22)
        self.active_bg = active_bg
        self.fg_color = fg_color
        self.active_fg = active_fg
        self.command = command
        self.compact_width = compact_width
        self.expanded_width = max(expanded_width, int(len(full_text) * 6.8) + 24)
        self.btn_h = height
        self.radius = radius
        self.is_active = is_active
        self.is_hovered = False
        self.state_mode = tk.NORMAL
        self._anim_job = None

        if parent_bg is None:
            try:
                parent_bg = parent.cget("bg")
            except Exception:
                parent_bg = "#252526"
        self.parent_bg = parent_bg

        self.cur_width = self.expanded_width if self.is_active else self.compact_width

        super().__init__(
            parent,
            width=self.cur_width,
            height=self.btn_h,
            bg=self.parent_bg,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )

        self.tooltip = MacTooltip(self, full_text, tooltip_desc)
        self._redraw()

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonRelease-1>", self._on_click)

    def _target_width(self) -> int:
        return self.expanded_width if (self.is_active or self.is_hovered) else self.compact_width

    def _redraw(self):
        self.delete("all")
        try:
            p_bg = self.master.cget("bg")
            if p_bg != self.parent_bg:
                self.parent_bg = p_bg
                super().configure(bg=p_bg)
        except Exception:
            pass

        w, h = self.cur_width, self.btn_h
        if self.state_mode == tk.DISABLED:
            fill_c = "#3C3C3C"
            txt_c = "#888888"
            outline_c = fill_c
        elif self.is_active:
            fill_c = _brighten_hex(self.active_bg, 1.10) if self.is_hovered else self.active_bg
            txt_c = self.active_fg
            outline_c = "#9CDCFE" if self.is_hovered else self.active_bg
        elif self.is_hovered:
            fill_c = self.hover_color
            txt_c = "#FFFFFF"
            outline_c = "#0A84FF"
        else:
            fill_c = self.bg_color
            txt_c = self.fg_color
            outline_c = "#3C3C3C"

        # วาดสี่เหลี่ยมขอบมน (บังคับให้คงรูปทรงสี่เหลี่ยมขอบมน ไม่ให้กลายเป็นวงกลม)
        rect_r = min(self.radius, (h - 6) / 2.0, 10.0)
        draw_rounded_rect(self, 1, 1, w - 1, h - 1, radius=rect_r, fill=fill_c, outline=outline_c, width=1.2)

        show_full = w >= (self.compact_width + self.expanded_width) * 0.52
        display_txt = self.full_text if show_full else self.short_text
        self.create_text(w / 2.0, h / 2.0, text=display_txt, fill=txt_c, font=("Leelawadee UI", 9, "bold"))

    def _animate_to(self, target_w: int):
        if self._anim_job:
            try:
                self.after_cancel(self._anim_job)
            except Exception:
                pass
            self._anim_job = None

        diff = target_w - self.cur_width
        if abs(diff) <= 10:
            self.cur_width = target_w
            super().configure(width=self.cur_width)
            self._redraw()
            return

        step = int(diff * 0.52)
        if step == 0:
            step = 1 if diff > 0 else -1
        self.cur_width += step
        super().configure(width=self.cur_width)
        self._redraw()
        self._anim_job = self.after(14, lambda: self._animate_to(target_w))

    def set_active(self, active: bool, bg_color: str | None = None, fg_color: str | None = None):
        if bg_color is not None:
            self.bg_color = bg_color
            self.hover_color = _brighten_hex(bg_color, 1.22)
        if fg_color is not None:
            self.fg_color = fg_color
        self.is_active = active
        self._animate_to(self._target_width())

    def _on_enter(self, _event):
        self.is_hovered = True
        self._animate_to(self._target_width())
        self.tooltip.show()

    def _on_leave(self, _event):
        self.is_hovered = False
        self.tooltip.hide()
        self._animate_to(self._target_width())

    def _on_click(self, _event):
        if self.state_mode != tk.DISABLED and callable(self.command):
            self.tooltip.hide()
            self.command()

    def config(self, **kwargs):
        if "bg" in kwargs:
            b = kwargs.pop("bg")
            if b == "#0A84FF":
                self.set_active(True)
            else:
                self.set_active(False, bg_color=b)
        if "fg" in kwargs:
            f = kwargs.pop("fg")
            if not self.is_active:
                self.fg_color = f
        if "state" in kwargs:
            self.state_mode = kwargs.pop("state")
        if "parent_bg" in kwargs:
            self.parent_bg = kwargs.pop("parent_bg")
            super().configure(bg=self.parent_bg)
        if kwargs:
            super().configure(**kwargs)
        self._redraw()

    configure = config


class RoundedButton(tk.Canvas):
    """
    ปุ่มสี่เหลี่ยมขอบมนโค้งมากสไตล์ Modern App (รัศมีโค้ง 14px ตามที่ผู้ใช้เลือก)
    ใช้สำหรับปุ่มทั่วไปในหน้าจอทั้งหมด พร้อมเอฟเฟกต์สว่างขึ้นเมื่อเอาเมาส์ชี้
    """

    def __init__(
        self,
        parent: tk.Widget,
        text: str,
        command=None,
        bg: str = "#0E639C",
        fg: str = "#FFFFFF",
        parent_bg: str | None = None,
        font=("Leelawadee UI", 9, "bold"),
        padx: int = 12,
        pady: int = 5,
        radius: float = 14.0,
        width: int | None = None,
        height: int | None = None,
    ):
        self.text_str = text
        self.command = command
        self.bg_color = bg
        self.hover_color = _brighten_hex(bg, 1.18)
        self.fg_color = fg
        self.font_spec = font
        self.radius = radius
        self.is_hovered = False
        self.state_mode = tk.NORMAL

        if parent_bg is None:
            try:
                parent_bg = parent.cget("bg")
            except Exception:
                parent_bg = "#1E1E1E"
        self.parent_bg = parent_bg

        measurer = tkfont.Font(font=self.font_spec)
        text_w = measurer.measure(text)
        text_h = measurer.metrics("linespace")
        min_w = text_w + max(padx * 2, 22)
        min_h = max(text_h + 12, 30)
        est_w = max(width, min_w) if width else max(60, min_w)
        est_h = max(height, min_h) if height else max(30, min_h)
        self.btn_w = est_w
        self.btn_h = est_h

        super().__init__(
            parent,
            width=self.btn_w,
            height=self.btn_h,
            bg=self.parent_bg,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self._redraw()

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonRelease-1>", self._on_click)
        self.bind("<Configure>", self._on_resize)

    def _on_resize(self, event):
        if event.width > 10 and event.height > 10:
            self.btn_w = event.width
            self.btn_h = event.height
            self._redraw()

    def _redraw(self):
        self.delete("all")
        try:
            p_bg = self.master.cget("bg")
            if p_bg != self.parent_bg:
                self.parent_bg = p_bg
                super().configure(bg=p_bg)
        except Exception:
            pass

        w, h = self.btn_w, self.btn_h
        fill_c = "#3C3C3C" if self.state_mode == tk.DISABLED else (self.hover_color if self.is_hovered else self.bg_color)
        outline_c = "#569CD6" if self.is_hovered and self.state_mode != tk.DISABLED else fill_c

        draw_rounded_rect(self, 1, 1, w - 1, h - 1, radius=self.radius, fill=fill_c, outline=outline_c, width=1.0)
        self.create_text(w / 2.0, h / 2.0, text=self.text_str, fill=self.fg_color, font=self.font_spec)

    def _on_enter(self, _event):
        self.is_hovered = True
        self._redraw()

    def _on_leave(self, _event):
        self.is_hovered = False
        self._redraw()

    def _on_click(self, _event):
        if self.state_mode != tk.DISABLED and callable(self.command):
            self.command()

    def config(self, **kwargs):
        if "text" in kwargs:
            self.text_str = kwargs.pop("text")
        if "bg" in kwargs:
            self.bg_color = kwargs.pop("bg")
            self.hover_color = _brighten_hex(self.bg_color, 1.18)
        if "fg" in kwargs:
            self.fg_color = kwargs.pop("fg")
        if "state" in kwargs:
            self.state_mode = kwargs.pop("state")
        if "parent_bg" in kwargs:
            self.parent_bg = kwargs.pop("parent_bg")
            super().configure(bg=self.parent_bg)
        if kwargs:
            super().configure(**kwargs)
        self._redraw()

    configure = config


class RoundedFocusEntry(tk.Canvas):
    """
    ช่องใส่ข้อความ (Entry) ล้อมด้วยกรอบสี่เหลี่ยมขอบมน (11px)
    เมื่อคลิกพิมพ์จะเรืองแสงขอบสีฟ้า macOS (#0A84FF Focus Ring)
    """

    def __init__(
        self,
        parent: tk.Widget,
        textvariable: tk.StringVar,
        width: int = 12,
        font=("Consolas", 10),
        fg: str = "#4EC9B0",
        bg: str = "#121212",
        parent_bg: str = "#181818",
        height: int = 28,
    ):
        self.entry_bg = bg
        self.parent_bg = parent_bg
        self.is_focused = False
        px_w = max(52, int(width * 8.2) + 18)
        self.box_w = px_w
        self.box_h = height

        super().__init__(
            parent,
            width=self.box_w,
            height=self.box_h,
            bg=parent_bg,
            highlightthickness=0,
            bd=0,
        )

        self.entry = tk.Entry(
            self,
            textvariable=textvariable,
            width=width,
            font=font,
            bg=bg,
            fg=fg,
            insertbackground="white",
            relief=tk.FLAT,
            bd=0,
            highlightthickness=0,
        )
        self.entry.bind("<FocusIn>", self._on_focus_in, add="+")
        self.entry.bind("<FocusOut>", self._on_focus_out, add="+")
        self._redraw()

    def _on_focus_in(self, _event):
        self.is_focused = True
        self._redraw()

    def _on_focus_out(self, _event):
        self.is_focused = False
        self._redraw()

    def _redraw(self):
        self.delete("bg_rect")
        border_c = "#0A84FF" if self.is_focused else "#3C3C3C"
        bw = 1.6 if self.is_focused else 1.0
        draw_rounded_rect(self, 1, 1, self.box_w - 1, self.box_h - 1, radius=10.0, fill=self.entry_bg, outline=border_c, width=bw)
        self.create_window(self.box_w / 2.0, self.box_h / 2.0, window=self.entry, width=self.box_w - 14, height=self.box_h - 8)


def create_mac_traffic_lights(parent: tk.Widget, bg_color: str = "#252526") -> tk.Canvas:
    """สร้างจุดไฟ 3 สีสไตล์หน้าต่าง MacBook (🔴 #FF5F56, 🟡 #FFBD2E, 🟢 #27C93F) สำหรับวางหน้าหัวข้อ Panel"""
    cv = tk.Canvas(parent, width=50, height=16, bg=bg_color, highlightthickness=0, bd=0)
    dots = [
        (8, "#FF5F56"),
        (24, "#FFBD2E"),
        (40, "#27C93F"),
    ]
    for cx, col in dots:
        cv.create_oval(cx - 5, 3, cx + 5, 13, fill=col, outline=col)
    return cv


class MacSegmentedControl(tk.Canvas):
    """
    แถบเลือกโหมดสไตล์ macOS Segmented Control (นิ่ง ไม่กระตุกเวลา Hover)
    รวมปุ่มไว้ในรางแคปซูลเดียว พร้อม Tooltip อธิบายเมื่อเอาเมาส์ชี้
    """

    def __init__(
        self,
        parent: tk.Widget,
        items: list[tuple[str, str, str]],  # [(key, label, tooltip_desc), ...]
        active_key: str,
        command=None,
        parent_bg: str = "#1C1C1E",
        track_bg: str = "#2C2C2E",
        active_bg: str = "#0A84FF",
        hover_bg: str = "#3A3A3C",
        fg: str = "#AEAEB2",
        active_fg: str = "#FFFFFF",
        border_color: str = "#3A3A3C",
        height: int = 32,
        font=("Leelawadee UI", 9, "bold"),
    ):
        self.items = items
        self.active_key = active_key
        self.command = command
        self.parent_bg = parent_bg
        self.track_bg = track_bg
        self.active_bg = active_bg
        self.hover_bg = hover_bg
        self.fg = fg
        self.active_fg = active_fg
        self.border_color = border_color
        self.ctrl_h = height
        self.font = font
        self.hover_key: str | None = None
        self.segment_rects: list[tuple[str, float, float, str]] = []

        # วัดความกว้างและความสูงจริงของข้อความเป็นพิกเซล (เผื่อสระ/วรรณยุกต์ภาษาไทยให้ไม่อึดอัด)
        measurer = tkfont.Font(font=self.font)
        linespace = measurer.metrics("linespace")
        self.ctrl_h = max(height, linespace + 14, 34)
        self.seg_widths = [max(74, measurer.measure(lbl) + 32) for _, lbl, _ in items]
        self.total_w = sum(self.seg_widths) + 8

        super().__init__(
            parent,
            width=self.total_w,
            height=self.ctrl_h,
            bg=parent_bg,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self.tooltip = MacTooltip(self, "", "")
        self.bind("<Motion>", self._on_motion)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)
        self._redraw()

    def _hit_test(self, x: float) -> tuple[str | None, str]:
        for key, x1, x2, desc in self.segment_rects:
            if x1 <= x <= x2:
                return key, desc
        return None, ""

    def _on_motion(self, event):
        key, desc = self._hit_test(event.x)
        if key != self.hover_key:
            self.hover_key = key
            self._redraw()
            self.tooltip.hide()
            if key and desc:
                lbl = next((l for k, l, _ in self.items if k == key), "")
                self.tooltip.title = lbl
                self.tooltip.description = desc
                self.tooltip.show()

    def _on_leave(self, _event):
        if self.hover_key is not None:
            self.hover_key = None
            self._redraw()
        self.tooltip.hide()

    def _on_click(self, event):
        key, _ = self._hit_test(event.x)
        if key and key != self.active_key:
            self.active_key = key
            self._redraw()
            if self.command:
                self.command(key)

    def set_active(self, key: str):
        if self.active_key != key:
            self.active_key = key
            self._redraw()

    def set_theme(self, parent_bg: str, track_bg: str, active_bg: str, hover_bg: str, fg: str, active_fg: str, border_color: str):
        self.parent_bg = parent_bg
        self.track_bg = track_bg
        self.active_bg = active_bg
        self.hover_bg = hover_bg
        self.fg = fg
        self.active_fg = active_fg
        self.border_color = border_color
        super().configure(bg=parent_bg)
        self._redraw()

    def _redraw(self):
        self.delete("all")
        self.segment_rects.clear()
        w, h = self.total_w, self.ctrl_h
        draw_rounded_rect(self, 1, 1, w - 1, h - 1, radius=10.0, fill=self.track_bg, outline=self.border_color, width=1.0)

        x = 3.0
        pad_y = 3.0
        for (key, lbl, desc), seg_w in zip(self.items, self.seg_widths):
            x1, x2 = x, x + seg_w
            is_act = key == self.active_key
            is_hov = key == self.hover_key
            if is_act:
                draw_rounded_rect(self, x1, pad_y, x2, h - pad_y, radius=8.0, fill=self.active_bg, outline="")
            elif is_hov:
                draw_rounded_rect(self, x1, pad_y, x2, h - pad_y, radius=8.0, fill=self.hover_bg, outline="")
            txt_col = self.active_fg if is_act else self.fg
            self.create_text((x1 + x2) / 2.0, h / 2.0, text=lbl, fill=txt_col, font=self.font)
            self.segment_rects.append((key, x1, x2, desc))
            x += seg_w


class MacToastManager:
    """
    แจ้งเตือนแบบ Toast สไตล์ macOS (มุมขวาล่างของหน้าต่าง หายเองอัตโนมัติ ไม่บล็อกการทำงาน)
    ใช้แทน messagebox.showinfo / showerror ที่ต้องกด OK ทุกครั้ง
    """

    KIND_STYLE = {
        "info": ("#0A84FF", "●"),
        "ok": ("#30D158", "●"),
        "warn": ("#FFD60A", "●"),
        "error": ("#FF453A", "●"),
    }

    def __init__(self, root: tk.Tk):
        self.root = root
        self.active: list[tk.Toplevel] = []

    def show(self, title: str, message: str, kind: str = "info", duration_ms: int = 3500):
        accent, dot = self.KIND_STYLE.get(kind, self.KIND_STYLE["info"])
        try:
            tw = tk.Toplevel(self.root)
            tw.wm_overrideredirect(True)
            tw.attributes("-topmost", True)
            try:
                tw.attributes("-alpha", 0.96)
            except Exception:
                pass

            frame = tk.Frame(tw, bg="#2C2C2E", padx=14, pady=10, highlightthickness=1, highlightbackground="#3A3A3C")
            frame.pack()
            head = tk.Frame(frame, bg="#2C2C2E")
            head.pack(fill=tk.X)
            tk.Label(head, text=dot, font=("Segoe UI", 10), fg=accent, bg="#2C2C2E").pack(side=tk.LEFT, padx=(0, 6))
            tk.Label(head, text=title, font=("Leelawadee UI", 10, "bold"), fg="#F5F5F7", bg="#2C2C2E", anchor="w").pack(side=tk.LEFT)
            if message:
                tk.Label(
                    frame,
                    text=message,
                    font=("Leelawadee UI", 9),
                    fg="#D1D1D6",
                    bg="#2C2C2E",
                    anchor="w",
                    justify=tk.LEFT,
                    wraplength=320,
                ).pack(fill=tk.X, pady=(4, 0))

            # คลิกที่ Toast เพื่อปิดทันที
            for w in (tw, frame, head, *frame.winfo_children(), *head.winfo_children()):
                w.bind("<Button-1>", lambda _e, win=tw: self._dismiss(win))

            self.active.append(tw)
            self._reposition()
            tw.after(duration_ms, lambda win=tw: self._dismiss(win))
        except Exception:
            pass

    def _dismiss(self, win: tk.Toplevel):
        if win in self.active:
            self.active.remove(win)
        try:
            win.destroy()
        except Exception:
            pass
        self._reposition()

    def _reposition(self):
        try:
            self.root.update_idletasks()
            rx = self.root.winfo_rootx() + self.root.winfo_width()
            ry = self.root.winfo_rooty() + self.root.winfo_height()
            y = ry - 18
            for win in reversed(self.active):
                win.update_idletasks()
                w, h = win.winfo_reqwidth(), win.winfo_reqheight()
                y -= h
                win.wm_geometry(f"+{rx - w - 18}+{y}")
                y -= 8
        except Exception:
            pass
