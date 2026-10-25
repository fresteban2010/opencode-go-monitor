from __future__ import annotations

import os
import subprocess
import sys
import threading

from .core.config import load, paths
from .core.monitor import Monitor

SNI_XML = """
<node>
  <interface name="org.kde.StatusNotifierItem">
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="WindowId" type="i" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="IconPixmap" type="a(iiay)" access="read"/>
    <property name="OverlayIconName" type="s" access="read"/>
    <property name="AttentionIconName" type="s" access="read"/>
    <property name="AttentionMovieName" type="s" access="read"/>
    <property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <property name="Menu" type="o" access="read"/>
    <method name="ContextMenu"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
    <method name="Activate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
    <method name="SecondaryActivate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
    <method name="Scroll"><arg type="i" direction="in"/><arg type="s" direction="in"/></method>
    <signal name="NewIcon"/>
    <signal name="NewToolTip"/>
    <signal name="NewStatus"><arg type="s"/></signal>
    <signal name="NewTitle"/>
  </interface>
</node>
"""

MENU_XML = """
<node>
  <interface name="com.canonical.dbusmenu">
    <property name="Version" type="u" access="read"/>
    <property name="TextDirection" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconThemePath" type="as" access="read"/>
    <method name="GetLayout">
      <arg type="i" direction="in"/><arg type="i" direction="in"/><arg type="as" direction="in"/>
      <arg type="u" direction="out"/><arg type="(ia{sv}av)" direction="out"/>
    </method>
    <method name="GetGroupProperties">
      <arg type="ai" direction="in"/><arg type="as" direction="in"/>
      <arg type="a(ia{sv})" direction="out"/>
    </method>
    <method name="GetProperty">
      <arg type="i" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="out"/>
    </method>
    <method name="Event">
      <arg type="i" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="in"/><arg type="u" direction="in"/>
    </method>
    <method name="EventGroup">
      <arg type="a(isvu)" direction="in"/><arg type="ai" direction="out"/>
    </method>
    <method name="AboutToShow"><arg type="i" direction="in"/><arg type="b" direction="out"/></method>
    <method name="AboutToShowGroup">
      <arg type="ai" direction="in"/><arg type="ai" direction="out"/><arg type="ai" direction="out"/>
    </method>
    <signal name="LayoutUpdated"><arg type="u"/><arg type="i"/></signal>
  </interface>
</node>
"""

ICONS = {"ok": "emblem-ok-symbolic", "warn": "dialog-warning", "danger": "dialog-error"}
LABELS = {"rolling": "5 h", "weekly": "sem", "monthly": "mes"}


def severity_for(percent: float, thresholds: tuple[int, ...]) -> str:
    warn = thresholds[0] if thresholds else 70
    danger = thresholds[1] if len(thresholds) > 1 else warn
    if percent >= danger:
        return "danger"
    if percent >= warn:
        return "warn"
    return "ok"

