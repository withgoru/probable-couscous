"""회차의 슬라이드 묶음 올리기·바꾸기·지우기(002 AC5~AC7, 오류 동작 "올리기 실패").

본문은 zip 파일 그대로이고 파일 이름은 `filename` 질의 값이다(001의 CSV 올리기와 같은 방식). 권한과 회차 상태를 먼저
보고, 통과한 뒤에만 본문을 임시 파일로 받는다. 받은 크기가 상한을 넘으면 그 자리에서 멈춘다.

저장 순서(반쯤 올라간 묶음은 쓰이지 않는다)
1. 묶음 번호를 얻으려고 '지운 상태'의 행을 먼저 넣는다(아무 화면에도 보이지 않는다).
2. 파일을 검사하고 풀어 둔다(`DeckStore.install`). DB 잠금은 잡지 않는다.
3. 한 트랜잭션에서 이전 묶음을 지운 상태로 만들고 새 행을 살린다. 기록을 남긴다.
4. 이전 묶음 파일을 지운다. 어느 단계든 실패하면 새 행과 새 파일을 지우고 이전 묶음은 그대로 둔다.
"""

import contextlib
import logging
import sqlite3
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated

import anyio
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from app.authz import Action, Granted, guard
from app.classrooms import load_classroom
from app.clock import Clock
from app.db import get_db, transaction
from app.deck_store import DeckError, DeckStore
from app.events import record_event
from app.sessions import ManageGuard, StoreDep, deck_item, load_session

log = logging.getLogger(__name__)
router = APIRouter()

LIVE = "수업 중에는 슬라이드를 바꿀 수 없습니다."
NO_DECK = "이 회차에 올린 슬라이드가 없습니다."
SAVE_FAILED = "올리지 못했습니다. 다시 올려 주세요."
NAME_MAX = 120
DEFAULT_NAME = "slides.zip"
MB = 1024 * 1024

Db = Annotated[sqlite3.Connection, Depends(get_db)]


def _clock(request: Request) -> Clock:
    return request.app.state.clock


ClockDep = Annotated[Clock, Depends(_clock)]


def too_big_message(limit: int) -> str:
    size = f"{limit // MB}MB" if limit % MB == 0 else f"{limit}바이트"
    return f"파일이 너무 큽니다. {size} 이하로 올려 주세요."


