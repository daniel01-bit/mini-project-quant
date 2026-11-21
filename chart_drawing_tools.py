#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
chart_drawing_tools.py — เครื่องมือวาดกราฟแบบทำมือสไตล์ TradingView สำหรับ Matplotlib Canvas
รองรับ:
  - cursor : Crosshair ดูราคาและวันที่แบบสด
  - hline  : เส้นแนวรับ-แนวต้านแนวนอน (คลิก 1 ครั้ง) พร้อมป้ายราคา
  - trend  : เส้นแนวโน้ม Trendline (คลิก 2 จุด) พร้อมเส้น Preview ตามเมาส์
  - fibo   : Fibonacci Retracement 0% - 100% (คลิก 2 จุด) พร้อมป้ายระดับราคา
"""

import matplotlib.dates as mdates


FIBO_LEVELS = [
    (0.0, "#8E8E93"),
    (0.236, "#64D2FF"),
    (0.382, "#30D158"),
    (0.5, "#FFD60A"),
    (0.618, "#FF9F0A"),
    (0.786, "#BF5AF2"),
    (1.0, "#FF453A"),
]


class ChartDrawingManager:
    """จัดการเส้นวาดทำมือต่อหุ้นแต่ละตัว พร้อม Live Preview และ Crosshair"""

    def __init__(self, on_redraw=None, on_status=None):
        self.on_redraw = on_redraw
        self.on_status = on_status
        self.active_tool: str = "cursor"
        self.drawings: dict[str, list[dict]] = {}
        self.pending_pt: tuple[float, float] | None = None
        self.active_ax = None
        self.active_ticker: str = ""
        self.active_theme: dict = {}
        self._preview_artists: list = []
        self._crosshair_artists: list = []

    def set_tool(self, tool: str):
        self.active_tool = tool
        self.pending_pt = None
        self._clear_preview()

    def attach_axis(self, ax, ticker: str, theme: dict):
        self.active_ax = ax
        self.active_ticker = ticker
        self.active_theme = theme
        self._preview_artists.clear()
        self._crosshair_artists.clear()
        self.render(ax, ticker, theme)

    def detach_axis(self):
        self.active_ax = None
        self._preview_artists.clear()
        self._crosshair_artists.clear()

    def undo_last(self, ticker: str):
        self.pending_pt = None
        items = self.drawings.get(ticker, [])
        if items:
            items.pop()
            if self.on_redraw:
                self.on_redraw()

    def clear_ticker(self, ticker: str):
        self.pending_pt = None
        self.drawings[ticker] = []
        if self.on_redraw:
            self.on_redraw()

    def _clear_preview(self):
        for art in self._preview_artists:
            try:
                art.remove()
            except Exception:
                pass
        self._preview_artists.clear()

    def _clear_crosshair(self):
        for art in self._crosshair_artists:
            try:
                art.remove()
            except Exception:
                pass
        self._crosshair_artists.clear()

    def _format_x(self, x_val: float) -> str:
        try:
            if x_val > 10000:
                return mdates.num2date(x_val).strftime("%Y-%m-%d")
        except Exception:
            pass
        return f"x={x_val:.1f}"

    def on_click(self, event, canvas):
        if self.active_ax is None or event.inaxes != self.active_ax:
            return
        if event.button == 3:
            # คลิกขวาเพื่อยกเลิกจุดที่กำลังลากค้างอยู่
            self.pending_pt = None
            self._clear_preview()
            canvas.draw_idle()
            return
        if event.button != 1 or event.xdata is None or event.ydata is None:
            return

        x, y = float(event.xdata), float(event.ydata)
        ticker = self.active_ticker
        if not ticker:
            return
        self.drawings.setdefault(ticker, [])

        if self.active_tool == "hline":
            self.drawings[ticker].append({"type": "hline", "y": y})
            if self.on_redraw:
                self.on_redraw()
        elif self.active_tool in ("trend", "fibo"):
            if self.pending_pt is None:
                self.pending_pt = (x, y)
                if self.on_status:
                    self.on_status(f"เลือกจุดเริ่มต้นแล้ว ({y:,.2f}) — คลิกจุดที่ 2 เพื่อวางเส้น (คลิกขวาเพื่อยกเลิก)")
            else:
                x1, y1 = self.pending_pt
                self.pending_pt = None
                self._clear_preview()
                self.drawings[ticker].append(
                    {"type": self.active_tool, "x1": x1, "y1": y1, "x2": x, "y2": y}
                )
                if self.on_redraw:
                    self.on_redraw()

    def on_motion(self, event, canvas):
        if self.active_ax is None or event.inaxes != self.active_ax:
            self._clear_crosshair()
            canvas.draw_idle()
            return
        if event.xdata is None or event.ydata is None:
            return

        x, y = float(event.xdata), float(event.ydata)

        # อัปเดต Crosshair บางๆ
        self._clear_crosshair()
        c_col = self.active_theme.get("sub_fg", "#8E8E93")
        self._crosshair_artists.append(self.active_ax.axhline(y, color=c_col, linestyle=":", linewidth=0.7, alpha=0.55))
        self._crosshair_artists.append(self.active_ax.axvline(x, color=c_col, linestyle=":", linewidth=0.7, alpha=0.55))

        if self.on_status:
            self.on_status(f"{self.active_ticker} | {self._format_x(x)} | Price: {y:,.2f}")

        # วาด Preview ระหว่างลากจุดที่ 2
        self._clear_preview()
        if self.pending_pt is not None and self.active_tool in ("trend", "fibo"):
            x1, y1 = self.pending_pt
            if self.active_tool == "trend":
                (ln,) = self.active_ax.plot([x1, x], [y1, y], color="#0A84FF", linestyle="--", linewidth=1.5, alpha=0.85)
                self._preview_artists.append(ln)
            elif self.active_tool == "fibo":
                x_min, x_max = min(x1, x), max(x1, x)
                for lvl, col in FIBO_LEVELS:
                    yv = y1 + (y - y1) * lvl
                    (ln,) = self.active_ax.plot([x_min, x_max], [yv, yv], color=col, linestyle="--", linewidth=1.0, alpha=0.7)
                    self._preview_artists.append(ln)

        canvas.draw_idle()

    def render(self, ax, ticker: str, theme: dict):
        items = self.drawings.get(ticker, [])
        if not items:
            return

        x_lim = ax.get_xlim()
        for item in items:
            kind = item.get("type")
            if kind == "hline":
                y = item["y"]
                ax.axhline(y, color="#FFD60A", linestyle="--", linewidth=1.3, alpha=0.9)
                ax.text(
                    x_lim[1],
                    y,
                    f" {y:,.2f} ",
                    color="#1C1C1E",
                    fontsize=7.5,
                    weight="bold",
                    va="center",
                    ha="right",
                    bbox=dict(boxstyle="round,pad=0.18", facecolor="#FFD60A", edgecolor="none", alpha=0.9),
                )
            elif kind == "trend":
                ax.plot(
                    [item["x1"], item["x2"]],
                    [item["y1"], item["y2"]],
                    color="#0A84FF",
                    linestyle="-",
                    linewidth=1.8,
                    marker="o",
                    markersize=4,
                )
            elif kind == "fibo":
                x1, x2 = min(item["x1"], item["x2"]), max(item["x1"], item["x2"])
                y1, y2 = item["y1"], item["y2"]
                for lvl, col in FIBO_LEVELS:
                    yv = y1 + (y2 - y1) * lvl
                    ax.plot([x1, x2], [yv, yv], color=col, linestyle="-", linewidth=1.1, alpha=0.85)
                    ax.text(
                        x2,
                        yv,
                        f" {lvl * 100:.1f}% ({yv:,.2f})",
                        color=col,
                        fontsize=7.2,
                        weight="bold",
                        va="center",
                        ha="left",
                    )
