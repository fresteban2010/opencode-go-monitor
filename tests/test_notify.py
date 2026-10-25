from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from ocgm.core.analysis import burn
from ocgm.core.models import Usage, WindowUsage
from ocgm.core.notify import Notifier
from ocgm.core.store import Store

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)


def usage(
    rolling: float,
    weekly: float = 10.0,
    monthly: float = 5.0,
    status: str = "ok",
    resets_in: timedelta = timedelta(hours=4),
) -> Usage:
    return Usage(
        WindowUsage(status, rolling, NOW + resets_in),
        WindowUsage("ok", weekly, NOW + timedelta(days=5)),
        WindowUsage("ok", monthly, NOW + timedelta(days=20)),
        NOW,
    )


def evaluate(store: Store, u: Usage, now: datetime = NOW):
    burns = {kind: burn(window, kind, now) for kind, window in u.by_window().items()}
    return Notifier(store, thresholds=(70, 85, 95)).evaluate(u, burns, now)


def make_store(tmp_path: Path) -> Store:
    store = Store(tmp_path / "m.db")
    store.init()
    return store


def test_no_alert_below_threshold_without_projection(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    assert evaluate(store, usage(10.0)) == []
    store.close()


def test_threshold_alerts_once_within_cooldown(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    first = evaluate(store, usage(72.0, resets_in=timedelta(minutes=10)))
    assert [a.kind for a in first] == ["threshold-70"]
    assert evaluate(store, usage(72.0, resets_in=timedelta(minutes=10))) == []
    store.close()


def test_higher_threshold_alerts_when_crossed(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    evaluate(store, usage(72.0, resets_in=timedelta(minutes=10)))
    alerts = evaluate(store, usage(90.0, resets_in=timedelta(minutes=10)))
    assert [a.kind for a in alerts] == ["threshold-85"]
    store.close()


def test_exhausted_alert(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    alerts = evaluate(store, usage(100.0, status="rate-limited"))
    assert alerts and alerts[0].kind == "exhausted"
    store.close()


def test_projected_exhaustion_alert(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    alerts = evaluate(store, usage(50.0))
    assert alerts and alerts[0].kind == "projected"
    assert "agotar" in alerts[0].body.lower()
    store.close()
