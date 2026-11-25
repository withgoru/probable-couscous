"""수업 중 메시지·자료 보내기와 거두기(002 AC31, AC32, AC33, AC35).

- 보내기: 글(1~2000자) 또는 링크(http/https, 2000자 이하). 진행 중인 회차에만 보낸다.
- 화면이 만든 `client_key`로 두 번 저장하지 않는다. 같은 키로 다시 오면(다시 누름, 응답이 늦어 다시 보냄) 저장된 그 항목을
  그대로 돌려준다. 수업이 그 사이 끝났어도 같다.
- 거두기: `retracted_at`만 쓰고 원문은 남긴다(C6). 되살리는 길은 없다. 이미 거둔 항목은 그대로 돌려준다.
- 바뀔 때마다 회차 `version`을 1 올리고, 기록과 함께 커밋한 **뒤에** 수업 방에 발행한다(C13).
- 기록(`item_sent`, `item_retracted`)에는 회차·항목 번호만 넣는다. 본문은 `session_items`에 있다.

권한은 `session.present`(소유 교수, 진행 중인 강좌)다.
"""

import re
import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.authz import Action, Granted, guard
from app.classrooms import load_classroom
from app.db import get_db, transaction
from app.events import record_event
from app.realtime import publish_class

router = APIRouter()

TEXT_MAX = 2000
URL_MAX = 2000
EMPTY = "글이나 링크를 입력해 주세요."
TEXT_TOO_LONG = f"글은 {TEXT_MAX}자 이하로 입력해 주세요."
BAD_LINK = "링크는 http:// 또는 https://로 시작해야 합니다."
LINK_TOO_LONG = f"링크는 {URL_MAX}자 이하로 입력해 주세요."
BAD_KEY = "보내기 요청이 올바르지 않습니다. 화면을 새로 고쳐 주세요."
NOT_LIVE = "진행 중인 수업에만 보낼 수 있습니다."
SESSION_NOT_FOUND = "찾을 수 없는 회차입니다."
ITEM_NOT_FOUND = "찾을 수 없는 항목입니다."

LINK = re.compile(r"https?://\S+", re.IGNORECASE)
CLIENT_KEY = re.compile(r"[A-Za-z0-9_-]{1,64}")

Db = Annotated[sqlite3.Connection, Depends(get_db)]
PresentGuard = Annotated[Granted, Depends(guard(Action.SESSION_PRESENT, load_classroom))]

_ITEM_COLUMNS = "id, body, url, created_at, retracted_at"


class NewItem(BaseModel):
    # 형식 검사는 직접 해서 어느 칸이 왜 잘못인지 한국어로 알린다
    body: object = None
    url: object = None
    client_key: object = None


def _invalid(field: str | None, message: str, status: int = 422) -> HTTPException:
    return HTTPException(status_code=status, detail={"field": field, "message": message})


def clean_item(item: NewItem) -> tuple[str | None, str | None, str]:
    """(글, 링크, client_key). 빈 칸은 None이다. 글은 교수가 쓴 그대로 둔다(줄바꿈, 들여쓰기)."""
    if not isinstance(item.client_key, str) or not CLIENT_KEY.fullmatch(item.client_key):
        raise _invalid(None, BAD_KEY)
    if item.body is not None and not isinstance(item.body, str):
        raise _invalid("body", TEXT_TOO_LONG)
    body = item.body if isinstance(item.body, str) and item.body.strip() else None
    if body is not None and len(body) > TEXT_MAX:
        raise _invalid("body", TEXT_TOO_LONG)
    if item.url is not None and not isinstance(item.url, str):
        raise _invalid("url", BAD_LINK)
    url = item.url.strip() if isinstance(item.url, str) and item.url.strip() else None
    if url is not None:
        if len(url) > URL_MAX:
            raise _invalid("url", LINK_TOO_LONG)
        if not LINK.fullmatch(url):
            raise _invalid("url", BAD_LINK)
    if body is None and url is None:
        raise _invalid(None, EMPTY)
    return body, url, item.client_key


