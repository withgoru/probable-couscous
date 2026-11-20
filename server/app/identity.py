"""멤버십(닉네임)과 사람(명단)을 잇는 `member_identities`를 읽고 쓰는 유일한 모듈(C9).

다른 모듈은 이 표를 직접 읽지 않는다. 필요한 사실(예: 명단의 누가 입장했는가)만 이 모듈에 물어본다.
이 모듈은 닉네임을 돌려주지 않는다.
"""

import sqlite3


def entered_roster_ids(db: sqlite3.Connection, classroom_id: int) -> set[int]:
    """이 강좌에서 이미 입장한(멤버십과 이어진) 명단 항목의 번호."""
    rows = db.execute(
        "SELECT roster_entry_id FROM member_identities WHERE classroom_id = ?", (classroom_id,)
    ).fetchall()
    return {r["roster_entry_id"] for r in rows}
