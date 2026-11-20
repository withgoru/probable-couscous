"""기록(events). 추가만 하고 수정·삭제는 DB 트리거가 막는다(C6). 이메일·이름·학번은 내용에 넣지 않는다(C7).

누가(actor), 언제(created_at), 어느 학생인지(subject_roster_entry_id 또는 payload의 번호)만 남긴다.
호출하는 쪽이 연 쓰기 트랜잭션 안에서 부른다. 그래야 기록 없이 일이 처리되거나 일 없이 기록만 남지 않는다.
"""

import json
import sqlite3
from datetime import datetime

# 내용에 넣을 수 없는 열 이름(대소문자 무시). 값에 '@'가 있으면 이메일일 수 있어 막는다
_PERSONAL_KEYS = {"email", "email_norm", "name", "student_no"}


def _check(value: object) -> None:
    if isinstance(value, dict):
        for key, inner in value.items():
            if str(key).lower() in _PERSONAL_KEYS:
                raise ValueError(f"기록 내용에 개인정보 열({key})을 넣을 수 없습니다. 번호만 남겨 주세요.")
            _check(inner)
    elif isinstance(value, list | tuple):
        for inner in value:
            _check(inner)
    elif isinstance(value, str) and "@" in value:
        raise ValueError("기록 내용에 이메일로 보이는 값이 있습니다. 개인정보는 기록에 남기지 않습니다.")


def record_event(
    db: sqlite3.Connection,
    classroom_id: int,
    type: str,
    actor_kind: str,
    actor_ref: int | None,
    subject_roster_entry_id: int | None,
    payload: dict,
    now: datetime,
) -> int:
    _check(payload)
    cursor = db.execute(
        "INSERT INTO events(classroom_id, type, actor_kind, actor_ref, subject_roster_entry_id, payload, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (classroom_id, type, actor_kind, actor_ref, subject_roster_entry_id, json.dumps(payload), now.isoformat()),
    )
    return cursor.lastrowid
