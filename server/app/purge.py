"""보관 후 6개월이 지난 강좌의 개인정보 정리(C11, plan '보관 후 6개월 삭제', T031).

하루 한 번 돈다. 지우는 것: 명단, 멤버십과 사람의 연결과 기기 인증 기록, 입장 요청, 인증 챌린지, 메일 발송 대기,
그리고 어느 강좌에도 이어지지 않게 된 계정과 그 기기 로그인(사람 쪽은 `identity` 모듈이 지운다, C9).
출석 창, 출석 기록, 수기 요청(사유)과 그 처리도 지운다(003 plan '보관 기간', T012). 이 표들을 지우는 코드는 여기뿐이다.
남기는 것: 강좌, 회차, 멤버십(가명), 기록(events, C6). 강좌마다 한 트랜잭션이고, 정리 결과를 같은 트랜잭션에서
`pii_purged` 기록으로 남긴다. 같은 입력에 여러 번 돌려도 결과가 같다: 지운 것이 없고 이미 기록이 있으면 다시 기록하지 않는다.
"""

import calendar
import logging
import sqlite3
import threading
from collections.abc import Callable
from datetime import datetime

from app import events, identity
from app.clock import Clock
from app.db import transaction

log = logging.getLogger(__name__)

RETENTION_MONTHS = 6
# 외래 키 순서: 기록과 처리가 요청을 가리키므로 요청보다 먼저 지운다. 창은 아무도 가리키지 않는다
ATTENDANCE_TABLES = ("attendance_marks", "attendance_decisions", "attendance_requests", "attendance_windows")
DAY_SECONDS = 24 * 60 * 60
THREAD_NAME = "pii-purge"


def months_before(when: datetime, months: int) -> datetime:
    """달력 기준으로 몇 달 전. 그 달에 같은 날이 없으면 말일로 맞춘다(예: 2월 28일의 6개월 전은 8월 28일)."""
    month_index = when.year * 12 + (when.month - 1) - months
    year, month = divmod(month_index, 12)
    day = min(when.day, calendar.monthrange(year, month + 1)[1])
    return when.replace(year=year, month=month + 1, day=day)


def _due_classrooms(db: sqlite3.Connection, now: datetime) -> list[int]:
    cutoff = months_before(now, RETENTION_MONTHS).isoformat()
    rows = db.execute(
        "SELECT id FROM classrooms WHERE status = 'archived' AND archived_at IS NOT NULL AND archived_at <= ? ORDER BY id",
        (cutoff,),
    ).fetchall()
    return [r["id"] for r in rows]


def _purge_one(db: sqlite3.Connection, classroom_id: int, now: datetime) -> dict[str, int] | None:
    """한 강좌를 정리한다. 기록했으면 지운 수를, 지운 것도 없고 이미 기록이 있으면 None을 돌려준다."""
    with transaction(db):
        counts = identity.forget_classroom_people(db, classroom_id)  # 명단을 가리키므로 먼저 지운다
        for table in ("roster_entries", "join_requests", "mail_outbox", "login_challenges", *ATTENDANCE_TABLES):
            counts[table] = db.execute(f"DELETE FROM {table} WHERE classroom_id = ?", (classroom_id,)).rowcount
        already = db.execute(
            "SELECT 1 FROM events WHERE classroom_id = ? AND type = 'pii_purged' LIMIT 1", (classroom_id,)
        ).fetchone()
        if already and not any(counts.values()):
            return None
        events.record_event(db, classroom_id, "pii_purged", "system", None, None, counts, now)
    return counts


def purge_due(db: sqlite3.Connection, now: datetime) -> list[dict]:
    """보관 6개월이 지난 강좌를 모두 정리한다. 기록한 강좌마다 {classroom_id, counts}를 돌려준다."""
    results = []
    for classroom_id in _due_classrooms(db, now):
        counts = _purge_one(db, classroom_id, now)
        if counts is not None:
            results.append({"classroom_id": classroom_id, "counts": counts})
            log.info("보관 6개월이 지난 강좌 %s의 개인정보를 정리했습니다: %s", classroom_id, counts)
    return results


class PurgeJob:
    """시작할 때 한 번, 그 뒤 하루에 한 번 `purge_due`를 돈다. 실패해도 스레드는 멈추지 않고 다음 차례에 다시 한다."""

    def __init__(
        self, open_db: Callable[[], sqlite3.Connection], clock: Clock, interval_seconds: float = DAY_SECONDS
    ) -> None:
        self._open_db = open_db
        self._clock = clock
        self.interval_seconds = interval_seconds
        self.last_result: list[dict] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def run_once(self) -> list[dict]:
        db = self._open_db()
        try:
            self.last_result = purge_due(db, self._clock.now())
        finally:
            db.close()
        return self.last_result

    def start(self) -> None:
        if self.is_running():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name=THREAD_NAME, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:  # DB가 잠겼거나 일시 오류여도 다음 차례에 다시 한다
                log.exception("개인정보 정리 작업 중 오류가 났습니다. 다음 차례에 다시 시도합니다.")
            self._stop.wait(self.interval_seconds)
