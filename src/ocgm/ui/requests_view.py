from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk  # noqa: E402

from ..core.models import RequestItem  # noqa: E402
from .format import clock, money_small, tokens  # noqa: E402


class RequestsPage(Gtk.Box):
    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._items: list[RequestItem] = []

        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        toolbar.set_margin_top(18)
        toolbar.set_margin_bottom(12)
        toolbar.set_margin_start(24)
        toolbar.set_margin_end(24)

        title = Gtk.Label(label="Peticiones recientes · máx. 1000")
        title.set_xalign(0)
        title.add_css_class("heading")
        title.set_hexpand(True)
        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text("Filtrar por modelo o cliente")
        self.search.set_size_request(260, -1)
        self.search.connect("search-changed", lambda *_: self._apply_filter())
        self.errors_only = Gtk.Switch()
        self.errors_only.connect("notify::active", lambda *_: self._apply_filter())
        errors_label = Gtk.Label(label="Solo errores")
        errors_label.add_css_class("dim-label")

        toolbar.append(title)
        toolbar.append(self.search)
        toolbar.append(self.errors_only)
        toolbar.append(errors_label)
        self.append(toolbar)

        self.empty = Gtk.Label(label="Sin peticiones para este filtro.")
        self.empty.set_margin_top(18)
        self.empty.set_margin_bottom(6)
        self.empty.add_css_class("dim-label")
        self.append(self.empty)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)

        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.listbox.add_css_class("boxed-list")
        self.listbox.set_margin_start(24)
        self.listbox.set_margin_end(24)
        self.listbox.set_margin_bottom(24)
        self.listbox.append(self._header())
        scroller.set_child(self.listbox)
        self.append(scroller)

    def _header(self) -> Gtk.Widget:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        row.add_css_class("table-header")
        for text, width in (
            ("Hora", 60),
            ("Modelo", 0),
            ("Cliente", 70),
            ("Estado", 80),
            ("Tokens", 110),
            ("Coste", 70),
        ):
            label = Gtk.Label(label=text)
            label.set_xalign(0 if width == 0 else 1)
            if width:
                label.set_size_request(width, -1)
            else:
                label.set_hexpand(True)
            label.add_css_class("dim-label")
            row.append(label)
        return row

    def render(self, items: list[RequestItem]) -> None:
        self._items = items
        self._apply_filter()

    def _apply_filter(self) -> None:
        query = self.search.get_text().strip().lower()
        only_errors = self.errors_only.get_active()
        visible = [
            item
            for item in self._items
            if (not only_errors or item.outcome != "succeeded" or item.status_code >= 400)
            and (not query or query in item.model.lower() or query in item.app.lower())
        ]

        child = self.listbox.get_first_child()
        header = child
        while child is not None:
            nxt = child.get_next_sibling()
            if child is not header:
                self.listbox.remove(child)
            child = nxt

        self.empty.set_visible(not visible)
        for item in visible[:200]:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            row.set_margin_top(5)
            row.set_margin_bottom(5)
            outcome = "ok" if item.status_code < 400 else f"HTTP {item.status_code}"
            cells = [
                clock(item.started_at),
                item.model,
                item.app or "—",
                outcome,
                f"{tokens(item.input_tokens)} / {tokens(item.output_tokens)}",
                money_small(item.cost_usd),
            ]
            for index, (text, (_, width)) in enumerate(
                zip(cells, (("", 60), ("", 0), ("", 70), ("", 80), ("", 110), ("", 70)))
            ):
                label = Gtk.Label(label=text)
                label.set_xalign(0 if index in (0, 1, 2, 3) else 1)
                if width:
                    label.set_size_request(width, -1)
                else:
                    label.set_hexpand(True)
                if index == 1:
                    label.add_css_class("monospace")
                if index == 3 and item.status_code >= 400:
                    label.add_css_class("danger")
                row.append(label)
            self.listbox.append(row)
