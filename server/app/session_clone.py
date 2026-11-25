"""복제할 때 회차와 슬라이드 묶음을 새 강좌로 복사한다(002 AC42, C5).

회차는 같은 이름·순서로 '예정' 상태가 된다. 위치, 시작·종료 시각, 보낸 항목은 복사하지 않는다.
살아 있는 묶음은 새 강좌의 새 번호로 생기고 파일은 `DeckStore.copy`가 둔다. 파일이 사라진 원본 묶음은 건너뛴다
(회차는 묶음 없이 생기고, 교수가 다시 올리면 된다). 묶음의 원래 파일 이름·크기·올린 시각은 그대로다.

001 `classrooms`의 복제가 강좌를 만든 쓰기 트랜잭션 안에서 부른다. 실패하면 그 트랜잭션이 되돌려지고,
이미 둔 파일은 부른 쪽이 `copied`로 지운다.
"""

import sqlite3

from app.deck_store import DeckStore

_SOURCE_SQL = """
SELECT s.id, s.title, s.sort_order,
       d.id AS deck_id, d.original_name, d.slide_count, d.size_bytes, d.uploaded_at
  FROM class_sessions s
  LEFT JOIN decks d ON d.session_id = s.id AND d.classroom_id = s.classroom_id AND d.removed_at IS NULL
 WHERE s.classroom_id = ?
 ORDER BY s.sort_order, s.id
"""


def copy_sessions(
    db: sqlite3.Connection, store: DeckStore, source_id: int, classroom_id: int, now: str, copied: list[int]
) -> None:
    """원본 강좌의 회차와 묶음을 새 강좌에 만든다. 파일을 둔 묶음 번호를 `copied`에 더한다."""
    for row in db.execute(_SOURCE_SQL, (source_id,)).fetchall():
        session_id = db.execute(
            "INSERT INTO class_sessions(classroom_id, title, sort_order, created_at) VALUES (?, ?, ?, ?)",
            (classroom_id, row["title"], row["sort_order"], now),
        ).lastrowid
        if row["deck_id"] is None or not store.exists(source_id, row["deck_id"]):
            continue
        deck_id = db.execute(
            "INSERT INTO decks(classroom_id, session_id, original_name, slide_count, size_bytes, uploaded_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (classroom_id, session_id, row["original_name"], row["slide_count"], row["size_bytes"], row["uploaded_at"]),
        ).lastrowid
        copied.append(deck_id)
        store.copy(source_id, row["deck_id"], classroom_id, deck_id)
