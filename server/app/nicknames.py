"""강좌 안에서 겹치지 않는 닉네임을 뽑는다(AC29, C7).

닉네임은 단어 목록(`nickname_words`)에서 무작위로 조합한다. 개인정보를 읽지 않으며, 같은 강좌의 멤버십 표에서
이미 쓰는 닉네임만 본다. 강좌 사이에는 서로 맞춰 보지 않는다. 같은 학생이 강좌마다 받는 닉네임이 서로
이어지지 않게 하려는 것이라, 우연히 같은 이름이 두 강좌에 나올 수 있다.
"""

import random
import sqlite3
from collections.abc import Collection

from app.nickname_words import ADJECTIVES, NOUNS

_SYSTEM = random.SystemRandom()
# 무작위로 다시 뽑는 횟수. 200명 안에서는 거의 첫 번째에 끝난다. 넘으면 남은 조합에서 직접 고른다
DRAWS = 20


class NicknamesExhausted(Exception):
    """이 강좌에서 만들 수 있는 닉네임이 모두 쓰였다."""

    def __init__(self) -> None:
        super().__init__("만들 수 있는 닉네임을 모두 사용했습니다. 단어 목록을 늘려야 합니다.")


def generate_nickname(taken: Collection[str], rng: random.Random = _SYSTEM) -> str:
    """taken에 없는 닉네임 하나. taken은 바꾸지 않는다."""
    for _ in range(DRAWS):
        name = f"{rng.choice(ADJECTIVES)} {rng.choice(NOUNS)}"
        if name not in taken:
            return name
    # 거의 다 찬 강좌: 계속 부딪히지 않고 남은 조합에서 고른다
    free = [f"{a} {n}" for a in ADJECTIVES for n in NOUNS if f"{a} {n}" not in taken]
    if not free:
        raise NicknamesExhausted
    return rng.choice(free)


def new_nickname(db: sqlite3.Connection, classroom_id: int, rng: random.Random = _SYSTEM) -> str:
    """이 강좌의 멤버십에 아직 없는 닉네임. 멤버십을 만드는 같은 쓰기 트랜잭션 안에서 부른다."""
    rows = db.execute("SELECT nickname FROM memberships WHERE classroom_id = ?", (classroom_id,)).fetchall()
    return generate_nickname({r["nickname"] for r in rows}, rng)
