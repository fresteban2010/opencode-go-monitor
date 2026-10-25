from __future__ import annotations

from dataclasses import replace

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk  # noqa: E402

from ..core.config import Config, save  # noqa: E402


class SettingsPage(Adw.PreferencesPage):
    def __init__(self, cfg: Config, on_save) -> None:
        super().__init__()
        self._on_save = on_save
        self._cfg = cfg

        general = Adw.PreferencesGroup(title="Actualización")
        self.poll = Adw.SpinRow.new_with_range(30, 3600, 30)
        self.poll.set_title("Cada cuánto consultar la cuota")
        self.poll.set_subtitle("Segundos (mínimo 30)")
        self.poll.set_value(cfg.poll_seconds)
        general.add(self.poll)

        self.sync = Adw.SpinRow.new_with_range(30, 3600, 30)
        self.sync.set_title("Cada cuánto sincronizar peticiones")
        self.sync.set_subtitle("Segundos")
        self.sync.set_value(cfg.sync_seconds)
        general.add(self.sync)
        self.add(general)

        alerts = Adw.PreferencesGroup(title="Avisos")
        self.notify = Adw.SwitchRow(title="Notificaciones de escritorio")
        self.notify.set_active(cfg.notify)
        alerts.add(self.notify)

        self.thresholds = Adw.EntryRow(title="Umbrales de aviso (%)")
        self.thresholds.set_text(", ".join(str(t) for t in cfg.thresholds))
        alerts.add(self.thresholds)
        self.add(alerts)

        credentials = Adw.PreferencesGroup(
            title="Credenciales",
            description="Si se deja vacío, se usa el token de OpenCode Console o OPENCODE_API_KEY.",
        )
        self.api_key = Adw.PasswordEntryRow(title="API key de OpenCode Go (opcional)")
        if cfg.api_key:
            self.api_key.set_text(cfg.api_key)
        credentials.add(self.api_key)
        self.add(credentials)

        actions = Adw.PreferencesGroup()
        row = Adw.ActionRow(title="Guardar cambios")
        button = Gtk.Button(label="Guardar")
        button.add_css_class("suggested-action")
        button.connect("clicked", self._save)
        row.add_suffix(button)
        actions.add(row)
        self.add(actions)

        self.status = Gtk.Label(label="")
        self.status.add_css_class("dim-label")
        self.status.set_margin_top(6)
        status_row = Adw.ActionRow()
        status_row.set_child(self.status)
        actions.add(status_row)

    def _save(self, _button) -> None:
        try:
            thresholds = tuple(
                sorted({max(1, min(100, int(part.strip()))) for part in self.thresholds.get_text().split(",") if part.strip()})
            )
        except ValueError:
            self.status.set_text("Los umbrales deben ser números separados por comas.")
            self.status.add_css_class("danger")
            return
        if not thresholds:
            self.status.set_text("Añade al menos un umbral.")
            self.status.add_css_class("danger")
            return

        cfg = replace(
            self._cfg,
            poll_seconds=int(self.poll.get_value()),
            sync_seconds=int(self.sync.get_value()),
            thresholds=thresholds,
            notify=self.notify.get_active(),
            api_key=self.api_key.get_text().strip() or None,
        )
        save(cfg)
        self.status.remove_css_class("danger")
        self.status.set_text("Guardado.")
        self._on_save(cfg)
