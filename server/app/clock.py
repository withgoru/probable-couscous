"""시계 인터페이스. 만료·보관 후 6개월 삭제처럼 시간에 기대는 동작을 테스트에서 시계를 돌려 확인하려고 주입한다(C15)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """현재 시각. 항상 시간대가 있는 UTC."""


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class ManualClock:
    """테스트용. 직접 옮기기 전에는 시각이 흐르지 않는다."""

    def __init__(self, start: datetime) -> None:
        self._now = self._checked(start)

    @staticmethod
    def _checked(when: datetime) -> datetime:
        if when.tzinfo is None:
            raise ValueError("시각에는 시간대가 있어야 합니다(UTC 권장).")
        return when

    def now(self) -> datetime:
        return self._now

    def set(self, when: datetime) -> None:
        self._now = self._checked(when)

    def advance(self, **delta: float) -> None:
        self._now += timedelta(**delta)
