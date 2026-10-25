from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Iterator
from urllib.parse import parse_qs, urlparse

import pytest

from ocgm.core.client import ApiError, OpenCodeClient, encode_cursor

USAGE_BODY = {
    "usage": {
        "rolling": {"status": "ok", "percent": 16, "resetsAt": "2026-10-25T23:16:06.000Z"},
        "weekly": {"status": "ok", "percent": 6, "resetsAt": "2026-10-26T00:00:00.000Z"},
        "monthly": {"status": "rate-limited", "percent": 100, "resetsAt": "2026-11-25T18:11:28.000Z"},
    }
}

LOG_BODY = {
    "items": [
        {
            "id": "req_1",
            "startedAt": 1792959049440,
            "model": "deepseek-v4.1-flash",
            "provider": "opencode",
            "app": "cli",
            "sessionID": "ses_1",
            "outcome": "succeeded",
            "statusCode": 200,
            "inputTokens": 3855,
            "outputTokens": 560,
            "reasoningTokens": 351,
            "cacheReadTokens": 51200,
            "cacheWriteTokens": 0,
            "cost": 0.00106785,
            "durationMs": 4280,
            "timeToFirstTokenMs": 1076,
        }
    ],
    "nextCursor": '{"after":{"startedAt":1792959049440,"id":"req_1"}}',
    "retentionDays": 30,
}


class Handler(BaseHTTPRequestHandler):
    routes: dict[str, tuple[int, object]] = {}
    seen: list[str] = []
    headers_seen: list[dict[str, str]] = []

    def do_GET(self) -> None:  # noqa: N802
        Handler.seen.append(self.path)
        Handler.headers_seen.append({k.lower(): v for k, v in self.headers.items()})
        path = urlparse(self.path).path
        status, body = Handler.routes.get(path, (404, {"error": "not found"}))
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        if status == 429:
            self.send_header("Retry-After", "120")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args: object) -> None:
        return


@contextmanager
def serve(routes: dict[str, tuple[int, object]]) -> Iterator[str]:
    Handler.routes = routes
    Handler.seen = []
    Handler.headers_seen = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


def test_usage_parses_windows() -> None:
    with serve({"/zen/go/v1/usage": (200, USAGE_BODY)}) as base:
        usage = OpenCodeClient("tok", base_url=base).usage()
    assert usage.rolling.percent == 16
    assert usage.weekly.percent == 6
    assert usage.monthly.is_limited is True
    assert usage.rolling.resets_at == datetime(2026, 10, 25, 23, 16, 6, tzinfo=timezone.utc)
    assert usage.fetched_at.tzinfo is not None


def test_sends_bearer_token_and_user_agent() -> None:
    with serve({"/zen/go/v1/usage": (200, USAGE_BODY)}) as base:
        OpenCodeClient("secret-token", base_url=base).usage()
    assert Handler.headers_seen[0]["authorization"] == "Bearer secret-token"
    assert Handler.headers_seen[0]["user-agent"] == "ocgm/1.0"


def test_usage_401_is_not_retryable() -> None:
    with serve({"/zen/go/v1/usage": (401, {"error": "unauthorized"})}) as base:
        with pytest.raises(ApiError) as err:
            OpenCodeClient("bad", base_url=base).usage()
    assert err.value.status == 401
    assert err.value.retryable is False


def test_usage_429_is_retryable() -> None:
    with serve({"/zen/go/v1/usage": (429, {"error": "slow down"})}) as base:
        with pytest.raises(ApiError) as err:
            OpenCodeClient("tok", base_url=base).usage()
    assert err.value.status == 429
    assert err.value.retryable is True
    assert err.value.retry_after == 120.0


def test_next_cursor_object_is_serialized() -> None:
    body = dict(LOG_BODY)
    body["nextCursor"] = {"after": {"startedAt": 1, "id": "req_1"}}
    with serve({"/console/api/request-logs": (200, body)}) as base:
        page = OpenCodeClient("tok", base_url=base).request_logs()
    assert isinstance(page.next_cursor, str)
    assert json.loads(page.next_cursor) == {"after": {"startedAt": 1, "id": "req_1"}}


def test_invalid_json_raises_api_error() -> None:
    class BadHandler(Handler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"<html>nope</html>")

    server = ThreadingHTTPServer(("127.0.0.1", 0), BadHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = OpenCodeClient("tok", base_url=f"http://127.0.0.1:{server.server_port}")
        with pytest.raises(ApiError):
            client.usage()
    finally:
        server.shutdown()
        server.server_close()


def test_request_logs_parse_and_encode_cursor() -> None:
    with serve({"/console/api/request-logs": (200, LOG_BODY)}) as base:
        page = OpenCodeClient("tok", base_url=base).request_logs(
            cursor={"after": {"startedAt": 1792959049440, "id": "req_1"}}, limit=100
        )
    item = page.items[0]
    assert item.id == "req_1"
    assert item.model == "deepseek-v4.1-flash"
    assert item.cache_read_tokens == 51200
    assert item.cost_usd == pytest.approx(0.00106785)
    assert item.ttft_ms == 1076
    assert page.retention_days == 30
    assert page.next_cursor is not None
    query = parse_qs(urlparse(Handler.seen[0]).query)
    assert query["category"] == ["inference"]
    assert query["limit"] == ["100"]
    assert json.loads(query["cursor"][0]) == {"after": {"startedAt": 1792959049440, "id": "req_1"}}


def test_encode_cursor_roundtrips_special_characters() -> None:
    cursor = {"after": {"id": "a b&c=d/é"}, "kind": "list"}
    parsed = json.loads(parse_qs(f"cursor={encode_cursor(cursor)}")["cursor"][0])
    assert parsed == cursor


def test_request_logs_tolerates_missing_optional_fields() -> None:
    body = {
        "items": [{"id": "req_2", "startedAt": 0, "model": "m", "cost": 0}],
        "nextCursor": None,
        "retentionDays": 30,
    }
    with serve({"/console/api/request-logs": (200, body)}) as base:
        page = OpenCodeClient("tok", base_url=base).request_logs()
    item = page.items[0]
    assert item.input_tokens == 0
    assert item.ttft_ms is None
    assert item.app == ""
    assert page.next_cursor is None
