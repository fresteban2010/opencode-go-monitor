from __future__ import annotations

from datetime import date, datetime

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk  # noqa: E402

from ..core.analysis import Summary  # noqa: E402
from .chart import CostChart  # noqa: E402
from .format import clock, eta_label, human_delta, money  # noqa: E402

WINDOW_LABELS = {"rolling": "5 horas", "weekly": "Semanal", "monthly": "Mensual"}


class SummaryPage(Gtk.ScrolledWindow):
    def __init__(self) -> None:
        super().__init__()
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._meters: dict[str, dict[str, Gtk.Widget]] = {}

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        box.set_margin_top(24)
        box.set_margin_bottom(24)
        box.set_margin_start(24)
        box.set_margin_end(24)
        clamp = Adw.Clamp(maximum_size=980)
        clamp.set_child(box)
        self.set_child(clamp)

        self.status = Gtk.Label(label="Cargando…")
        self.status.set_xalign(0)
        self.status.add_css_class("dim-label")
        box.append(self.status)

        meters = Gtk.Grid(column_homogeneous=True, column_spacing=14)
        for index, kind in enumerate(("rolling", "weekly", "monthly")):
            meters.attach(self._meter_card(kind), index, 0, 1, 1)
        box.append(meters)

        spend = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        spend.append(self._stat_card("hoy", "today"))
        spend.append(self._stat_card("últimos 7 días", "7d"))
        spend.append(self._stat_card("últimos 30 días", "30d"))
        box.append(spend)

        chart_title = Gtk.Label(label="Coste diario · 14 días")
        chart_title.set_xalign(0)
        chart_title.add_css_class("heading")
        box.append(chart_title)
        self.chart = CostChart()
        chart_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        chart_box.set_hexpand(True)
        chart_box.add_css_class("card")
        chart_box.append(self.chart)
        box.append(chart_box)

        self.footer = Gtk.Label(label="")
        self.footer.set_xalign(0)
        self.footer.add_css_class("dim-label")
        self.footer.set_wrap(True)
        box.append(self.footer)

    def _meter_card(self, kind: str) -> Gtk.Widget:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        card.add_css_class("card")

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        name = Gtk.Label(label=WINDOW_LABELS[kind])
        name.set_xalign(0)
        name.add_css_class("heading")
        value = Gtk.Label(label="—")
        value.add_css_class("meter-value")
        value.set_hexpand(True)
        value.set_xalign(1)
        head.append(name)
        head.append(value)

        bar = Gtk.ProgressBar()
        bar.set_fraction(0.0)

        reset = Gtk.Label(label="")
        reset.set_xalign(0)
        reset.add_css_class("dim-label")

        projection = Gtk.Label(label="")
        projection.set_xalign(0)
        projection.set_wrap(True)
        projection.add_css_class("dim-label")

        card.append(head)
        card.append(bar)
        card.append(reset)
        card.append(projection)
        self._meters[kind] = {"value": value, "bar": bar, "reset": reset, "projection": projection}
        return card

    def _stat_card(self, label: str, key: str) -> Gtk.Widget:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        card.add_css_class("card")
        card.set_hexpand(True)
        value = Gtk.Label(label="—")
        value.set_xalign(0)
        value.add_css_class("stat-value")
        caption = Gtk.Label(label=label)
        caption.set_xalign(0)
        caption.add_css_class("dim-label")
        card.append(value)
        card.append(caption)
        setattr(self, f"spend_{key}", value)
        return card

    def render(
        self,
        state: Summary,
        daily: list[tuple[date, float]],
        updated_at: datetime | None,
        stale: bool,
        error: str | None,
        source: str | None,
        logs_unavailable: bool = False,
        local_spend: dict[str, float] | None = None,
    ) -> None:
        if error:
            when = clock(updated_at) if updated_at else None
            suffix = f" · última foto de las {when}" if when else ""
            self.status.set_text(f"No se pudo actualizar: {error}{suffix}")
            self.status.remove_css_class("dim-label")
            self.status.add_css_class("danger")
        else:
            when = clock(updated_at)
            suffix = " · datos desactualizados" if stale else ""
            origin = f" · fuente {source}" if source else ""
            self.status.set_text(f"Actualizado a las {when}{origin}{suffix}")
            self.status.remove_css_class("danger")
            self.status.add_css_class("dim-label")

        usage = state.usage
        for kind, widgets in self._meters.items():
            value = widgets["value"]
            bar = widgets["bar"]
            reset = widgets["reset"]
            projection = widgets["projection"]
            for css in ("ok", "warn", "danger"):
                value.remove_css_class(css)
                projection.remove_css_class(css)
            if usage is None:
                value.set_text("—")
                bar.set_fraction(0.0)
                reset.set_text("Sin datos. Pulsa actualizar.")
                projection.set_text("")
                continue
            window = usage.by_window()[kind]
            burn = state.burns.get(kind)
            value.set_text(f"{window.percent:.0f}%")
            bar.set_fraction(max(0.0, min(1.0, window.percent / 100.0)))
            reset_text = (
                "Límite alcanzado"
                if window.is_limited
                else f"Reset en {human_delta(burn.resets_in if burn else window.resets_at - usage.fetched_at)}"
            )
            if not window.is_limited and window.status not in ("ok", "unknown", ""):
                reset_text = f"{window.status} · {reset_text}"
            reset.set_text(reset_text)
            if window.is_limited:
                value.add_css_class("danger")
                projection.set_text("Esta ventana está agotada.")
            elif burn is None:
                projection.set_text("")
            elif burn.eta is not None:
                value.add_css_class("danger")
                projection.add_css_class("danger")
                projection.set_text(f"A este ritmo se agota a las {eta_label(burn.eta)}.")
            elif burn.projected_percent > 100:
                value.add_css_class("warn")
                projection.add_css_class("warn")
                projection.set_text(f"Proyección {burn.projected_percent:.0f}% al reset.")
            else:
                value.add_css_class("ok")
                projection.set_text(f"Proyección {burn.projected_percent:.0f}% al reset.")

        self.spend_today.set_text(money(local_spend["today"] if local_spend else state.spend_today))
        self.spend_7d.set_text(money(local_spend["7d"] if local_spend else state.spend_7d))
        self.spend_30d.set_text(money(local_spend["30d"] if local_spend else state.spend_30d))
        self.chart.set_data(daily)
        models = len(state.top_models)
        if logs_unavailable:
            self.footer.set_text(
                "Detalle por petición no disponible"
                + ("; gasto estimado desde la BD local de OpenCode" if local_spend else "")
                + "."
            )
        else:
            self.footer.set_text(
                f"{models} modelos con actividad en 30 días · la cuota es agregada de la cuenta"
            )