def _item(row: sqlite3.Row) -> dict:
    return {k: row[k] for k in ("id", "body", "url", "created_at", "retracted_at")}


def _bump(db: sqlite3.Connection, classroom_id: int, session_id: int) -> int:
    db.execute(
        "UPDATE class_sessions SET version = version + 1 WHERE id = ? AND classroom_id = ?", (session_id, classroom_id)
    )
    return _version(db, classroom_id, session_id)


def _version(db: sqlite3.Connection, classroom_id: int, session_id: int) -> int:
    return db.execute(
        "SELECT version FROM class_sessions WHERE id = ? AND classroom_id = ?", (session_id, classroom_id)
    ).fetchone()["version"]


def _record(db: sqlite3.Connection, granted: Granted, type_: str, session_id: int, item_id: int, request: Request):
    record_event(
        db, granted.resource.id, type_, "professor", granted.actor.github_id, None,
        {"session_id": session_id, "item_id": item_id}, request.app.state.clock.now(),
    )


_BASE = "/api/classrooms/{classroom_id}/sessions/{session_id}/items"


@router.post(_BASE, status_code=201)
def send_item(session_id: int, payload: NewItem, granted: PresentGuard, db: Db, request: Request):
    body, url, key = clean_item(payload)
    classroom_id = granted.resource.id
    created = False
    with transaction(db):
        session = db.execute(
            "SELECT status FROM class_sessions WHERE id = ? AND classroom_id = ?", (session_id, classroom_id)
        ).fetchone()
        if session is None:
            raise HTTPException(status_code=404, detail=SESSION_NOT_FOUND)
        row = db.execute(
            f"SELECT {_ITEM_COLUMNS} FROM session_items WHERE session_id = ? AND classroom_id = ? AND client_key = ?",
            (session_id, classroom_id, key),
        ).fetchone()
        if row is None:  # 처음 온 요청이다
            if session["status"] != "live":
                raise _invalid(None, NOT_LIVE, status=409)
            cursor = db.execute(
                "INSERT INTO session_items(classroom_id, session_id, body, url, client_key, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (classroom_id, session_id, body, url, key, request.app.state.clock.now().isoformat()),
            )
            _record(db, granted, "item_sent", session_id, cursor.lastrowid, request)
            version = _bump(db, classroom_id, session_id)
            row = db.execute(f"SELECT {_ITEM_COLUMNS} FROM session_items WHERE id = ?", (cursor.lastrowid,)).fetchone()
            created = True
        else:
            version = _version(db, classroom_id, session_id)
    item = _item(row)
    if created:
        student_view = {k: item[k] for k in ("id", "body", "url", "created_at")}
        publish_class(request, classroom_id, "item.created", session_id=session_id, item=student_view, version=version)
    return JSONResponse(status_code=201, content={"item": item, "version": version})


@router.post(_BASE + "/{item_id}/retract")
def retract_item(session_id: int, item_id: int, granted: PresentGuard, db: Db, request: Request):
    classroom_id = granted.resource.id
    changed = False
    with transaction(db):
        row = db.execute(
            f"SELECT {_ITEM_COLUMNS} FROM session_items WHERE id = ? AND session_id = ? AND classroom_id = ?",
            (item_id, session_id, classroom_id),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=ITEM_NOT_FOUND)
        if row["retracted_at"] is None:
            db.execute(
                "UPDATE session_items SET retracted_at = ? WHERE id = ? AND classroom_id = ?",
                (request.app.state.clock.now().isoformat(), item_id, classroom_id),
            )
            _record(db, granted, "item_retracted", session_id, item_id, request)
            version = _bump(db, classroom_id, session_id)
            row = db.execute(f"SELECT {_ITEM_COLUMNS} FROM session_items WHERE id = ?", (item_id,)).fetchone()
            changed = True
        else:
            version = _version(db, classroom_id, session_id)
    if changed:
        publish_class(request, classroom_id, "item.retracted", session_id=session_id, item_id=item_id, version=version)
    return {"item": _item(row), "version": version}
