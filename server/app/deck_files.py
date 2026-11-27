"""슬라이드 묶음 파일 내려주기 `/decks/{묶음}/…`(002 AC30, AC44, plan 위험 6·9).

- 그 강좌의 교수와, 그 강좌에 입장한 학생만 받는다(`class.view`, `guard_class`).
- 학생은 공개 묶음이거나, 진행 중인 회차의 지금 묶음일 때만 받는다(AC50). 비공개 묶음은 수업 중 따라가기 밖에서
  내주지 않는다. 막을 때는 없는 묶음과 같은 404다(어떤 묶음이 있는지 알리지 않는다). 교수와 프로젝터는 늘 받는다.
- 노트 파일(`classroom-deck.json`)은 누구에게도 내려주지 않는다. 노트는 교수 전용 API로만 나간다.
- 지운 묶음(바꾸기로 밀려난 것 포함)과 없는 묶음은 404, 기록은 있는데 파일이 없으면 410이다.
- 해시가 붙은 파일은 내용이 바뀌지 않으니 1년 캐시하고, `index.html` 등은 매번 확인한다. 로그인한 사람만 받는
  파일이라 공유 캐시에는 두지 않는다(`private`). 다른 사이트가 iframe으로 얹지 못한다.
- 학생에게 비공개 묶음은 해시 파일도 매번 확인한다(`no-cache`). 수업 중에 받은 비공개 묶음 파일이 1년 캐시에 남아
  수업 뒤 주소로 바로 열리지 않게 한다. 공개 묶음은 학생도 해시 파일을 오래 캐시한다(대기 화면에서 미리 받아 수업 시작의
  몰림을 줄인다, T038). 첫 화면(index.html)은 누구나 매번 확인한다.
"""

import re
import sqlite3
from pathlib import Path, PurePosixPath
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from app.authz import Action, ClassroomRef, Granted
from app.class_access import NOT_FOUND as NO_SUCH_DECK
from app.class_access import guard_class
from app.db import get_db
from app.deck_store import META_NAME, DeckStore

router = APIRouter()

NOT_FOUND = "찾을 수 없는 슬라이드입니다."
CANNOT_OPEN = "슬라이드를 열 수 없습니다. 묶음을 다시 올려 주세요."
HASHED = re.compile(r"-[\w-]{8,}\.[A-Za-z0-9]+$")  # Vite가 내용 해시를 붙인 파일(예: index-M_OShFis.js)
LONG_CACHE = "private, max-age=31536000, immutable"
NO_CACHE = "private, no-cache"
SECURITY = {"Content-Security-Policy": "frame-ancestors 'self'", "X-Content-Type-Options": "nosniff"}

Db = Annotated[sqlite3.Connection, Depends(get_db)]


def load_deck_classroom(deck_id: int, db: Db) -> ClassroomRef | None:
    """살아 있는 묶음이 속한 강좌. 지웠거나 없으면 None(→ 404)."""
    row = db.execute(
        "SELECT c.id, c.owner_github_id, c.status FROM decks d JOIN classrooms c ON c.id = d.classroom_id "
        "WHERE d.id = ? AND d.removed_at IS NULL",
        (deck_id,),
    ).fetchone()
    if row is None:
        return None
    return ClassroomRef(id=row["id"], owner_github_id=row["owner_github_id"], status=row["status"])


ViewGuard = Annotated[Granted, Depends(guard_class(Action.CLASS_VIEW, load_deck_classroom))]


def _student_access(db: sqlite3.Connection, deck_id: int) -> str | None:
    """학생이 받을 수 있으면 'public'(공개 묶음) 또는 'live'(진행 중 회차의 비공개 묶음), 아니면 None(AC50).
    지운 묶음은 None이다. 비공개로 바꾸면 수업 밖에서는 바로 None이 된다."""
    row = db.execute(
        "SELECT d.public, s.status FROM decks d "
        "JOIN class_sessions s ON s.id = d.session_id AND s.classroom_id = d.classroom_id "
        "WHERE d.id = ? AND d.removed_at IS NULL",
        (deck_id,),
    ).fetchone()
    if row is None:
        return None
    if row["public"]:
        return "public"
    return "live" if row["status"] == "live" else None


def _safe_target(folder: Path, relative: str) -> Path | None:
    parts = PurePosixPath(relative).parts
    if any(part in ("..", ".") or "\\" in part for part in parts):
        return None
    if parts and parts[0] == META_NAME:
        return None  # 노트가 든 파일은 내려주지 않는다(AC30)
    target = (folder / (relative or "index.html")).resolve()  # 링크를 풀어 아래의 폴더 안 확인과 같은 기준으로 본다
    root = folder.resolve()
    if not target.is_relative_to(root) or not target.is_file():
        return None
    return target


@router.get("/decks/{deck_id}/{path:path}")
def deck_file(deck_id: int, path: str, granted: ViewGuard, request: Request, db: Db):
    store: DeckStore = request.app.state.deck_store
    classroom_id = granted.resource.id
    professor = granted.actor.kind == "professor"  # 교수와 프로젝터(교수 로그인)만 늘 받는다
    access = None if professor else _student_access(db, deck_id)
    if not professor and access is None:
        # 없거나 지운 묶음과 같은 응답. 이어서 하거나 공개한 뒤에 막힌 응답이 남지 않게 저장하지 않는다
        raise HTTPException(status_code=404, detail=NO_SUCH_DECK, headers={"Cache-Control": "no-store"})
    if not store.exists(classroom_id, deck_id):
        raise HTTPException(status_code=410, detail=CANNOT_OPEN)
    target = _safe_target(store.path_for(classroom_id, deck_id), path)
    if target is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    # 해시 파일은 내용이 바뀌지 않아 오래 캐시한다. 학생은 공개 묶음만(미리 받기, T038). 비공개 묶음은 수업 뒤 캐시로
    # 열리지 않게 매번 확인한다(T033). 첫 화면(index.html)은 누구나 매번 확인해, 비공개로 바뀌면 바로 막힌다
    long_ok = professor or access == "public"
    cache = LONG_CACHE if long_ok and HASHED.search(target.name) else NO_CACHE
    return FileResponse(target, headers={"Cache-Control": cache, **SECURITY})
