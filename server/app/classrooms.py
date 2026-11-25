"""강좌 만들기, 복제, 목록, 조회(AC5~AC8, AC11~AC12).

모든 라우트는 `authz`의 `guard`로 권한 판단을 거친다(C8). 목록은 로그인한 교수의 강좌만 읽고(C5),
다른 교수의 강좌는 번호로 조회해도 `guard`가 막는다. 초대 토큰은 응답에 싣지 않는다(초대 링크는 T014).
"""

import logging
import secrets
import sqlite3
from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app import events
from app.authz import Action, ClassroomRef, Granted, guard, guard_account
from app.challenges import supersede_classroom
from app.clock import Clock
from app.db import get_db, transaction
from app.identity import entered_roster_ids
from app.realtime import publish_admin, publish_class
from app.roster import (
    IMPORT_MAX_BYTES,
    ROSTER_LIMIT,
    TOO_LARGE,
    RosterError,
    add_entry,
    clean_entry,
    import_rows,
    parse_csv,
    remove_entry,
    revoke_login,
)
from app.session_clone import copy_sessions

log = logging.getLogger(__name__)
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
         WHERE r.classroom_id = c.id AND r.removed_at IS NULL) AS student_count,
       (SELECT COUNT(*) FROM class_sessions s
         WHERE s.classroom_id = c.id AND s.first_started_at IS NOT NULL) AS session_count
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
ManageGuard = Annotated[Granted, Depends(guard(Action.CLASSROOM_MANAGE, load_classroom))]
CloneGuard = Annotated[Granted, Depends(guard(Action.CLASSROOM_CLONE, load_classroom))]
RosterGuard = Annotated[Granted, Depends(guard(Action.ROSTER_MANAGE, load_classroom))]
CreateGuard = Annotated[Granted, Depends(guard_account(Action.CLASSROOM_CREATE))]
ListGuard = Annotated[Granted, Depends(guard_account(Action.CLASSROOM_LIST))]
MeGuard = Annotated[Granted, Depends(guard_account(Action.ME_READ))]


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
    db: sqlite3.Connection,
    owner: int,
    name: str,
    section: str | None,
    source_id: int | None,
    now: str,
    fill: Callable[[sqlite3.Connection, int], None] | None = None,
) -> dict:
    """강좌 한 개를 새로 만든다. 새 초대 토큰을 받고 명단과 기록은 비어 있다. 토큰이 겹치면 다시 시도한다.

    `fill(db, 새 강좌 번호)`가 있으면 같은 쓰기 트랜잭션에서 부른다(복제의 회차 복사). 실패하면 강좌도 만들지 않는다.
    """
    for _ in range(TOKEN_ATTEMPTS):
        try:
            with transaction(db):
                cursor = db.execute(
                    "INSERT INTO classrooms(owner_github_id, name, section_name, invite_token, "
                    "source_classroom_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (owner, name, section, secrets.token_urlsafe(16), source_id, now),
                )
                if fill is not None:
                    fill(db, cursor.lastrowid)
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
def clone_classroom(body: CloneClassroom, granted: CloneGuard, db: Db, clock: ClockDep, request: Request):
    """분반 만들기, 새 학기로 복제. 이름과 분반을 가져오고 명단, 입장 기록, 초대 링크는 새로 시작한다(AC12).

    회차와 슬라이드 묶음은 '예정' 상태로 복사한다(002 AC42). 보낸 항목과 위치는 복사하지 않는다.
    """
    source = db.execute(
        "SELECT name, section_name FROM classrooms WHERE id = ?", (granted.resource.id,)
    ).fetchone()
    name = _clean_name(body.name) if "name" in body.model_fields_set else source["name"]
    section = (
        _clean_section(body.section_name) if "section_name" in body.model_fields_set else source["section_name"]
    )
    store = request.app.state.deck_store
    now = clock.now().isoformat()
    copied: list[int] = []
    new_id: list[int] = []

    def fill(conn: sqlite3.Connection, classroom_id: int) -> None:
        new_id[:] = [classroom_id]
        copy_sessions(conn, store, granted.resource.id, classroom_id, now, copied)

    try:
        return _insert_classroom(db, granted.actor.github_id, name, section, granted.resource.id, now, fill)
    except HTTPException:
        raise
    except Exception as err:
        for deck_id in copied:  # 되돌린 강좌의 파일을 남기지 않는다
            store.remove(new_id[0], deck_id)
        log.exception("강좌 %s를 복제하지 못했습니다.", granted.resource.id)
        raise HTTPException(status_code=500, detail=CLONE_FAILED) from err


