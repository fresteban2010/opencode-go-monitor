from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .models import ModelAgg, Usage, WindowUsage
from .store import Store

WINDOW_DURATIONS = {
    "rolling": timedelta(hours=5),
    "weekly": timedelta(days=7),
    "monthly": timedelta(days=30),
}


@dataclass(frozen=True)
class Burn:
    rate_pct_per_hour: float
    projected_percent: float
    eta: datetime | None
    resets_in: timedelta


@dataclass(frozen=True)
class Summary:
    usage: Usage | None
    spend_today: float
    spend_7d: float
    spend_30d: float
    burns: dict[str, Burn]
    top_models: list[ModelAgg]


def burn(window: WindowUsage, kind: str, now: datetime) -> Burn:
    duration = WINDOW_DURATIONS[kind]
    resets_in = window.resets_at - now
    if resets_in <= timedelta(0):
        return Burn(0.0, window.percent, None, resets_in)
    if window.percent >= 100.0:
        return Burn(0.0, 100.0, now, resets_in)

    start = window.resets_at - duration
    elapsed = (now - start).total_seconds()
    total = duration.total_seconds()
    if elapsed <= 0:
        return Burn(0.0, window.percent, None, resets_in)

    rate_per_second = window.percent / elapsed
    remaining = max(0.0, total - elapsed)
    projected = window.percent + rate_per_second * remaining

    eta: datetime | None = None
    if rate_per_second > 0:
        seconds_to_full = (100.0 - window.percent) / rate_per_second
        candidate = now + timedelta(seconds=seconds_to_full)
        if candidate <= window.resets_at:
            eta = candidate

    return Burn(
        rate_pct_per_hour=rate_per_second * 3600.0,
        projected_percent=projected,
        eta=eta,
        resets_in=resets_in,
    )


def summary(store: Store, now: datetime | None = None) -> Summary:
    now = now or datetime.now(timezone.utc)
    local = now.astimezone()
    day_start = local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    usage = store.last_usage()
    burns: dict[str, Burn] = {}
    if usage is not None:
        burns = {kind: burn(window, kind, now) for kind, window in usage.by_window().items()}
    return Summary(
        usage=usage,
        spend_today=store.cost_since(day_start),
        spend_7d=store.cost_since(now - timedelta(days=7)),
        spend_30d=store.cost_since(now - timedelta(days=30)),
        burns=burns,
        top_models=store.aggregate_models(now - timedelta(days=30)),
    )
