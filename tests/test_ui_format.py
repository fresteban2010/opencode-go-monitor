from datetime import date, datetime, timezone

from ocgm.ui.format import clock, date_short, eta_label, money, money_small, tokens


def test_date_short_accepts_date_and_datetime() -> None:
    assert date_short(date(2026, 10, 25)) == "25 oct"
    assert date_short(datetime(2026, 10, 25, 12, tzinfo=timezone.utc)) == "25 oct"


def test_clock_formats_local_time() -> None:
    assert clock(datetime(2026, 10, 25, 12, tzinfo=timezone.utc))
    assert clock(None) == "—"


def test_money_and_tokens() -> None:
    assert money(1.5) == "$1.50"
    assert money_small(0.00106785) == "$0.00107"
    assert money_small(0.5) == "$0.50"
    assert money_small(0.0) == "$0.00"
    assert tokens(1500) == "1.5k"
    assert tokens(2_000_000) == "2.0M"


def test_eta_label_includes_date_when_not_today() -> None:
    tz = datetime.now().astimezone().tzinfo
    now = datetime(2026, 10, 26, 14, 23, tzinfo=tz)
    same_day = datetime(2026, 10, 26, 18, 0, tzinfo=tz)
    later = datetime(2026, 10, 28, 5, 24, tzinfo=tz)
    assert eta_label(same_day, now=now) == "18:00"
    assert eta_label(later, now=now) == "28 oct 05:24"
