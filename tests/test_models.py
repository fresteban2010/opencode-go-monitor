from datetime import datetime, timezone

from ocgm.core.models import WindowUsage


def _window(status: str, percent: float = 50.0) -> WindowUsage:
    return WindowUsage(status, percent, datetime(2026, 10, 25, 12, tzinfo=timezone.utc))


def test_ok_status_is_not_limited() -> None:
    assert _window("ok").is_limited is False


def test_unknown_status_is_not_treated_as_exhausted() -> None:
    assert _window("unknown").is_limited is False


def test_known_limited_statuses_are_limited() -> None:
    assert _window("rate-limited").is_limited is True
    assert _window("limited").is_limited is True


def test_full_percent_is_limited_even_with_ok_status() -> None:
    assert _window("ok", 100.0).is_limited is True
