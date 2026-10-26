from __future__ import annotations

from datetime import datetime, timedelta


def money(value: float) -> str:
    return f"${value:,.2f}"


def money_small(value: float) -> str:
    """Coste de una petición: conserva fracciones de céntimo."""
    if value <= 0:
        return "$0.00"
    if value < 0.01:
        return f"${value:.5f}"
    return f"${value:,.2f}"


def tokens(value: int) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}k"
    return str(value)


def human_delta(delta: timedelta) -> str:
    seconds = int(delta.total_seconds())
    if seconds <= 0:
        return "pendiente"
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        return f"{days} d {hours} h"
    if hours:
        return f"{hours} h {minutes:02d} min"
    return f"{minutes} min"


def clock(value: datetime | None) -> str:
    return value.astimezone().strftime("%H:%M") if value else "—"


def eta_label(value: datetime, now: datetime | None = None) -> str:
    local = value.astimezone()
    current = (now or datetime.now().astimezone()).astimezone()
    if local.date() == current.date():
        return local.strftime("%H:%M")
    return f"{date_short(local)} {local.strftime('%H:%M')}"


def date_short(value: datetime | date) -> str:
    months = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
    local = value.astimezone() if isinstance(value, datetime) else value
    return f"{local.day} {months[local.month - 1]}"


def percent(value: float) -> str:
    return f"{value:.0f}%"
