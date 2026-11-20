"""강좌 만들기, 복제, 목록, 조회(AC5~AC8, AC11~AC12).

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
from app.roster import RosterError, add_entry, clean_entry

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
CloneGuard = Annotated[Granted, Depends(guard(Action.CLASSROOM_CLONE, load_classroom))]
RosterGuard = Annotated[Granted, Depends(guard(Action.ROSTER_MANAGE, load_classroom))]
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


class CloneClassroom(BaseModel):
    # 보내지 않은 칸은 원본의 값을 쓴다. 보냈는데 비어 있으면 새로 만들 때와 같은 검사를 받는다
    name: object = None
    section_name: object = None


def _item(db: sqlite3.Connection, classroom_id: int) -> dict:
    row = db.execute(_ITEM_SQL + " WHERE c.id = ?", (classroom_id,)).fetchone()
    return dict(row)


def _insert_classroom(
    db: sqlite3.Connection, owner: int, name: str, section: str | None, source_id: int | None, now: str
) -> dict:
    """강좌 한 개를 새로 만든다. 새 초대 토큰을 받고 명단과 기록은 비어 있다. 토큰이 겹치면 다시 시도한다."""
    for _ in range(TOKEN_ATTEMPTS):
        try:
            with transaction(db):
                cursor = db.execute(
                    "INSERT INTO classrooms(owner_github_id, name, section_name, invite_token, "
                    "source_classroom_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (owner, name, section, secrets.token_urlsafe(16), source_id, now),
                )
            return _item(db, cursor.lastrowid)
        except sqlite3.IntegrityError as err:
            if "invite_token" not in str(err):
                raise  # 초대 토큰이 겹친 경우만 다시 시도한다
    raise HTTPException(status_code=503, detail="강좌를 만들지 못했습니다. 잠시 뒤 다시 시도해 주세요.")


@router.post("/api/classrooms", status_code=201)
def create_classroom(body: NewClassroom, granted: CreateGuard, db: Db, clock: ClockDep):
    name = _clean_name(body.name)
    section = _clean_section(body.section_name)
    return _insert_classroom(db, granted.actor.github_id, name, section, None, clock.now().isoformat())


@router.post("/api/classrooms/{classroom_id}/clone", status_code=201)
def clone_classroom(body: CloneClassroom, granted: CloneGuard, db: Db, clock: ClockDep):
    """분반 만들기, 새 학기로 복제. 이름과 분반만 가져오고 명단, 입장 기록, 초대 링크는 새로 시작한다(AC12)."""
    source = db.execute(
        "SELECT name, section_name FROM classrooms WHERE id = ?", (granted.resource.id,)
    ).fetchone()
    name = _clean_name(body.name) if "name" in body.model_fields_set else source["name"]
    section = (
        _clean_section(body.section_name) if "section_name" in body.model_fields_set else source["section_name"]
    )
    return _insert_classroom(
        db, granted.actor.github_id, name, section, granted.resource.id, clock.now().isoformat()
    )


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


class NewStudent(BaseModel):
    # 형식 검사는 roster.clean_entry가 해서 칸마다 한국어 안내를 준다
    student_no: object = None
    name: object = None
    email: object = None


@router.post("/api/classrooms/{classroom_id}/roster", status_code=201)
def add_student(body: NewStudent, granted: RosterGuard, db: Db, clock: ClockDep):
    """학생 한 명 추가(AC15). 오류의 detail은 `{field, message}`라서 화면이 그 입력 칸 옆에 보여 준다."""
    try:
        entry = clean_entry(body.student_no, body.name, body.email)
        entry_id = add_entry(db, granted.resource.id, entry, clock.now().isoformat())
    except RosterError as err:
        raise HTTPException(status_code=422, detail={"field": err.field, "message": err.message}) from err
    return {"id": entry_id, "student_no": entry.student_no, "name": entry.name, "email": entry.email_norm}