CLONE_FAILED = "강좌를 복제하지 못했습니다. 잠시 뒤 다시 시도해 주세요."
ALREADY_ARCHIVED = "이미 보관된 강좌입니다."
LIVE_CANNOT_ARCHIVE = "{title} 수업이 진행 중입니다. 수업을 끝낸 뒤 보관해 주세요."


@router.post("/api/classrooms/{classroom_id}/archive")
def archive_classroom(granted: ManageGuard, db: Db, clock: ClockDep):
    """강좌 보관(AC9, AC10). 학생 입장을 닫고(로그인 유지 중이던 학생도 `student.enter`에서 막힌다) 기록한다.

    아직 쓰지 않은 코드는 모두 쓸 수 없게 해서 보내지 않은 코드 메일도 나가지 않는다. 기록은 그대로 볼 수 있다.
    수업 중이면 보관하지 않는다(002 AC46). 보관 시각은 6개월 정리의 기준이라 다시 보관해도 바꾸지 않는다.
    """
    classroom_id = granted.resource.id
    now = clock.now()
    with transaction(db):
        # 수업 중에는 보관하지 않는다(002 AC46). 보관하면 학생 로그인이 모두 끊겨 수업이 멈춘다.
        # 같은 쓰기 트랜잭션에서 보므로 시작·이어서 하기와 엇갈리지 않는다
        live = db.execute(
            "SELECT id, title FROM class_sessions WHERE classroom_id = ? AND status = 'live'", (classroom_id,)
        ).fetchone()
        changed = 0
        if live is None:
            changed = db.execute(
                "UPDATE classrooms SET status = 'archived', archived_at = ? WHERE id = ? AND status = 'active'",
                (now.isoformat(), classroom_id),
            ).rowcount
            if changed:
                supersede_classroom(db, classroom_id)
                events.record_event(
                    db, classroom_id, "classroom_archived", "professor", granted.actor.github_id, None, {}, now
                )
    if live is not None:
        return JSONResponse(
            status_code=409,
            content={"detail": LIVE_CANNOT_ARCHIVE.format(title=live["title"]), "live_session_id": live["id"]},
        )
    if not changed:
        raise HTTPException(status_code=409, detail=ALREADY_ARCHIVED)
    return _item(db, classroom_id)


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


def _roster_problem(err: RosterError, status: int = 422) -> HTTPException:
    # detail은 `{field, message}`라서 화면이 그 입력 칸(field가 없으면 명단 전체) 옆에 보여 준다
    return HTTPException(status_code=status, detail={"field": err.field, "message": err.message})


@router.post("/api/classrooms/{classroom_id}/roster", status_code=201)
def add_student(body: NewStudent, granted: RosterGuard, db: Db, clock: ClockDep, request: Request):
    """학생 한 명 추가(AC15)."""
    try:
        entry = clean_entry(body.student_no, body.name, body.email)
        entry_id = add_entry(db, granted.resource.id, entry, clock.now().isoformat())
    except RosterError as err:
        raise _roster_problem(err) from err
    publish_admin(request, granted.resource.id, "roster.updated")  # 저장이 끝난 뒤에 알린다
    return {"id": entry_id, "student_no": entry.student_no, "name": entry.name, "email": entry.email_norm}


_ROSTER_STATUS = {"not_found": 404, "not_entered": 409}


@router.delete("/api/classrooms/{classroom_id}/roster/{entry_id}")
def remove_student(entry_id: int, granted: RosterGuard, db: Db, clock: ClockDep, request: Request):
    """명단에서 빼기(AC19). 입장이 거부되고 이 강좌의 로그인 유지가 끝난다. 기록한다(AC48)."""
    classroom_id = granted.resource.id
    try:
        gone, membership_id = remove_entry(db, classroom_id, entry_id, granted.actor.github_id, clock.now())
    except RosterError as err:
        raise _roster_problem(err, _ROSTER_STATUS[err.reason]) from err
    for challenge_id in gone:  # 저장이 끝난 뒤에 알린다
        publish_admin(request, classroom_id, "pending_auth.updated", id=challenge_id)
    publish_admin(request, classroom_id, "roster.updated")
    if membership_id is not None:  # 수업 중이면 그 학생의 연결을 닫는다(002 AC44)
        publish_class(request, classroom_id, "member_revoked", membership_id=membership_id, reason="removed")
    return {"id": entry_id, "removed": True}


