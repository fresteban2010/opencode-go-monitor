from __future__ import annotations

from datetime import datetime, timedelta


class Backoff:
    def __init__(self, base: int = 30, maximum: int = 900) -> None:
        self.base = base
        self.maximum = maximum
        self._current = 0
        self._until: datetime | None = None

    def next(self, retry_after: float | None = None, now: datetime | None = None) -> datetime:
        now = now or datetime.now().astimezone()
        if retry_after is not None:
            delay = max(self.base, retry_after)
        else:
            delay = self.base if self._current == 0 else self._current * 2
        delay = min(self.maximum, delay)
        self._current = int(delay)
        self._until = now + timedelta(seconds=self._current)
        return self._until

    def active(self, now: datetime | None = None) -> bool:
        if self._until is None:
            return False
        now = now or datetime.now().astimezone()
        return now < self._until

    def reset(self) -> None:
        self._current = 0
        self._until = None

    @property
    def until(self) -> datetime | None:
        return self._until