class Tray:
    def __init__(self, monitor: Monitor | None = None) -> None:
        from gi.repository import Gio, GLib

        self.Gio = Gio
        self.GLib = GLib
        self.monitor = monitor or Monitor(load())
        self.cfg = self.monitor.cfg
        self._loop = GLib.MainLoop()
        self._refreshing = False
        self._timer_id = 0
        self._revision = 1
        self._title = "OpenCode Go"
        self._subtitle = "Cargando…"
        self._icon = ICONS["ok"]
        self._menu_labels = {"open": "Abrir", "refresh": "Actualizar", "quit": "Salir"}

        self.conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self._own_name()

        self._sni_info = Gio.DBusNodeInfo.new_for_xml(SNI_XML).interfaces[0]
        self._menu_info = Gio.DBusNodeInfo.new_for_xml(MENU_XML).interfaces[0]
        self._sni_values = {
            "Category": ("s", "ApplicationStatus"),
            "Id": ("s", "opencode-go-monitor"),
            "Title": ("s", "OpenCode Go"),
            "Status": ("s", "Active"),
            "WindowId": ("i", 0),
            "IconName": ("s", self._icon),
            "IconPixmap": ("a(iiay)", []),
            "OverlayIconName": ("s", ""),
            "AttentionIconName": ("s", ""),
            "AttentionMovieName": ("s", ""),
            "ToolTip": ("(sa(iiay)ss)", (self._icon, [], self._title, self._subtitle)),
            "ItemIsMenu": ("b", False),
            "Menu": ("o", "/MenuBar"),
        }

        self.conn.register_object(
            "/StatusNotifierItem", self._sni_info, self._sni_method, self._sni_property, None
        )
        self.conn.register_object(
            "/MenuBar", self._menu_info, self._menu_method, self._menu_property, None
        )
        self._register_watcher()

    def _own_name(self) -> None:
        reply = self.conn.call_sync(
            "org.freedesktop.DBus",
            "/org/freedesktop/DBus",
            "org.freedesktop.DBus",
            "RequestName",
            self.GLib.Variant("(su)", ("io.github.fresteban.OpencodeGoMonitor.Tray", 4)),
            None,
            self.Gio.DBusCallFlags.NONE,
            -1,
            None,
        )
        if reply.unpack()[0] != 1:
            raise RuntimeError("La bandeja ya está en ejecución")

    def _register_watcher(self) -> None:
        name = f"org.kde.StatusNotifierItem-{os.getpid()}-1"
        self.conn.call_sync(
            "org.freedesktop.DBus",
            "/org/freedesktop/DBus",
            "org.freedesktop.DBus",
            "RequestName",
            self.GLib.Variant("(su)", (name, 4)),
            None,
            self.Gio.DBusCallFlags.NONE,
            -1,
            None,
        )
        try:
            self.conn.call_sync(
                "org.kde.StatusNotifierWatcher",
                "/StatusNotifierWatcher",
                "org.kde.StatusNotifierWatcher",
                "RegisterStatusNotifierItem",
                self.GLib.Variant("(s)", (name,)),
                None,
                self.Gio.DBusCallFlags.NONE,
                -1,
                None,
            )
        except Exception:  # noqa: BLE001 - no watcher (p.ej. GNOME sin extensión)
            pass

    def _sni_property(self, _conn, _sender, _path, _iface, prop):
        signature, value = self._sni_values[prop]
        return self.GLib.Variant(signature, value)

    def _sni_method(self, _conn, _sender, _path, _iface, method, params, invocation):
        if method in ("Activate", "SecondaryActivate", "ContextMenu"):
            self.open_window()
        elif method == "Scroll":
            self.refresh()
        invocation.return_value(None)

    def _menu_property(self, _conn, _sender, _path, _iface, prop):
        from gi.repository import GLib

        values = {
            "Version": GLib.Variant("u", 3),
            "TextDirection": GLib.Variant("s", "ltr"),
            "Status": GLib.Variant("s", "normal"),
            "IconThemePath": GLib.Variant("as", []),
        }
        return values[prop]

    def _entry_map(self):
        def item(label: str, enabled: bool = True) -> dict[str, tuple[str, object]]:
            return {"label": ("s", label), "enabled": ("b", enabled), "visible": ("b", True)}

        return {
            0: {"children-display": ("s", "submenu"), "visible": ("b", True)},
            1: item(self._menu_labels["open"]),
            2: item(self._menu_labels["refresh"]),
            3: {"type": ("s", "separator"), "visible": ("b", True)},
            4: item(self._menu_labels["quit"]),
        }

    def _layout(self):
        from gi.repository import GLib

        entries = self._entry_map()

        def build(item_id: int, children: tuple[int, ...] = ()):
            props = {k: GLib.Variant(*v) for k, v in entries[item_id].items()}
            kids = [GLib.Variant("(ia{sv}av)", build(child)) for child in children]
            return (item_id, props, kids)

        return build(0, (1, 2, 3, 4))

    def _menu_method(self, _conn, _sender, _path, _iface, method, params, invocation):
        from gi.repository import GLib

        if method == "GetLayout":
            invocation.return_value(GLib.Variant("(u(ia{sv}av))", (self._revision, self._layout())))
        elif method == "GetGroupProperties":
            ids, _names = params.unpack()
            entries = self._entry_map()
            result = [
                (entry_id, {k: GLib.Variant(*v) for k, v in props.items()})
                for entry_id, props in entries.items()
                if not ids or entry_id in ids
            ]
            invocation.return_value(GLib.Variant("(a(ia{sv}))", (result,)))
        elif method == "GetProperty":
            entry_id, name = params.unpack()
            props = self._entry_map().get(entry_id, {})
            signature, value = props.get(name, ("s", ""))
            invocation.return_value(GLib.Variant("(v)", (GLib.Variant(signature, value),)))
        elif method == "Event":
            entry_id, event_id, _data, _timestamp = params.unpack()
            if event_id == "clicked":
                if entry_id == 1:
                    self.open_window()
                elif entry_id == 2:
                    self.refresh(force=True)
                elif entry_id == 4:
                    self._loop.quit()
            invocation.return_value(None)
        elif method == "EventGroup":
            invocation.return_value(GLib.Variant("(ai)", ([],)))
        elif method == "AboutToShow":
            invocation.return_value(GLib.Variant("(b)", (False,)))
        elif method == "AboutToShowGroup":
            invocation.return_value(GLib.Variant("(aiai)", ([], [])))
        else:
            invocation.return_value(None)

    def open_window(self) -> None:
        subprocess.Popen(
            [sys.executable, "-m", "ocgm", "gui", "--no-tray"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    def refresh(self, force: bool = False) -> None:
        if self._refreshing:
            return
        self._refreshing = True

        def work() -> None:
            try:
                self.monitor.refresh(force=force)
            except Exception as error:  # noqa: BLE001 - never leave the tray stuck
                self.monitor.last_error = f"Error inesperado: {error}"
            finally:
                self.GLib.idle_add(self._update)

        threading.Thread(target=work, daemon=True).start()

    def _update(self) -> bool:
        self._refreshing = False
        state = self.monitor.summary()
        usage = state.usage
        if usage is None:
            self._title = "OpenCode Go"
            self._subtitle = self.monitor.last_error or "Sin datos"
            self._icon = ICONS["warn"]
        else:
            worst = usage.worst_percent
            self._icon = ICONS[severity_for(worst, self.cfg.thresholds)]
            self._subtitle = " · ".join(
                f"{LABELS[kind]} {window.percent:.0f}%" for kind, window in usage.by_window().items()
            )
            if self.monitor.is_stale():
                self._subtitle += " (desactualizado)"
        self._sni_values["IconName"] = ("s", self._icon)
        self._sni_values["ToolTip"] = (
            "(sa(iiay)ss)",
            (self._icon, [], self._title, self._subtitle),
        )
        for signal_name in ("NewIcon", "NewToolTip"):
            self.conn.emit_signal(None, "/StatusNotifierItem", "org.kde.StatusNotifierItem", signal_name, None)
        return False

    def run(self) -> int:
        self.refresh()
        self._schedule()
        try:
            self._loop.run()
        finally:
            self.monitor.close()
        return 0

    def _schedule(self) -> None:
        if self._timer_id:
            self.GLib.source_remove(self._timer_id)
        self._timer_id = self.GLib.timeout_add_seconds(self.cfg.poll_seconds, self._tick)

    def _tick(self) -> bool:
        from .core.notify import Notifier

        cfg = load()
        if cfg != self.cfg:
            self.cfg = cfg
            self.monitor.cfg = cfg
            self.monitor.notifier = Notifier(self.monitor.store, cfg.thresholds)
            self._timer_id = self.GLib.timeout_add_seconds(cfg.poll_seconds, self._tick)
            self.refresh()
            return False
        self.refresh()
        return True


def run_tray() -> int:
    try:
        tray = Tray()
    except RuntimeError:
        return 0
    except Exception as error:  # noqa: BLE001 - headless/no D-Bus must not crash
        print(f"No se pudo iniciar la bandeja: {error}", file=sys.stderr)
        return 1
    return tray.run()
