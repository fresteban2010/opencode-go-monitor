from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from .analysis import Summary, summary as build_summary
from .backoff import Backoff
from .client import OpenCodeClient
from .config import Config, load, paths
from .credentials import Credential, CredentialsError, resolve
from .notify import Notifier, send
from .store import Store
from .sync import SyncResult, synchronize


class Monitor:
    def __init__(self, cfg: Config | None = None, data_path: Path | None = None) -> None:
        self.cfg = cfg or load()
        data = data_path or paths()[1]
        self.store = Store(data / "monitor.db")
        self.store.init()
        self.notifier = Notifier(self.store, self.cfg.thresholds)
        self.backoff = Backoff()
        self.credential: Credential | None = None
        self.last_result: SyncResult | None = None
        self.last_error: str | None = None
        self.logs_unavailable = False
        self._last_logs_sync: datetime | None = None

    def refresh(self, full: bool = False, force: bool = False) -> SyncResult | None:
        now = datetime.now(timezone.utc)
        if not force and self.backoff.active(now):
            return self.last_result

        try:
            self.credential = resolve(config_key=self.cfg.api_key)
        except CredentialsError as error:
            self.last_error = str(error)
            return None
        except Exception as error:  # noqa: BLE001 - monitor must survive any failure
            self.last_error = f"Error leyendo credenciales: {error}"
            return None

        oauth = self.credential.kind == "oauth"
        due = (
            self._last_logs_sync is None
            or (now - self._last_logs_sync).total_seconds() >= self.cfg.sync_seconds
        )
        include_logs = oauth and (due or full or force)

        try:
            client = OpenCodeClient(self.credential.token)
            result = synchronize(
                self.store,
                client,
                full=full,
                page_size=self.cfg.request_page_size,
                max_pages=1000 if full else 40,
                include_logs=include_logs,
            )
        except Exception as error:  # noqa: BLE001 - monitor must survive any failure
            self.last_error = f"Error inesperado: {error}"
            return None

        self.last_result = result
        self.last_error = "; ".join(result.errors) or None
        self.logs_unavailable = (not oauth) or result.logs_stale
        if include_logs:
            self._last_logs_sync = now

        if result.stale:
            if result.retryable:
                self.backoff.next(retry_after=result.retry_after, now=now)
            else:
                self.backoff.next(retry_after=300, now=now)
        else:
            self.backoff.reset()

        self._notify()
        return result

    def _notify(self) -> None:
        if not self.cfg.notify:
            return
        state = self.summary()
        if state.usage is None:
            return
        for alert in self.notifier.evaluate(state.usage, state.burns, datetime.now(timezone.utc)):
            send(alert)

    def summary(self, now: datetime | None = None) -> Summary:
        return build_summary(self.store, now)

    def is_stale(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        usage = self.store.last_usage()
        if usage is None:
            return True
        return (now - usage.fetched_at).total_seconds() > self.cfg.stale_after_seconds

    def local_spend(self, now: datetime | None = None) -> dict[str, float]:
        from .localdb import DEFAULT_OPENCODE_DB, session_totals

        now = now or datetime.now(timezone.utc)
        local = now.astimezone()
        day_start = local.replace(hour=0, minute=0, second=0, microsecond=0)
        return {
            "today": session_totals(DEFAULT_OPENCODE_DB, day_start).cost_usd,
            "7d": session_totals(DEFAULT_OPENCODE_DB, now - timedelta(days=7)).cost_usd,
            "30d": session_totals(DEFAULT_OPENCODE_DB, now - timedelta(days=30)).cost_usd,
        }

    def close(self) -> None:
        self.store.close()
