from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ocgm.core.analysis import burn, summary
from ocgm.core.models import RequestItem, Usage, WindowUsage
from ocgm.core.store import Store

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)


def test_burn_linear_projection() -> None:
    resets = NOW + timedelta(hours=4)  # 1 h elapsed of a 5 h window
    window = WindowUsage("ok", 20.0, resets)
    result = burn(window, "rolling", now=NOW)
    assert result.rate_pct_per_hour == pytest.approx(20.0)
    assert result.projected_percent == pytest.approx(100.0)
    assert result.eta == resets
    assert result.resets_in == timedelta(hours=4)


def test_burn_predicts_early_exhaustion() -> None:
    resets = NOW + timedelta(hours=4)
    window = WindowUsage("ok", 50.0, resets)
    result = burn(window, "rolling", now=NOW)
    assert result.projected_percent == pytest.approx(250.0)
    assert result.eta == NOW + timedelta(hours=1)


def test_burn_at_window_start_has_no_rate() -> None:
    resets = NOW + timedelta(hours=5)
    result = burn(WindowUsage("ok", 0.0, resets), "rolling", now=NOW)
    assert result.rate_pct_per_hour == 0.0
    assert result.projected_percent == 0.0
    assert result.eta is None


def test_burn_after_reset_is_marked_stale() -> None:
    result = burn(WindowUsage("ok", 80.0, NOW - timedelta(minutes=5)), "weekly", now=NOW)
    assert result.resets_in < timedelta(0)
    assert result.eta is None
    assert result.projected_percent == 80.0


def test_burn_already_limited() -> None:
    result = burn(WindowUsage("rate-limited", 100.0, NOW + timedelta(hours=1)), "monthly", now=NOW)
    assert result.eta == NOW


def test_summary_aggregates_spend_and_models(tmp_path) -> None:
    store = Store(tmp_path / "m.db")
    store.init()
    reset = NOW + timedelta(hours=4)
    store.record_usage(
        Usage(
            WindowUsage("ok", 10.0, reset),
            WindowUsage("ok", 5.0, NOW + timedelta(days=5)),
            WindowUsage("ok", 2.0, NOW + timedelta(days=20)),
            NOW,
        )
    )
    store.upsert_requests(
        [
            RequestItem(
                "a", NOW, "model-a", "opencode", "cli", "s", "succeeded", 200,
                100, 50, 0, 200, 0, 0.10, 1000, 100,
            ),
            RequestItem(
                "b", NOW - timedelta(days=2), "model-b", "opencode", "cli", "s",
                "succeeded", 200, 200, 60, 0, 0, 0, 0.25, 1000, 100,
            ),
        ]
    )
    result = summary(store, now=NOW)
    assert result.usage is not None
    assert result.spend_30d == pytest.approx(0.35)
    assert result.spend_7d == pytest.approx(0.35)
    assert result.spend_today == pytest.approx(0.10)
    assert [m.model for m in result.top_models] == ["model-b", "model-a"]
    assert set(result.burns) == {"rolling", "weekly", "monthly"}
    store.close()


def test_summary_today_uses_local_midnight(tmp_path) -> None:
    tz = timezone(timedelta(hours=-5))
    now = datetime(2026, 10, 25, 4, 30, tzinfo=tz)  # 09:30 UTC
    store = Store(tmp_path / "m.db")
    store.init()
    store.upsert_requests(
        [
            RequestItem(
                "late", datetime(2026, 10, 25, 4, 0, tzinfo=timezone.utc), "m", "p", "cli",
                "s", "succeeded", 200, 1, 1, 0, 0, 0, 0.30, 1, 1,
            ),
            RequestItem(
                "early", datetime(2026, 10, 25, 6, 0, tzinfo=timezone.utc), "m", "p", "cli",
                "s", "succeeded", 200, 1, 1, 0, 0, 0, 0.20, 1, 1,
            ),
        ]
    )
    result = summary(store, now=now)
    assert result.spend_today == pytest.approx(0.20)
    assert result.spend_7d == pytest.approx(0.50)
    store.close()
