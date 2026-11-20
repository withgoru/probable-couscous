"""멤버십(닉네임)과 사람(명단)을 잇는 `member_identities`를 읽고 쓰는 유일한 모듈(C9).

다른 모듈은 이 표를 직접 읽지 않는다. 필요한 사실(예: 명단의 누가 입장했는가)만 이 모듈에 물어본다.
교수 화면에 쓰는 조회는 닉네임과 이름·이메일을 함께 돌려주지 않는다. 학생 본인에게는 본인 닉네임만 알려 준다(입장 화면).
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from app.nicknames import new_nickname


def entered_roster_ids(db: sqlite3.Connection, classroom_id: int) -> set[int]:
    """이 강좌에서 이미 입장한(멤버십과 이어진) 명단 항목의 번호."""
    rows = db.execute(
        "SELECT roster_entry_id FROM member_identities WHERE classroom_id = ?", (classroom_id,)
    ).fetchall()
    return {r["roster_entry_id"] for r in rows}


@dataclass(frozen=True)
class Membership:
    id: int
    nickname: str
    is_new: bool


def get_or_create_account(db: sqlite3.Connection, email_norm: str, now: datetime) -> int:
    """이메일의 계정. 강좌를 넘나드는 계정층이라 이메일마다 하나다. 호출하는 쪽이 연 쓰기 트랜잭션 안에서 부른다."""
    db.execute("INSERT OR IGNORE INTO accounts(email_norm, created_at) VALUES (?, ?)", (email_norm, now.isoformat()))
    return db.execute("SELECT id FROM accounts WHERE email_norm = ?", (email_norm,)).fetchone()["id"]


def membership_for(
    db: sqlite3.Connection, classroom_id: int, account_id: int, roster_entry_id: int, now: datetime
) -> Membership:
    """이 강좌에서 이 계정의 멤버십. 있으면 그대로(닉네임도 같다), 없으면 새 닉네임으로 만들어 명단과 잇는다.

    명단에서 빼고 다시 넣어 명단 항목이 바뀌었으면 지금의 항목으로 이어 준다. 호출하는 쪽이 연 쓰기 트랜잭션 안에서 부른다.
    """
    row = db.execute(
        "SELECT i.membership_id, i.roster_entry_id, m.nickname FROM member_identities i "
        "JOIN memberships m ON m.id = i.membership_id WHERE i.classroom_id = ? AND i.account_id = ?",
        (classroom_id, account_id),
    ).fetchone()
    if row is not None:
        if row["roster_entry_id"] != roster_entry_id:
            db.execute(
                "UPDATE member_identities SET roster_entry_id = ? WHERE membership_id = ?",
                (roster_entry_id, row["membership_id"]),
            )
        return Membership(row["membership_id"], row["nickname"], False)
    nickname = new_nickname(db, classroom_id)
    membership_id = db.execute(
        "INSERT INTO memberships(classroom_id, nickname, created_at) VALUES (?, ?, ?)",
        (classroom_id, nickname, now.isoformat()),
    ).lastrowid
    db.execute(
        "INSERT INTO member_identities(membership_id, classroom_id, account_id, roster_entry_id) VALUES (?, ?, ?, ?)",
        (membership_id, classroom_id, account_id, roster_entry_id),
    )
    return Membership(membership_id, nickname, True)
