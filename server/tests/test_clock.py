from datetime import UTC, datetime, timedelta

from app.clock import ManualClock, SystemClock


def test_system_clock_is_timezone_aware_utc():
    now = SystemClock().now()
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)
    assert abs((datetime.now(UTC) - now).total_seconds()) < 5


def test_manual_clock_starts_where_told_and_only_moves_when_advanced():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    clock = ManualClock(start)
    assert clock.now() == start
    assert clock.now() == start
    clock.advance(minutes=10)
    assert clock.now() == start + timedelta(minutes=10)
    clock.set(datetime(2027, 6, 1, tzinfo=UTC))
    assert clock.now() == datetime(2027, 6, 1, tzinfo=UTC)


def test_manual_clock_rejects_naive_datetimes():
    import pytest

    with pytest.raises(ValueError):
        ManualClock(datetime(2026, 1, 1))
