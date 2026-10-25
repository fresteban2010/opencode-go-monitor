from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .analysis import Summary, summary as build_summary
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
        self.credential: Credential | None = None
        self.last_result: SyncResult | None = None
        self.last_error: str | None = None

    def refresh(self, full: bool = False) -> SyncResult | None:
        try:
            self.credential = resolve(config_key=self.cfg.api_key)
        except CredentialsError as error:
            self.last_error = str(error)
            return None
        try:
            client = OpenCodeClient(self.credential.token)
            result = synchronize(
                self.store, client, full=full, page_size=self.cfg.request_page_size
            )
        except Exception as error:  # noqa: BLE001 - monitor must survive any failure
            self.last_error = f"Error inesperado: {error}"
            return None
        self.last_result = result
        self.last_error = "; ".join(result.errors) or None
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

    def close(self) -> None:
        self.store.close()
