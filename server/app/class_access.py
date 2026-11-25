"""강좌 안에서 요청한 사람이 누구인가(002 `class.view`). 교수 로그인이거나, 그 강좌에 입장한 학생이다.

`authz.get_actor`는 강좌를 모른 채 교수만 알아본다. 학생의 기기 로그인은 계정 단위라서, 어느 강좌의 학생인지는
강좌를 알아야 정해진다. 그래서 강좌를 먼저 불러온 뒤 행위자를 정하는 `guard_class`를 둔다. 판단 자체는 여전히
`authz.decide` 한 곳에서 한다(C8).

입장한 학생: 유효한 기기 로그인 + 그 강좌의 살아 있는 명단에 이메일이 있음 + 교수가 로그인을 끊은 뒤에 만든 로그인 +
그 로그인으로 '확인하고 입장'까지 마침(001 AC20, AC28, AC44).
"""

import sqlite3
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException
from starlette.requests import HTTPConnection

from app import identity, student_login
from app.authz import Action, Actor, ClassroomRef, Granted, _deny, decide, get_actor
from app.challenges import DEVICE_COOKIE
from app.db import get_db
from app.roster import find_live_by_email
from app.student_login import LOGIN_COOKIE, current_login


def fresh_login(request: HTTPConnection, db: sqlite3.Connection, classroom_id: int):
    """이 강좌에서 쓸 수 있는 기기 로그인과 그 계정의 명단 항목. 쓸 수 없으면 None.

    로그인이 유효해야 하고, 계정의 이메일이 이 강좌의 살아 있는 명단에 있어야 하며,
    교수가 로그인을 끊은 뒤(`reverify_after`)에 인증한 로그인이어야 한다.
    """
    now = request.app.state.clock.now()
    login = current_login(db, request.cookies.get(LOGIN_COOKIE), request.cookies.get(DEVICE_COOKIE), now)
    if login is None:
        return None, None, "login"
    entry = find_live_by_email(db, classroom_id, student_login.account_email(db, login.account_id))
    if entry is None:
        return login, None, "not_on_roster"
    existing = identity.find_membership(db, classroom_id, login.account_id)
    if existing and existing.reverify_after and login.created_at <= existing.reverify_after:
        return login, entry, "login"  # 끊긴 뒤에는 이메일 인증부터 다시 한다(AC20)
    return login, entry, "ok"


def entered_membership(request: HTTPConnection, db: sqlite3.Connection, classroom_id: int) -> int | None:
    """이 기기로 이 강좌에 입장한 학생의 멤버십 번호. 아니면 None. 아무것도 만들지 않는다."""
    login, _, status = fresh_login(request, db, classroom_id)
    if status != "ok":
        return None
    membership = identity.find_membership(db, classroom_id, login.account_id)
    if membership is None or student_login.verified_at(db, login.id, classroom_id) is None:
        return None
    return membership.id


def class_actor(request: HTTPConnection, db: sqlite3.Connection, classroom: ClassroomRef) -> Actor:
    professor = get_actor(request, db)
    if professor.kind == "professor":
        return professor
    membership_id = entered_membership(request, db, classroom.id)
    if membership_id is not None:
        return Actor.student(membership_id=membership_id, classroom_id=classroom.id)
    now = request.app.state.clock.now()
    if current_login(db, request.cookies.get(LOGIN_COOKIE), request.cookies.get(DEVICE_COOKIE), now):
        # 로그인한 학생이지만 이 강좌에는 입장하지 않았다: "입장한 학생만 볼 수 있습니다"(403)로 알린다
        return Actor("student")
    return Actor.anonymous()


NOT_FOUND = "찾을 수 없습니다."


def guard_class(action: Action, load: Callable[..., ClassroomRef | None]) -> Callable[..., Granted]:
    """`guard`와 같지만 학생도 알아본다. HTTP와 WebSocket 연결 모두에 건다. 대상(강좌)이 없으면 404다(묶음 번호처럼 강좌 아래의 대상을 찾을 때)."""

    def check(
        request: HTTPConnection,
        db: Annotated[sqlite3.Connection, Depends(get_db)],
        classroom: Annotated[ClassroomRef | None, Depends(load)],
    ) -> Granted:
        if classroom is None:
            raise HTTPException(status_code=404, detail=NOT_FOUND)
        actor = class_actor(request, db, classroom)
        decision = decide(actor, action, classroom)
        if not decision:
            raise _deny(decision)
        return Granted(actor=actor, resource=classroom)

    check.__authz_guard__ = True  # type: ignore[attr-defined]
    check.__authz_action__ = action  # type: ignore[attr-defined]
    return check
