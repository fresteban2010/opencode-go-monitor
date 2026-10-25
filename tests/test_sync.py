from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from ocgm.core.client import ApiError
from ocgm.core.models import LogPage, RequestItem, Usage, WindowUsage
from ocgm.core.store import Store
from ocgm.core.sync import synchronize

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)


def item(rid: str) -> RequestItem:
    return RequestItem(
        id=rid,
        started_at=NOW,
        model="m",
        provider="opencode",
        app="cli",
        session_id="s",
        outcome="succeeded",
        status_code=200,
        input_tokens=1,
        output_tokens=1,
        reasoning_tokens=0,
        cache_read_tokens=0,
        cache_write_tokens=0,
        cost_usd=0.01,
        duration_ms=1,
        ttft_ms=1,
    )


def usage(percent: float = 10.0) -> Usage:
    return Usage(
        rolling=WindowUsage("ok", percent, NOW + timedelta(hours=4)),
        weekly=WindowUsage("ok", 5.0, NOW + timedelta(days=5)),
        monthly=WindowUsage("ok", 2.0, NOW + timedelta(days=20)),
        fetched_at=NOW,
    )


class FakeClient:
    def __init__(self, pages: list[LogPage], usage_result: Usage | Exception | None = None,
                 logs_error: Exception | None = None) -> None:
        self.pages = pages
        self.usage_result = usage_result if usage_result is not None else usage()
        self.logs_error = logs_error
        self.usage_calls = 0
        self.log_calls = 0

    def usage(self) -> Usage:
        self.usage_calls += 1
        if isinstance(self.usage_result, Exception):
            raise self.usage_result
        return self.usage_result

    def request_logs(self, cursor=None, limit: int = 100) -> LogPage:
        self.log_calls += 1
        if self.logs_error:
            raise self.logs_error
        index = self.log_calls - 1
        if index >= len(self.pages):
            return LogPage([], None, 30)
        return self.pages[index]


def make_store(tmp_path: Path) -> Store:
    store = Store(tmp_path / "m.db")
    store.init()
    return store


def test_first_sync_records_usage_and_all_pages(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    client = FakeClient(
        [
            LogPage([item("a"), item("b")], '{"after":{"id":"b"}}', 30),
            LogPage([item("c")], None, 30),
        ]
    )
    result = synchronize(store, client)  # type: ignore[arg-type]
    assert result.new_requests == 3
    assert result.pages == 2
    assert result.errors == []
    assert result.stale is False
    assert len(store.requests()) == 3
    assert store.last_usage() is not None
    store.close()


def test_incremental_stops_at_fully_cached_page(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.upsert_requests([item("a"), item("b")])
    client = FakeClient(
        [
            LogPage([item("a"), item("b")], '{"after":{"id":"b"}}', 30),
            LogPage([item("c")], None, 30),
        ]
    )
    result = synchronize(store, client)  # type: ignore[arg-type]
    assert result.new_requests == 0
    assert result.pages == 1
    assert client.log_calls == 1
    assert len(store.requests()) == 2
    store.close()


def test_usage_failure_keeps_last_usage_and_still_syncs_logs(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.record_usage(usage(33.0))
    client = FakeClient(
        [LogPage([item("a")], None, 30)],
        usage_result=ApiError("boom", 500, True),
    )
    result = synchronize(store, client)  # type: ignore[arg-type]
    assert result.new_requests == 1
    assert result.stale is True
    assert result.errors
    assert result.new_requests == 1
    assert store.last_usage().rolling.percent == 33.0  # type: ignore[union-attr]
    store.close()


def test_logs_failure_keeps_usage_and_does_not_crash(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    client = FakeClient([], logs_error=ApiError("boom", 429, True))
    result = synchronize(store, client)  # type: ignore[arg-type]
    assert result.errors
    assert result.new_requests == 0
    assert store.last_usage() is not None
    store.close()


def test_full_sync_walks_past_cached_page(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.upsert_requests([item("a"), item("b")])
    client = FakeClient(
        [
            LogPage([item("a"), item("b")], '{"after":{"id":"b"}}', 30),
            LogPage([item("c")], None, 30),
        ]
    )
    result = synchronize(store, client, full=True)  # type: ignore[arg-type]
    assert result.pages == 2
    assert result.new_requests == 1
    assert len(store.requests()) == 3
    store.close()


def test_max_pages_bounds_the_walk(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    pages = [LogPage([item(f"p{n}")], f'{{"after":{{"id":"p{n}"}}}}', 30) for n in range(10)]
    result = synchronize(store, FakeClient(pages), full=True, max_pages=2)  # type: ignore[arg-type]
    assert result.pages == 2
    store.close()
