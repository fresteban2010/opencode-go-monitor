from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .analysis import Burn
from .models import Usage, WindowUsage
from .store import Store

LABELS = {"rolling": "5 h", "weekly": "semanal", "monthly": "mensual"}


@dataclass(frozen=True)
class Alert:
    window: str
    kind: str
    percent: float
    title: str
    body: str


class Notifier:
    def __init__(self, store: Store, thresholds: tuple[int, ...] = (70, 85, 95)) -> None:
        self._store = store
        self._thresholds = tuple(sorted(thresholds))

    def evaluate(self, usage: Usage, burns: dict[str, Burn], now: datetime) -> list[Alert]:
        alerts: list[Alert] = []
        for kind, window in usage.by_window().items():
            alert = self._evaluate_window(kind, window, burns.get(kind), now)
            if alert is not None:
                alerts.append(alert)
        return alerts

    def _evaluate_window(
        self, kind: str, window: WindowUsage, burn: Burn | None, now: datetime
    ) -> Alert | None:
        label = LABELS[kind]
        if window.is_limited:
            if self._store.record_alert(kind, "exhausted", window.percent, now):
                return Alert(
                    kind,
                    "exhausted",
                    window.percent,
                    f"Ventana {label} agotada",
                    "Has alcanzado el límite de esta ventana. Se restablece "
                    f"en {_human(window.resets_at - now)}.",
                )
            return None

        if burn is not None and burn.eta is not None and burn.eta < window.resets_at:
            if self._store.record_alert(kind, "projected", window.percent, now):
                return Alert(
                    kind,
                    "projected",
                    window.percent,
                    f"Ritmo alto en la ventana {label}",
                    f"A este paso vas a agotar la ventana antes del reset "
                    f"(sobre las {burn.eta.astimezone().strftime('%H:%M')}).",
                )
            return None

        for threshold in reversed(self._thresholds):
            if window.percent >= threshold:
                if self._store.record_alert(kind, f"threshold-{threshold}", window.percent, now):
                    return Alert(
                        kind,
                        f"threshold-{threshold}",
                        window.percent,
                        f"Cuota {label} al {window.percent:.0f}%",
                        f"Te queda un {max(0.0, 100.0 - window.percent):.0f}% de la ventana. "
                        f"Reset en {_human(window.resets_at - now)}.",
                    )
                return None
        return None


def _human(delta) -> str:
    seconds = int(delta.total_seconds())
    if seconds <= 0:
        return "menos de un minuto"
    hours, rest = divmod(seconds, 3600)
    minutes = rest // 60
    if hours >= 48:
        return f"{hours // 24} días"
    if hours:
        return f"{hours} h {minutes:02d} min"
    return f"{minutes} min"


def send(alert: Alert) -> bool:
    try:
        import gi

        gi.require_version("Notify", "0.7")
        from gi.repository import Notify

        Notify.init("OpenCode Go Monitor")
        notification = Notify.Notification.new(alert.title, alert.body, "dialog-information")
        notification.show()
        return True
    except Exception:  # noqa: BLE001 - notifications are best-effort
        return False
