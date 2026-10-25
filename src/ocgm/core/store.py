from __future__ import annotations

import sqlite3
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .models import ModelAgg, RequestItem, Usage, WindowUsage

SCHEMA_VERSION = 1
ALERT_COOLDOWN = timedelta(minutes=30)


def _ms(value: datetime) -> int:
    return int(value.timestamp() * 1000)


def _dt(value: int | None) -> datetime:
    if value is None:
        return datetime.fromtimestamp(0, tz=timezone.utc)
    return datetime.fromtimestamp(value / 1000.0, tz=timezone.utc)


class Store:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None

    def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, timeout=5.0, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(
            """
            create table if not exists meta (
                key text primary key,
                value text not null
            );
            create table if not exists usage_snapshots (
                id integer primary key autoincrement,
                fetched_at integer not null,
                rolling_status text not null,
                rolling_percent real not null,
                rolling_resets_at integer not null,
                weekly_status text not null,
                weekly_percent real not null,
                weekly_resets_at integer not null,
                monthly_status text not null,
                monthly_percent real not null,
                monthly_resets_at integer not null
            );
            create table if not exists requests (
                id text primary key,
                started_at integer not null,
                model text not null,
                provider text not null,
                app text not null,
                session_id text not null,
                outcome text not null,
                status_code integer not null,
                input_tokens integer not null,
                output_tokens integer not null,
                reasoning_tokens integer not null,
                cache_read_tokens integer not null,
                cache_write_tokens integer not null,
                cost_usd real not null,
                duration_ms integer not null,
                ttft_ms integer
            );
            create index if not exists requests_started_idx on requests(started_at);
            create index if not exists requests_model_idx on requests(model);
            create table if not exists alert_log (
                id integer primary key autoincrement,
                window text not null,
                kind text not null,
                percent real not null,
                at integer not null
            );
            create index if not exists alert_window_idx on alert_log(window, kind, at);
            """
        )
        self._conn.commit()
        self.meta_set("schema_version", str(SCHEMA_VERSION))

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _db(self) -> sqlite3.Connection:
        if self._conn is None:
            self.init()
        assert self._conn is not None
        return self._conn

    def record_usage(self, usage: Usage) -> None:
        with self._lock:
            db = self._db()
            db.execute(
                "insert into usage_snapshots (fetched_at,"
                " rolling_status, rolling_percent, rolling_resets_at,"
                " weekly_status, weekly_percent, weekly_resets_at,"
                " monthly_status, monthly_percent, monthly_resets_at)"
                " values (?,?,?,?,?,?,?,?,?,?)",
                (
                    _ms(usage.fetched_at),
                    usage.rolling.status,
                    usage.rolling.percent,
                    _ms(usage.rolling.resets_at),
                    usage.weekly.status,
                    usage.weekly.percent,
                    _ms(usage.weekly.resets_at),
                    usage.monthly.status,
                    usage.monthly.percent,
                    _ms(usage.monthly.resets_at),
                ),
            )
            db.commit()

    def last_usage(self) -> Usage | None:
        with self._lock:
            row = self._db().execute(
                "select fetched_at, rolling_status, rolling_percent, rolling_resets_at,"
                " weekly_status, weekly_percent, weekly_resets_at,"
                " monthly_status, monthly_percent, monthly_resets_at"
                " from usage_snapshots order by fetched_at desc, id desc limit 1"
            ).fetchone()
        if row is None:
            return None
        return Usage(
            rolling=WindowUsage(row[1], row[2], _dt(row[3])),
            weekly=WindowUsage(row[4], row[5], _dt(row[6])),
            monthly=WindowUsage(row[7], row[8], _dt(row[9])),
            fetched_at=_dt(row[0]),
        )

    def upsert_requests(self, items: list[RequestItem]) -> int:
        if not items:
            return 0
        with self._lock:
            db = self._db()
            before = db.total_changes
            db.executemany(
                "insert or ignore into requests values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        i.id,
                        _ms(i.started_at),
                        i.model,
                        i.provider,
                        i.app,
                        i.session_id,
                        i.outcome,
                        i.status_code,
                        i.input_tokens,
                        i.output_tokens,
                        i.reasoning_tokens,
                        i.cache_read_tokens,
                        i.cache_write_tokens,
                        i.cost_usd,
                        i.duration_ms,
                        i.ttft_ms,
                    )
                    for i in items
                ],
            )
            db.commit()
            return db.total_changes - before

    def _row_to_item(self, row: tuple) -> RequestItem:
        return RequestItem(
            id=row[0],
            started_at=_dt(row[1]),
            model=row[2],
            provider=row[3],
            app=row[4],
            session_id=row[5],
            outcome=row[6],
            status_code=row[7],
            input_tokens=row[8],
            output_tokens=row[9],
            reasoning_tokens=row[10],
            cache_read_tokens=row[11],
            cache_write_tokens=row[12],
            cost_usd=row[13],
            duration_ms=row[14],
            ttft_ms=row[15],
        )

    def requests(
        self,
        limit: int = 200,
        model: str | None = None,
        app: str | None = None,
        outcome: str | None = None,
    ) -> list[RequestItem]:
        sql = "select * from requests"
        where: list[str] = []
        params: list[object] = []
        for column, value in (("model", model), ("app", app), ("outcome", outcome)):
            if value:
                where.append(f"{column} = ?")
                params.append(value)
        if where:
            sql += " where " + " and ".join(where)
        sql += " order by started_at desc limit ?"
        params.append(limit)
        with self._lock:
            rows = self._db().execute(sql, params).fetchall()
        return [self._row_to_item(r) for r in rows]

    def cost_since(self, since: datetime) -> float:
        with self._lock:
            row = self._db().execute(
                "select coalesce(sum(cost_usd), 0) from requests where started_at >= ?", (_ms(since),)
            ).fetchone()
        return float(row[0])

    def aggregate_models(self, since: datetime) -> list[ModelAgg]:
        with self._lock:
            rows = self._db().execute(
                "select model, count(*), coalesce(sum(input_tokens),0),"
                " coalesce(sum(output_tokens),0), coalesce(sum(cache_read_tokens),0),"
                " coalesce(sum(cost_usd),0)"
                " from requests where started_at >= ? group by model order by sum(cost_usd) desc",
                (_ms(since),),
            ).fetchall()
        return [ModelAgg(r[0], r[1], r[2], r[3], r[4], r[5]) for r in rows]

    def daily_cost(self, days: int = 14, now: datetime | None = None) -> list[tuple[date, float]]:
        now = now or datetime.now(timezone.utc)
        today = now.astimezone(timezone.utc).date()
        first = today - timedelta(days=days - 1)
        with self._lock:
            rows = self._db().execute(
                "select started_at, cost_usd from requests where started_at >= ?", (_ms(now.replace(hour=0, minute=0, second=0, microsecond=0)),)
            ).fetchall()
        totals: dict[date, float] = {}
        for started_at, cost in rows:
            day = _dt(started_at).date()
            totals[day] = totals.get(day, 0.0) + cost
        return [(first + timedelta(days=n), totals.get(first + timedelta(days=n), 0.0)) for n in range(days)]

    def meta_get(self, key: str) -> str | None:
        with self._lock:
            row = self._db().execute("select value from meta where key = ?", (key,)).fetchone()
        return row[0] if row else None

    def meta_set(self, key: str, value: str) -> None:
        with self._lock:
            db = self._db()
            db.execute("insert into meta (key, value) values (?, ?) on conflict(key) do update set value=excluded.value", (key, value))
            db.commit()

    def record_alert(self, window: str, kind: str, percent: float, at: datetime) -> bool:
        with self._lock:
            db = self._db()
            row = db.execute(
                "select max(at) from alert_log where window = ? and kind = ?", (window, kind)
            ).fetchone()
            if row and row[0] is not None and at - _dt(row[0]) < ALERT_COOLDOWN:
                return False
            db.execute(
                "insert into alert_log (window, kind, percent, at) values (?,?,?,?)",
                (window, kind, percent, _ms(at)),
            )
            db.commit()
            return True
