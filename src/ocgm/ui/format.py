from __future__ import annotations

from datetime import datetime, timedelta


def money(value: float) -> str:
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


def date_short(value: datetime) -> str:
    months = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
    local = value.astimezone()
    return f"{local.day} {months[local.month - 1]}"


def percent(value: float) -> str:
    return f"{value:.0f}%"
