from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class WindowUsage:
    status: str
    percent: float
    resets_at: datetime

    @property
    def is_limited(self) -> bool:
        known = {"rate-limited", "limited", "exceeded", "quota_exceeded", "quota-exceeded"}
        return self.status.strip().lower() in known or self.percent >= 100.0


@dataclass(frozen=True)
class Usage:
    rolling: WindowUsage
    weekly: WindowUsage
    monthly: WindowUsage
    fetched_at: datetime

    def by_window(self) -> dict[str, WindowUsage]:
        return {"rolling": self.rolling, "weekly": self.weekly, "monthly": self.monthly}

    @property
    def worst_percent(self) -> float:
        return max(w.percent for w in self.by_window().values())


@dataclass(frozen=True)
class RequestItem:
    id: str
    started_at: datetime
    model: str
    provider: str
    app: str
    session_id: str
    outcome: str
    status_code: int
    input_tokens: int
    output_tokens: int
    reasoning_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: float
    duration_ms: int
    ttft_ms: int | None


@dataclass(frozen=True)
class LogPage:
    items: list[RequestItem]
    next_cursor: str | None
    retention_days: int


@dataclass(frozen=True)
class ModelAgg:
    model: str
    requests: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cost_usd: float
