from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk  # noqa: E402

from ..core.models import ModelAgg  # noqa: E402
from .format import money, tokens  # noqa: E402

COLUMNS = (("Modelo", 0), ("Peticiones", 90), ("Tokens", 120), ("Caché", 80), ("Coste", 90))


class ModelsPage(Gtk.ScrolledWindow):
    def __init__(self) -> None:
        super().__init__()
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(24)
        box.set_margin_bottom(24)
        box.set_margin_start(24)
        box.set_margin_end(24)
        clamp = Adw.Clamp(maximum_size=980)
        clamp.set_child(box)
        self.set_child(clamp)

        title = Gtk.Label(label="Consumo por modelo · 30 días")
        title.set_xalign(0)
        title.add_css_class("heading")
        box.append(title)

        self.empty = Gtk.Label(label="Sin peticiones en los últimos 30 días.")
        self.empty.set_xalign(0)
        self.empty.add_css_class("dim-label")

        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.listbox.add_css_class("boxed-list")
        self.listbox.append(self._header())
        box.append(self.listbox)
        box.append(self.empty)

    def _header(self) -> Gtk.Widget:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add_css_class("table-header")
        for label, width in COLUMNS:
            widget = Gtk.Label(label=label)
            widget.set_xalign(0 if width == 0 else 1)
            if width:
                widget.set_size_request(width, -1)
            else:
                widget.set_hexpand(True)
            widget.add_css_class("dim-label")
            row.append(widget)
        return row

    def render(self, models: list[ModelAgg]) -> None:
        child = self.listbox.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            if child is not self.listbox.get_first_child():
                self.listbox.remove(child)
            child = nxt

        self.empty.set_visible(not models)
        for model in models:
            cache_ratio = 0.0
            total_input = model.input_tokens + model.cache_read_tokens
            if total_input:
                cache_ratio = model.cache_read_tokens / total_input * 100.0
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            row.set_margin_top(6)
            row.set_margin_bottom(6)
            cells = [
                model.model,
                f"{model.requests}",
                f"{tokens(model.input_tokens)} / {tokens(model.output_tokens)}",
                f"{cache_ratio:.0f}%",
                money(model.cost_usd),
            ]
            for index, (text, (_, width)) in enumerate(zip(cells, COLUMNS)):
                widget = Gtk.Label(label=text)
                widget.set_xalign(0 if index == 0 else 1)
                if width:
                    widget.set_size_request(width, -1)
                else:
                    widget.set_hexpand(True)
                    widget.set_ellipsize(3)
                if index == 0:
                    widget.add_css_class("monospace")
                row.append(widget)
            self.listbox.append(row)
