from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from ocgm.core.models import RequestItem, Usage, WindowUsage
from ocgm.core.store import Store

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)


def item(rid: str, cost: float, model: str = "deepseek-v4.1-flash", started: datetime | None = None) -> RequestItem:
    return RequestItem(
        id=rid,
        started_at=started or NOW,
        model=model,
        provider="opencode",
        app="cli",
        session_id="ses_1",
        outcome="succeeded",
        status_code=200,
        input_tokens=100,
        output_tokens=50,
        reasoning_tokens=10,
        cache_read_tokens=1000,
        cache_write_tokens=0,
        cost_usd=cost,
        duration_ms=1200,
        ttft_ms=300,
    )


def usage(percent: float = 16.0) -> Usage:
    reset = NOW + timedelta(hours=4)
    return Usage(
        rolling=WindowUsage("ok", percent, reset),
        weekly=WindowUsage("ok", 6.0, NOW + timedelta(days=5)),
        monthly=WindowUsage("ok", 3.0, NOW + timedelta(days=28)),
        fetched_at=NOW,
    )


def test_records_and_reads_last_usage(tmp_path: Path) -> None:
    store = Store(tmp_path / "m.db")
    store.init()
    store.record_usage(usage(42.0))
    last = store.last_usage()
    assert last is not None
    assert last.rolling.percent == 42.0
    assert last.rolling.resets_at == NOW + timedelta(hours=4)
    assert last.fetched_at == NOW
    store.close()


def test_upsert_is_idempotent_and_returns_new_count(tmp_path: Path) -> None:
    store = Store(tmp_path / "m.db")
    store.init()
    assert store.upsert_requests([item("a", 0.1), item("b", 0.2)]) == 2
    assert store.upsert_requests([item("b", 0.2), item("c", 0.3)]) == 1
    assert len(store.requests()) == 3
    store.close()


def test_requests_filter_and_order(tmp_path: Path) -> None:
    store = Store(tmp_path / "m.db")
    store.init()
    older = NOW - timedelta(hours=2)
    store.upsert_requests(
        [
            item("old", 0.1, model="glm", started=older),
            item("new", 0.2, model="kimi", started=NOW),
        ]
    )
    assert [r.id for r in store.requests()] == ["new", "old"]
    assert [r.id for r in store.requests(model="glm")] == ["old"]
    store.close()


def test_cost_and_model_aggregates(tmp_path: Path) -> None:
    store = Store(tmp_path / "m.db")
    store.init()
    store.upsert_requests([item("a", 0.10), item("b", 0.20), item("c", 0.50, model="kimi")])
    assert store.cost_since(NOW - timedelta(days=1)) == pytest.approx(0.80)
    aggs = {a.model: a for a in store.aggregate_models(NOW - timedelta(days=1))}
    assert aggs["deepseek-v4.1-flash"].requests == 2
    assert aggs["deepseek-v4.1-flash"].cost_usd == pytest.approx(0.30)
    assert aggs["kimi"].requests == 1
    store.close()


def test_daily_cost_includes_empty_days_and_older_requests(tmp_path: Path) -> None:
    store = Store(tmp_path / "m.db")
    store.init()
    store.upsert_requests(
        [
            item("a", 0.5, started=NOW),
            item("old", 0.25, started=NOW - timedelta(days=3)),
        ]
    )
    days = store.daily_cost(days=5, now=NOW)
    assert len(days) == 5
    assert days[-1] == (NOW.date(), 0.5)
    assert days[1] == ((NOW - timedelta(days=3)).date(), 0.25)
    assert days[0][1] == 0.0
    store.close()


def test_daily_cost_uses_local_day(tmp_path: Path) -> None:
    store = Store(tmp_path / "m.db")
    store.init()
    tz = timezone(timedelta(hours=-5))
    now = datetime(2026, 10, 25, 4, 30, tzinfo=tz)  # 09:30 UTC
    store.upsert_requests(
        [
            item("late", 0.10, started=datetime(2026, 10, 25, 4, 0, tzinfo=timezone.utc)),
            item("early", 0.20, started=datetime(2026, 10, 25, 6, 0, tzinfo=timezone.utc)),
        ]
    )
    days = dict(store.daily_cost(days=2, now=now))
    assert days[date(2026, 10, 24)] == pytest.approx(0.10)
    assert days[date(2026, 10, 25)] == pytest.approx(0.20)
    store.close()


def test_meta_roundtrip(tmp_path: Path) -> None:
    store = Store(tmp_path / "m.db")
    store.init()
    store.meta_set("cursor", "abc")
    assert store.meta_get("cursor") == "abc"
    assert store.meta_get("missing") is None
    store.close()


def test_alert_cooldown(tmp_path: Path) -> None:
    store = Store(tmp_path / "m.db")
    store.init()
    assert store.record_alert("rolling", "threshold", 70.0, NOW) is True
    assert store.record_alert("rolling", "threshold", 72.0, NOW + timedelta(minutes=5)) is False
    assert store.record_alert("weekly", "threshold", 70.0, NOW + timedelta(minutes=5)) is True
    assert store.record_alert("rolling", "threshold", 70.0, NOW + timedelta(minutes=31)) is True
    store.close()


def test_store_can_be_used_without_explicit_init(tmp_path: Path) -> None:
    store = Store(tmp_path / "lazy.db")
    assert store.last_usage() is None
    store.close()