@router.post("/api/classrooms/{classroom_id}/roster/{entry_id}/revoke-login")
def revoke_student_login(entry_id: int, granted: RosterGuard, db: Db, clock: ClockDep, request: Request):
    """로그인 끊기(AC20). 이 학생의 모든 기기가 이 강좌에서 로그아웃된다. 바뀌는 목록이 없어 교수 화면에 알리지 않는다.

    수업 중이면 그 학생의 수업 연결을 닫는다(002 AC44).
    """
    try:
        membership_id = revoke_login(db, granted.resource.id, entry_id, granted.actor.github_id, clock.now())
    except RosterError as err:
        raise _roster_problem(err, _ROSTER_STATUS[err.reason]) from err
    publish_class(request, granted.resource.id, "member_revoked", membership_id=membership_id, reason="signed_out")
    return {"id": entry_id, "revoked": True}


@router.get("/api/me/summary")
def me_summary(granted: MeGuard, db: Db):
    """마이페이지(AC49). 로그인한 교수의 계정, 강좌 수, 진행 중 수강생 합계, 진행 중 강좌 목록."""
    owner = granted.actor.github_id
    professor = db.execute("SELECT github_id, login FROM professors WHERE github_id = ?", (owner,)).fetchone()
    rows = db.execute(
        _ITEM_SQL + " WHERE c.owner_github_id = ? ORDER BY c.created_at DESC, c.id DESC", (owner,)
    ).fetchall()
    classrooms = [dict(r) for r in rows]
    active = [c for c in classrooms if c["status"] == "active"]
    return JSONResponse(
        {
            "github_id": professor["github_id"],
            "login": professor["login"],
            "counts": {"active": len(active), "archived": len(classrooms) - len(active)},
            "active_students": sum(c["student_count"] for c in active),
            "active_classrooms": active,
        },
        headers={"Cache-Control": "no-store"},
    )


async def csv_body(request: Request) -> bytes:
    """본문을 1MB까지만 읽는다. 헤더의 크기와 실제로 받은 크기를 둘 다 본다."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > IMPORT_MAX_BYTES:
        raise _roster_problem(RosterError("too_large", TOO_LARGE), 413)
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > IMPORT_MAX_BYTES:
            raise _roster_problem(RosterError("too_large", TOO_LARGE), 413)
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/api/classrooms/{classroom_id}/roster/import")
def import_roster(
    granted: RosterGuard, data: Annotated[bytes, Depends(csv_body)], db: Db, clock: ClockDep, request: Request
):
    """CSV 올리기(AC13, AC14, AC18). 본문은 CSV 파일 그대로다. 권한을 먼저 보고, 통과한 뒤에만 본문을 읽는다."""
    try:
        rows = parse_csv(data)
        result = import_rows(db, granted.resource.id, rows, clock.now().isoformat())
    except RosterError as err:
        raise _roster_problem(err) from err
    if result["added"]:
        publish_admin(request, granted.resource.id, "roster.updated")
    return result


@router.get("/api/classrooms/{classroom_id}/roster")
def list_roster(granted: RosterGuard, db: Db):
    """명단 조회(AC17). 학번, 이름, 이메일, 입장 여부만 준다. 닉네임과 연결 정보는 싣지 않는다(C9)."""
    rows = db.execute(
        "SELECT id, student_no, name, email_norm AS email FROM roster_entries "
        "WHERE classroom_id = ? AND removed_at IS NULL ORDER BY id",
        (granted.resource.id,),
    ).fetchall()
    entered = entered_roster_ids(db, granted.resource.id)
    entries = [{**dict(r), "entered": r["id"] in entered} for r in rows]
    return JSONResponse(
        {"entries": entries, "count": len(entries), "limit": ROSTER_LIMIT},
        headers={"Cache-Control": "no-store"},
    )