def clean_filename(raw: str | None) -> str:
    """화면에 보일 파일 이름. 폴더 부분을 빼고 길이를 줄인다. 저장 경로에는 쓰지 않는다."""
    name = (raw or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not name:
        return DEFAULT_NAME
    if len(name) > NAME_MAX:
        suffix = ".zip" if name.lower().endswith(".zip") else ""
        name = name[: NAME_MAX - len(suffix)].rstrip() + suffix
    return name


def editable_session(session_id: int, granted: ManageGuard, db: Db) -> sqlite3.Row:
    """경로의 강좌에 있고 진행 중이 아닌 회차(AC7). 본문을 받기 전에 확인한다."""
    row = load_session(db, granted.resource.id, session_id)
    if row["status"] == "live":
        raise HTTPException(status_code=409, detail=LIVE)
    return row


EditableSession = Annotated[sqlite3.Row, Depends(editable_session)]


async def zip_upload(request: Request, store: StoreDep, _: EditableSession) -> AsyncIterator[tuple[Path, int]]:
    """본문을 임시 파일로 받는다. 상한을 넘으면 413. 요청이 끝나면 임시 파일을 지운다."""
    limit = request.app.state.settings.deck_max_bytes
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise HTTPException(status_code=413, detail=too_big_message(limit))
    folder = store.root / ".uploads"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{uuid.uuid4().hex}.zip"
    size = 0
    try:
        async with await anyio.open_file(path, "wb") as out:
            async for chunk in request.stream():
                size += len(chunk)
                if size > limit:
                    raise HTTPException(status_code=413, detail=too_big_message(limit))
                await out.write(chunk)
        yield path, size
    finally:
        path.unlink(missing_ok=True)
        with contextlib.suppress(OSError):
            folder.rmdir()


Upload = Annotated[tuple[Path, int], Depends(zip_upload)]


def live_deck(db: sqlite3.Connection, classroom_id: int, session_id: int) -> sqlite3.Row | None:
    return db.execute(
        "SELECT * FROM decks WHERE session_id = ? AND classroom_id = ? AND removed_at IS NULL",
        (session_id, classroom_id),
    ).fetchone()


def _record(db, granted: Granted, type: str, session_id: int, deck_id: int, clock: Clock) -> None:
    payload = {"session_id": session_id, "deck_id": deck_id}
    record_event(db, granted.resource.id, type, "professor", granted.actor.github_id, None, payload, clock.now())


@router.put("/api/classrooms/{classroom_id}/sessions/{session_id}/deck")
def upload_deck(
    session_id: int,
    granted: ManageGuard,
    session: EditableSession,
    upload: Upload,
    db: Db,
    clock: ClockDep,
    store: StoreDep,
    filename: str | None = None,
):
    classroom_id = granted.resource.id
    zip_path, size = upload
    now = clock.now().isoformat()
    with transaction(db):  # 1. 번호 얻기(지운 상태라 보이지 않는다)
        deck_id = db.execute(
            "INSERT INTO decks(classroom_id, session_id, original_name, slide_count, size_bytes, uploaded_at, "
            "removed_at) VALUES (?, ?, ?, 1, ?, ?, ?)",
            (classroom_id, session_id, clean_filename(filename), size, now, now),
        ).lastrowid
    old = None
    try:
        meta = store.install(classroom_id, deck_id, zip_path)  # 2. 검사하고 풀기
        with transaction(db):  # 3. 바꾸기
            if load_session(db, classroom_id, session_id)["status"] == "live":
                raise HTTPException(status_code=409, detail=LIVE)
            old = live_deck(db, classroom_id, session_id)
            if old is not None:
                db.execute("UPDATE decks SET removed_at = ? WHERE id = ?", (now, old["id"]))
            db.execute(
                "UPDATE decks SET slide_count = ?, removed_at = NULL WHERE id = ?", (meta.slide_count, deck_id)
            )
            _record(db, granted, "deck_uploaded", session_id, deck_id, clock)
    except BaseException as err:
        _discard(db, store, classroom_id, deck_id)
        if isinstance(err, DeckError):
            raise HTTPException(status_code=422, detail=str(err)) from None
        if isinstance(err, HTTPException):
            raise
        log.exception("슬라이드 묶음을 저장하지 못했습니다(강좌 %s, 회차 %s)", classroom_id, session_id)
        raise HTTPException(status_code=500, detail=SAVE_FAILED) from None
    if old is not None:  # 4. 이전 파일 지우기
        store.remove(classroom_id, old["id"])
    row = db.execute("SELECT * FROM decks WHERE id = ?", (deck_id,)).fetchone()
    return {"deck": deck_item(row, deck_id, store.exists(classroom_id, deck_id))}


def _discard(db: sqlite3.Connection, store: DeckStore, classroom_id: int, deck_id: int) -> None:
    """실패한 올리기의 행과 파일을 지운다. 이전 묶음은 건드리지 않는다."""
    store.remove(classroom_id, deck_id)
    with transaction(db):
        db.execute("DELETE FROM decks WHERE id = ? AND removed_at IS NOT NULL", (deck_id,))


@router.delete("/api/classrooms/{classroom_id}/sessions/{session_id}/deck", status_code=204)
def remove_deck(session_id: int, granted: ManageGuard, session: EditableSession, db: Db, clock: ClockDep, store: StoreDep):
    classroom_id = granted.resource.id
    with transaction(db):
        deck = live_deck(db, classroom_id, session_id)
        if deck is None:
            raise HTTPException(status_code=404, detail=NO_DECK)
        db.execute("UPDATE decks SET removed_at = ? WHERE id = ?", (clock.now().isoformat(), deck["id"]))
        _record(db, granted, "deck_removed", session_id, deck["id"], clock)
    store.remove(classroom_id, deck["id"])
    return Response(status_code=204)


CANNOT_OPEN = "슬라이드를 열 수 없습니다. 묶음을 다시 올려 주세요."
NotesGuard = Annotated[Granted, Depends(guard(Action.DECK_NOTES, load_classroom))]


@router.get("/api/classrooms/{classroom_id}/sessions/{session_id}/deck/notes")
def deck_notes(session_id: int, granted: NotesGuard, db: Db, store: StoreDep):
    """발표자 노트(AC30). 교수 수업 화면만 부른다. 학생이 받는 파일에는 노트가 없다."""
    classroom_id = granted.resource.id
    load_session(db, classroom_id, session_id)
    deck = live_deck(db, classroom_id, session_id)
    if deck is None:
        raise HTTPException(status_code=404, detail=NO_DECK)
    if not store.exists(classroom_id, deck["id"]):
        raise HTTPException(status_code=410, detail=CANNOT_OPEN)
    meta = store.read_meta(classroom_id, deck["id"])
    slides = [
        {"no": i + 1, "title": str(s.get("title") or ""), "note": str(s.get("note") or "")}
        for i, s in enumerate(meta.slides)
    ]
    return JSONResponse(
        {"deck_id": deck["id"], "slide_count": meta.slide_count, "slides": slides},
        headers={"Cache-Control": "no-store"},
    )

