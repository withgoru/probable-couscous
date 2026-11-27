"""출석의 계산 함수(003 plan "기술 선택과 근거", "확장 지점"). DB를 모르고, 시각은 부르는 쪽이 넘긴다.

- 출석코드: 저장하지 않는다. HMAC-SHA256(서버 비밀값, "attendance:{창 번호}:{창 난수}:{칸}")에서 6자리를 뽑는다.
  칸은 유닉스 시각을 15초로 나눈 번호라 모든 강좌·화면이 같은 경계에서 바뀌고, 서버를 다시 시작해도 같은 값이다(C13).
- 받는 칸: 받은 순간의 칸과 바로 앞 칸(입력하는 사이에 바뀌어도 된다, AC12).
- 틀린 코드 제한기: 1분 안에 5번 틀리면 가장 오래된 틀림 + 60초까지 막는다(AC13). 메모리에만 둔다(plan 위험 5).
- 출석 상태: 회차·학생별 마지막 기록에서 계산한다(C6). 지각 같은 새 상태는 여기와 기록 종류만 늘린다.
"""

import hashlib
import hmac
import math
import re
import threading
from collections import deque
from collections.abc import Callable, Hashable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

SLOT_SECONDS = 15
CODE_DIGITS = 6
LOCK_AFTER = 5  # 1분 안에 이만큼 틀리면 막는다
LOCK_WINDOW = timedelta(seconds=60)

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_SLOT = timedelta(seconds=SLOT_SECONDS)
# ASCII 숫자만. 빠른 길이 아니라 꼭 필요한 검사다: hmac.compare_digest는 ASCII가 아닌 문자열에 TypeError를 낸다
# (전각 숫자 "１２３４５６"이 500이 된다). isdigit()는 전각 숫자도 참이라 정규식으로 본다
_CODE_FORMAT = re.compile(r"[0-9]{6}")


# --- 칸과 코드 ----------------------------------------------------------------------------


def slot_of(when: datetime) -> int:
    """이 시각이 속한 15초 칸 번호."""
    if when.tzinfo is None:
        raise ValueError("시각에는 시간대가 있어야 합니다(UTC 권장).")
    return (when - _EPOCH) // _SLOT


def slot_bounds(slot: int) -> tuple[datetime, datetime]:
    """칸이 시작하는 시각과 끝나는(다음 칸이 시작하는) 시각."""
    start = _EPOCH + slot * _SLOT
    return start, start + _SLOT


def compute_attendance_code(secret: str, window_id: int, nonce: str, slot: int) -> str:
    if not secret:
        raise ValueError("SERVER_SECRET이 비어 있습니다. .env에 값을 넣고 서버를 다시 시작해 주세요.")
    message = f"attendance:{window_id}:{nonce}:{slot}".encode()
    digest = hmac.new(secret.encode(), message, hashlib.sha256).digest()
    # 64비트에서 뽑아 100만으로 나눈 나머지의 치우침은 무시할 만큼 작다(challenges.compute_code와 같다)
    return str(int.from_bytes(digest[:8], "big") % 10**CODE_DIGITS).zfill(CODE_DIGITS)


def code_accepted(secret: str, window_id: int, nonce: str, typed: object, now: datetime) -> bool:
    """받은 순간(now)의 칸이나 바로 앞 칸의 코드면 참. 형식이 틀리면 계산하지 않고 거짓."""
    if not isinstance(typed, str) or not _CODE_FORMAT.fullmatch(typed):
        return False
    current = slot_of(now)
    ok = False
    for slot in (current, current - 1):  # 둘 다 비교해 어느 칸에서 맞았는지 시간으로 드러내지 않는다
        ok |= hmac.compare_digest(compute_attendance_code(secret, window_id, nonce, slot), typed)
    return ok


# --- 틀린 코드 제한기 -------------------------------------------------------------------------


@dataclass(frozen=True)
class Attempt:
    ok: bool  # 코드가 맞았다
    locked: bool  # 막혀 있어 코드를 보지도 않았다
    seconds: int  # 막혔으면(이번 틀림으로 막힌 경우 포함) 남은 초, 아니면 0


class WrongCodeLimiter:
    """키(강좌, 멤버십)마다 최근 1분의 틀린 시각을 기억한다. 여러 요청 스레드에서 함께 쓴다."""

    def __init__(self) -> None:
        self._wrong: dict[Hashable, deque[datetime]] = {}
        self._lock = threading.Lock()

    def _forget_old(self, now: datetime) -> None:
        cutoff = now - LOCK_WINDOW
        for key in list(self._wrong):
            times = self._wrong[key]
            while times and times[0] <= cutoff:
                times.popleft()
            if not times:
                del self._wrong[key]

    def _seconds_left(self, key: Hashable, now: datetime) -> int:
        times = self._wrong.get(key)
        if not times or len(times) < LOCK_AFTER:
            return 0
        until = times[-LOCK_AFTER] + LOCK_WINDOW
        return max(0, math.ceil((until - now).total_seconds()))

    def locked_for(self, key: Hashable, now: datetime) -> int:
        """막혀 있으면 남은 초(올림), 아니면 0."""
        with self._lock:
            self._forget_old(now)
            return self._seconds_left(key, now)

    def record_wrong(self, key: Hashable, now: datetime) -> int:
        """틀림을 하나 더하고, 이번 틀림으로 막혔으면 남은 초를 돌려준다(아니면 0)."""
        with self._lock:
            self._forget_old(now)
            self._wrong.setdefault(key, deque()).append(now)
            return self._seconds_left(key, now)

    def attempt(self, key: Hashable, now: datetime, check: Callable[[], bool]) -> Attempt:
        """막혀 있는지 보고, 아니면 코드를 확인하고, 틀리면 센다. 세 단계를 한 잠금 안에서 한다.

        따로 부르면 한 학생이 동시에 여러 요청을 보내 모두 '아직 안 막힘'을 지나갈 수 있다(5번 제한을 넘는다).
        `check`는 DB를 쓰지 않는 빠른 계산(코드 비교)이어야 한다.
        """
        with self._lock:
            self._forget_old(now)
            left = self._seconds_left(key, now)
            if left:
                return Attempt(ok=False, locked=True, seconds=left)
            if check():
                return Attempt(ok=True, locked=False, seconds=0)
            self._wrong.setdefault(key, deque()).append(now)
            return Attempt(ok=False, locked=False, seconds=self._seconds_left(key, now))

    def tracked(self) -> int:
        """기억하고 있는 키 수(테스트용)."""
        with self._lock:
            return len(self._wrong)


# --- 상태 ---------------------------------------------------------------------------------


class AttendanceStatus(StrEnum):
    PRESENT = "present"  # 출석코드로 출석
    MANUAL = "manual"  # 출석 (수기): 요청 승인이나 교수의 직접 바꾸기
    ABSENT = "absent"  # 기록이 없거나 교수가 결석으로 바꿈


_STATUS_OF_KIND = {
    "code": AttendanceStatus.PRESENT,
    "request_approved": AttendanceStatus.MANUAL,
    "manual_present": AttendanceStatus.MANUAL,
    "manual_absent": AttendanceStatus.ABSENT,
}


def attendance_status(kinds: Iterable[str]) -> AttendanceStatus:
    """한 회차·한 학생의 기록 종류를 기록 순서(번호 순)로 받아 상태를 계산한다. 마지막 기록이 정한다."""
    status = AttendanceStatus.ABSENT
    for kind in kinds:
        try:
            status = _STATUS_OF_KIND[kind]
        except KeyError:
            raise ValueError(f"모르는 출석 기록 종류입니다: {kind!r}") from None
    return status
