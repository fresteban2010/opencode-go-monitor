from datetime import datetime, timedelta, timezone

from ocgm.core.backoff import Backoff

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)


def test_backoff_doubles_up_to_the_cap() -> None:
    b = Backoff(base=30, maximum=900)
    assert b.next(now=NOW) == NOW + timedelta(seconds=30)
    assert b.next(now=NOW) == NOW + timedelta(seconds=60)
    assert b.next(now=NOW) == NOW + timedelta(seconds=120)
    for _ in range(10):
        b.next(now=NOW)
    assert b.next(now=NOW) == NOW + timedelta(seconds=900)


def test_retry_after_is_honored_and_clamped() -> None:
    b = Backoff(base=30, maximum=900)
    assert b.next(retry_after=120, now=NOW) == NOW + timedelta(seconds=120)
    assert b.next(retry_after=5000, now=NOW) == NOW + timedelta(seconds=900)
    assert b.next(retry_after=5, now=NOW) == NOW + timedelta(seconds=30)


def test_active_until_and_reset() -> None:
    b = Backoff(base=30, maximum=900)
    b.next(now=NOW)
    assert b.active(NOW + timedelta(seconds=10))
    assert not b.active(NOW + timedelta(seconds=31))
    b.reset()
    assert not b.active(NOW + timedelta(seconds=10))
