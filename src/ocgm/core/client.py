from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .models import LogPage, RequestItem, Usage, WindowUsage

DEFAULT_BASE_URL = "https://opencode.ai"
USER_AGENT = "ocgm/1.0"


class ApiError(Exception):
    def __init__(
        self,
        message: str,
        status: int = 0,
        retryable: bool = False,
        retry_after: float | None = None,
    ) -> None:
        self.status = status
        self.retryable = retryable
        self.retry_after = retry_after
        super().__init__(message)


def _parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_ms(value: Any) -> datetime:
    if not isinstance(value, (int, float)):
        return datetime.fromtimestamp(0, tz=timezone.utc)
    return datetime.fromtimestamp(value / 1000.0, tz=timezone.utc)


def encode_cursor(cursor: dict[str, Any] | str) -> str:
    payload = cursor if isinstance(cursor, str) else json.dumps(cursor, separators=(",", ":"))
    return quote(payload, safe="")


def _int(value: Any) -> int:
    return int(value) if isinstance(value, (int, float)) else 0


def _float(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


class OpenCodeClient:
    def __init__(self, token: str, base_url: str = DEFAULT_BASE_URL, timeout: float = 15.0) -> None:
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def _get(self, path_and_query: str) -> dict[str, Any]:
        request = Request(
            f"{self._base_url}{path_and_query}",
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
        )
        try:
            with urlopen(request, timeout=self._timeout) as response:
                raw = response.read()
        except HTTPError as error:
            retryable = error.code == 429 or error.code >= 500
            retry_after: float | None = None
            header = error.headers.get("Retry-After") if error.headers else None
            if header:
                try:
                    retry_after = float(header)
                except ValueError:
                    retry_after = None
            if error.code in (401, 403):
                message = (
                    f"Credencial rechazada (HTTP {error.code}). "
                    "Abre OpenCode para renovarla o revisa la API key."
                )
            else:
                message = f"HTTP {error.code} en {path_and_query.split('?')[0]}"
            raise ApiError(message, error.code, retryable, retry_after) from None
        except (URLError, TimeoutError, OSError) as error:
            raise ApiError(f"Sin conexión con opencode.ai: {error}", 0, True) from None

        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ApiError("Respuesta no válida del servidor (se esperaba JSON)", 200, False) from None
        if not isinstance(data, dict):
            raise ApiError("Respuesta no válida del servidor (objeto esperado)", 200, False)
        return data

    def usage(self) -> Usage:
        data = self._get("/zen/go/v1/usage")
        usage = data.get("usage")
        if not isinstance(usage, dict):
            raise ApiError("Respuesta de cuota sin campo 'usage'", 200, False)
        windows: dict[str, WindowUsage] = {}
        for key in ("rolling", "weekly", "monthly"):
            raw = usage.get(key)
            if not isinstance(raw, dict) or "resetsAt" not in raw:
                raise ApiError(f"Respuesta de cuota incompleta: falta '{key}'", 200, False)
            try:
                windows[key] = WindowUsage(
                    status=str(raw.get("status", "unknown")),
                    percent=float(raw.get("percent", 0)),
                    resets_at=_parse_iso(str(raw["resetsAt"])),
                )
            except (TypeError, ValueError):
                raise ApiError(f"Respuesta de cuota inválida en '{key}'", 200, False) from None
        return Usage(
            rolling=windows["rolling"],
            weekly=windows["weekly"],
            monthly=windows["monthly"],
            fetched_at=datetime.now(timezone.utc),
        )

    def request_logs(self, cursor: dict[str, Any] | str | None = None, limit: int = 100) -> LogPage:
        query = urlencode({"category": "inference", "limit": max(1, min(200, limit))})
        if cursor:
            query += "&cursor=" + encode_cursor(cursor)
        data = self._get(f"/console/api/request-logs?{query}")

        raw_items = data.get("items")
        if not isinstance(raw_items, list):
            raise ApiError("Respuesta de peticiones sin lista 'items'", 200, False)
        items = [item for raw in raw_items if (item := self._parse_item(raw)) is not None]
        next_cursor = data.get("nextCursor")
        if isinstance(next_cursor, dict):
            next_cursor = json.dumps(next_cursor, separators=(",", ":"))
        return LogPage(
            items=items,
            next_cursor=next_cursor if isinstance(next_cursor, str) and next_cursor else None,
            retention_days=_int(data.get("retentionDays")) or 30,
        )

    @staticmethod
    def _parse_item(raw: Any) -> RequestItem | None:
        if not isinstance(raw, dict) or not raw.get("id"):
            return None
        ttft = raw.get("timeToFirstTokenMs")
        return RequestItem(
            id=str(raw["id"]),
            started_at=_parse_ms(raw.get("startedAt")),
            model=str(raw.get("model") or raw.get("requestedModel") or "desconocido"),
            provider=str(raw.get("provider") or ""),
            app=str(raw.get("app") or ""),
            session_id=str(raw.get("sessionID") or ""),
            outcome=str(raw.get("outcome") or ""),
            status_code=_int(raw.get("statusCode")),
            input_tokens=_int(raw.get("inputTokens")),
            output_tokens=_int(raw.get("outputTokens")),
            reasoning_tokens=_int(raw.get("reasoningTokens")),
            cache_read_tokens=_int(raw.get("cacheReadTokens")),
            cache_write_tokens=_int(raw.get("cacheWriteTokens")),
            cost_usd=_float(raw.get("cost")),
            duration_ms=_int(raw.get("durationMs")),
            ttft_ms=int(ttft) if isinstance(ttft, (int, float)) else None,
        )
