from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

DEFAULT_OPENCODE_DB = Path.home() / ".local" / "share" / "opencode" / "opencode.db"


@dataclass(frozen=True)
class LocalTotals:
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    sessions: int = 0


@dataclass(frozen=True)
class Reconciliation:
    server_cost: float
    local_cost: float
    delta_pct: float


def session_totals(path: Path, since: datetime) -> LocalTotals:
    if not path.exists():
        return LocalTotals()
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=1.0)
    except sqlite3.Error:
        return LocalTotals()
    try:
        row = conn.execute(
            "select coalesce(sum(cost),0), coalesce(sum(tokens_input),0),"
            " coalesce(sum(tokens_output),0), coalesce(sum(tokens_cache_read),0), count(*)"
            " from session where time_created >= ?",
            (int(since.timestamp() * 1000),),
        ).fetchone()
    except sqlite3.Error:
        return LocalTotals()
    finally:
        conn.close()
    if row is None:
        return LocalTotals()
    return LocalTotals(
        cost_usd=float(row[0]),
        input_tokens=int(row[1]),
        output_tokens=int(row[2]),
        cache_read_tokens=int(row[3]),
        sessions=int(row[4]),
    )


def compare(server_cost: float, path: Path, since: datetime) -> Reconciliation:
    local = session_totals(path, since)
    delta = 0.0
    if local.cost_usd > 0:
        delta = (server_cost - local.cost_usd) / local.cost_usd * 100.0
    return Reconciliation(server_cost=server_cost, local_cost=local.cost_usd, delta_pct=delta)
