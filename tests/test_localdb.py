from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ocgm.core.localdb import compare, session_totals

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)


def make_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        "create table session (id text primary key, cost real, tokens_input integer,"
        " tokens_output integer, tokens_cache_read integer, time_created integer)"
    )
    recent = int((NOW - timedelta(days=1)).timestamp() * 1000)
    old = int((NOW - timedelta(days=40)).timestamp() * 1000)
    conn.executemany(
        "insert into session values (?,?,?,?,?,?)",
        [
            ("s1", 0.10, 100, 50, 200, recent),
            ("s2", 0.20, 300, 60, 400, recent),
            ("s3", 0.99, 1, 1, 1, old),
        ],
    )
    conn.commit()
    conn.close()


def test_session_totals_since(tmp_path: Path) -> None:
    db = tmp_path / "opencode.db"
    make_db(db)
    totals = session_totals(db, NOW - timedelta(days=30))
    assert totals.sessions == 2
    assert totals.cost_usd == pytest.approx(0.30)
    assert totals.input_tokens == 400
    assert totals.cache_read_tokens == 600


def test_missing_db_returns_zero(tmp_path: Path) -> None:
    totals = session_totals(tmp_path / "absent.db", NOW)
    assert totals.sessions == 0
    assert totals.cost_usd == 0.0


def test_compare_reports_delta(tmp_path: Path) -> None:
    db = tmp_path / "opencode.db"
    make_db(db)
    rec = compare(server_cost=0.36, path=db, since=NOW - timedelta(days=30))
    assert rec.server_cost == 0.36
    assert rec.local_cost == pytest.approx(0.30)
    assert rec.delta_pct == pytest.approx(20.0)


def test_compare_without_local_data_is_safe(tmp_path: Path) -> None:
    rec = compare(server_cost=0.36, path=tmp_path / "absent.db", since=NOW)
    assert rec.delta_pct == 0.0
