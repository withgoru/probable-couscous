"""슬라이드 묶음 파일 내려주기 `/decks/{묶음}/…`(002 AC30, AC44, plan 위험 6·9).

- 그 강좌의 교수와, 그 강좌에 입장한 학생만 받는다(`class.view`, `guard_class`).
- 노트 파일(`classroom-deck.json`)은 누구에게도 내려주지 않는다. 노트는 교수 전용 API로만 나간다.
- 지운 묶음(바꾸기로 밀려난 것 포함)과 없는 묶음은 404, 기록은 있는데 파일이 없으면 410이다.
- 해시가 붙은 파일은 내용이 바뀌지 않으니 1년 캐시하고, `index.html` 등은 매번 확인한다. 로그인한 사람만 받는
  파일이라 공유 캐시에는 두지 않는다(`private`). 다른 사이트가 iframe으로 얹지 못한다.
"""

import re
import sqlite3
from pathlib import Path, PurePosixPath
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from app.authz import Action, ClassroomRef, Granted
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
def deck_file(deck_id: int, path: str, granted: ViewGuard, request: Request):
    store: DeckStore = request.app.state.deck_store
    classroom_id = granted.resource.id
    if not store.exists(classroom_id, deck_id):
        raise HTTPException(status_code=410, detail=CANNOT_OPEN)
    target = _safe_target(store.path_for(classroom_id, deck_id), path)
    if target is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    cache = LONG_CACHE if HASHED.search(target.name) else NO_CACHE
    return FileResponse(target, headers={"Cache-Control": cache, **SECURITY})
