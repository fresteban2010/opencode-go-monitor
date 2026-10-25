from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from ..core.config import Config  # noqa: E402
from ..core.monitor import Monitor  # noqa: E402
from ..core.notify import Notifier  # noqa: E402
from .models_view import ModelsPage  # noqa: E402
from .requests_view import RequestsPage  # noqa: E402
from .settings_view import SettingsPage  # noqa: E402
from .summary import SummaryPage  # noqa: E402

APP_ID = "io.github.fresteban.OpencodeGoMonitor"
TRAY_NAME = "io.github.fresteban.OpencodeGoMonitor.Tray"


def _load_css() -> None:
    provider = Gtk.CssProvider()
    css = Path(__file__).with_name("style.css")
    provider.load_from_data(css.read_bytes())
    display = Gdk.Display.get_default()
    if display is not None:
        Gtk.StyleContext.add_provider_for_display(
            display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )


def _tray_running() -> bool:
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        reply = bus.call_sync(
            "org.freedesktop.DBus",
            "/org/freedesktop/DBus",
            "org.freedesktop.DBus",
            "NameHasOwner",
            GLib.Variant("(s)", (TRAY_NAME,)),
            None,
            Gio.DBusCallFlags.NONE,
            -1,
            None,
        )
        return bool(reply.unpack()[0])
    except Exception:  # noqa: BLE001
        return False


def _ensure_tray() -> None:
    if _tray_running():
        return
    subprocess.Popen(
        [sys.executable, "-m", "ocgm", "tray"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application, monitor: Monitor) -> None:
        super().__init__(application=app, title="OpenCode Go Monitor")
        self.monitor = monitor
        self._busy = False
        self._timer_id = 0

        self.summary_page = SummaryPage()
        self.models_page = ModelsPage()
        self.requests_page = RequestsPage()
        self.settings_page = SettingsPage(monitor.cfg, self._settings_saved)

        stack = Adw.ViewStack()
        self.stack = stack
        stack.add_titled(self.summary_page, "summary", "Resumen")
        stack.add_titled(self.models_page, "models", "Modelos")
        stack.add_titled(self.requests_page, "requests", "Peticiones")
        stack.add_titled(self.settings_page, "settings", "Ajustes")

        header = Adw.HeaderBar()
        switcher = Adw.ViewSwitcher(stack=stack)
        switcher.set_policy(Adw.ViewSwitcherPolicy.WIDE)
        header.set_title_widget(switcher)

        refresh = Gtk.Button(icon_name="view-refresh-symbolic")
        refresh.set_tooltip_text("Actualizar ahora")
        refresh.connect("clicked", lambda *_: self.refresh())
        header.pack_end(refresh)

        self.save_button = Gtk.Button(label="Guardar")
        self.save_button.add_css_class("suggested-action")
        self.save_button.set_visible(False)
        self.save_button.set_tooltip_text("Guardar ajustes")
        self.save_button.connect("clicked", lambda *_: self.settings_page.save())
        header.pack_end(self.save_button)
        stack.connect("notify::visible-child-name", self._page_changed)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)
        toolbar.set_content(stack)
        self.set_content(toolbar)

        self.set_default_size(1020, 820)
        self.set_size_request(760, 620)

        self._schedule()
        self.refresh()

    def _schedule(self) -> None:
        if self._timer_id:
            GLib.source_remove(self._timer_id)
        self._timer_id = GLib.timeout_add_seconds(self.monitor.cfg.poll_seconds, self._tick)

    def _page_changed(self, stack, _param) -> None:
        self.save_button.set_visible(stack.get_visible_child_name() == "settings")

    def _tick(self) -> bool:
        self.refresh()
        return True

    def refresh(self) -> None:
        if self._busy:
            return
        self._busy = True
        threading.Thread(target=self._work, daemon=True).start()

    def _work(self) -> None:
        self.monitor.refresh()
        state = self.monitor.summary()
        daily = self.monitor.store.daily_cost(14)
        requests = self.monitor.store.requests(1000)
        GLib.idle_add(self._apply, state, daily, requests)

    def _apply(self, state, daily, requests) -> bool:
        self._busy = False
        usage = state.usage
        updated_at = usage.fetched_at if usage is not None else None
        stale = self.monitor.is_stale()
        source = self.monitor.credential.source if self.monitor.credential else None
        self.summary_page.render(
            state, daily, updated_at, stale, self.monitor.last_error, source
        )
        self.models_page.render(state.top_models)
        self.requests_page.render(requests)
        return False

    def _settings_saved(self, cfg: Config) -> None:
        self.monitor.cfg = cfg
        self.monitor.notifier = Notifier(self.monitor.store, cfg.thresholds)
        self._schedule()
        self.refresh()


class Application(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.window: MainWindow | None = None
        self.monitor: Monitor | None = None

    def do_activate(self) -> None:  # noqa: N802
        if self.window is not None:
            self.window.present()
            return
        self.monitor = Monitor()
        self.window = MainWindow(self, self.monitor)
        self.window.connect("close-request", self._on_close)
        self.window.present()

    def _on_close(self, _window) -> bool:
        if self.monitor is not None:
            self.monitor.close()
            self.monitor = None
        self.window = None
        return False


def run(argv: list[str]) -> int:
    flags = [arg for arg in argv if arg.startswith("--")]
    no_tray = "--no-tray" in flags
    Adw.init()
    _load_css()
    if not no_tray:
        _ensure_tray()
    app = Application()
    return app.run([sys.argv[0]])
