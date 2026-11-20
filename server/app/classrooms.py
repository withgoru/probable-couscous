"""강좌 만들기, 목록, 조회(AC5~AC8).

모든 라우트는 `authz`의 `guard`로 권한 판단을 거친다(C8). 목록은 로그인한 교수의 강좌만 읽고(C5),
다른 교수의 강좌는 번호로 조회해도 `guard`가 막는다. 초대 토큰은 응답에 싣지 않는다(초대 링크는 T014).
"""

import secrets
import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.authz import Action, ClassroomRef, Granted, guard, guard_account
from app.clock import Clock
from app.db import get_db, transaction

router = APIRouter()

NAME_MAX = 100
SECTION_MAX = 50
TOKEN_ATTEMPTS = 5

Db = Annotated[sqlite3.Connection, Depends(get_db)]


def _clock(request: Request) -> Clock:
    return request.app.state.clock


ClockDep = Annotated[Clock, Depends(_clock)]

_ITEM_SQL = """
SELECT c.id, c.name, c.section_name, c.status, c.created_at,
       (SELECT COUNT(*) FROM roster_entries r
         WHERE r.classroom_id = c.id AND r.removed_at IS NULL) AS student_count
  FROM classrooms c
"""


def load_classroom(classroom_id: int, db: Db) -> ClassroomRef | None:
    """`guard`가 쓰는 강좌 불러오기. 없으면 None."""
    row = db.execute(
        "SELECT id, owner_github_id, status FROM classrooms WHERE id = ?", (classroom_id,)
    ).fetchone()
    if row is None:
        return None
    return ClassroomRef(id=row["id"], owner_github_id=row["owner_github_id"], status=row["status"])


ReadGuard = Annotated[Granted, Depends(guard(Action.CLASSROOM_READ, load_classroom))]
CreateGuard = Annotated[Granted, Depends(guard_account(Action.CLASSROOM_CREATE))]
ListGuard = Annotated[Granted, Depends(guard_account(Action.CLASSROOM_LIST))]


class NewClassroom(BaseModel):
    # 형식 검사는 직접 해서 사람이 읽을 수 있는 한국어 안내를 준다
    name: object = ""
    section_name: object = None


def _invalid(message: str) -> HTTPException:
    return HTTPException(status_code=422, detail=message)


def _clean_name(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid("강좌 이름을 입력해 주세요.")
    name = value.strip()
    if len(name) > NAME_MAX:
        raise _invalid(f"강좌 이름은 {NAME_MAX}자 이하로 입력해 주세요.")
    return name


def _clean_section(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise _invalid("분반 이름은 글자로 입력해 주세요.")
    section = value.strip()
    if not section:
        return None
    if len(section) > SECTION_MAX:
        raise _invalid(f"분반 이름은 {SECTION_MAX}자 이하로 입력해 주세요.")
    return section


def _item(db: sqlite3.Connection, classroom_id: int) -> dict:
    row = db.execute(_ITEM_SQL + " WHERE c.id = ?", (classroom_id,)).fetchone()
    return dict(row)


@router.post("/api/classrooms", status_code=201)
def create_classroom(body: NewClassroom, granted: CreateGuard, db: Db, clock: ClockDep):
    name = _clean_name(body.name)
    section = _clean_section(body.section_name)
    now = clock.now().isoformat()
    for _ in range(TOKEN_ATTEMPTS):
        try:
            with transaction(db):
                cursor = db.execute(
                    "INSERT INTO classrooms(owner_github_id, name, section_name, invite_token, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (granted.actor.github_id, name, section, secrets.token_urlsafe(16), now),
                )
            return _item(db, cursor.lastrowid)
        except sqlite3.IntegrityError as err:
            if "invite_token" not in str(err):
                raise  # 초대 토큰이 겹친 경우만 다시 시도한다
    raise HTTPException(status_code=503, detail="강좌를 만들지 못했습니다. 잠시 뒤 다시 시도해 주세요.")


@router.get("/api/classrooms")
def list_classrooms(granted: ListGuard, db: Db):
    rows = db.execute(
        _ITEM_SQL + " WHERE c.owner_github_id = ? ORDER BY c.created_at DESC, c.id DESC",
        (granted.actor.github_id,),
    ).fetchall()
    classrooms = [dict(r) for r in rows]
    counts = {"active": 0, "archived": 0}
    for c in classrooms:
        counts[c["status"]] += 1
    return {"classrooms": classrooms, "counts": counts}


@router.get("/api/classrooms/{classroom_id}")
def get_classroom(granted: ReadGuard, db: Db):
    return _item(db, granted.resource.id)
