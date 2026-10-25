from __future__ import annotations

from datetime import date

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gtk  # noqa: E402

from .format import date_short, money  # noqa: E402


class CostChart(Gtk.DrawingArea):
    def __init__(self) -> None:
        super().__init__()
        self._data: list[tuple[date, float]] = []
        self.set_content_height(150)
        self.set_draw_func(self._draw)

    def set_data(self, data: list[tuple[date, float]]) -> None:
        self._data = data
        self.queue_draw()

    def _draw(self, _area, cr, width: int, height: int) -> None:
        data = self._data
        if not data:
            return
        left, right, top, bottom = 12.0, 12.0, 22.0, 26.0
        plot_w = max(1.0, width - left - right)
        plot_h = max(1.0, height - top - bottom)
        maximum = max((value for _, value in data), default=0.0) or 1.0

        cr.set_source_rgba(1, 1, 1, 0.08)
        cr.rectangle(left, top, plot_w, plot_h)
        cr.fill()

        bar_gap = 6.0
        bar_w = max(2.0, (plot_w - bar_gap * (len(data) - 1)) / len(data))
        for index, (_, value) in enumerate(data):
            bar_h = plot_h * (value / maximum)
            x = left + index * (bar_w + bar_gap)
            y = top + plot_h - bar_h
            cr.set_source_rgba(0.36, 0.62, 0.98, 0.85)
            cr.rectangle(x, y, bar_w, bar_h)
            cr.fill()

        cr.set_source_rgba(1, 1, 1, 0.55)
        cr.select_font_face("Sans", 0, 0)
        cr.set_font_size(10)
        cr.move_to(left, top - 6)
        cr.show_text(f"máx {money(maximum)}")
        cr.move_to(left, height - 6)
        cr.show_text(date_short(data[0][0]))
        label = date_short(data[-1][0])
        extents = cr.text_extents(label)
        cr.move_to(width - right - extents.width, height - 6)
        cr.show_text(label)
