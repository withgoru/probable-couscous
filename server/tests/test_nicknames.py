"""AC29의 규칙(C7): 강좌 안에서 겹치지 않는 닉네임을 무작위로 뽑는다. 닉네임은 단어 목록에서만 나오고 개인정보가 없다."""

import random
import re

import pytest

from app import nicknames
from app.nickname_words import ADJECTIVES, NOUNS
from app.nicknames import NicknamesExhausted, generate_nickname, new_nickname

NOW = "2026-03-01T09:00:00+00:00"
HANGUL = re.compile(r"^[가-힣]+$")


# --- 단어 목록 (사용자가 검토한다) ----------------------------------------------------


def test_word_lists_are_clean_hangul_words_without_duplicates():
    for words in (ADJECTIVES, NOUNS):
        assert len(words) == len(set(words)), "중복된 단어"
        assert all(HANGUL.match(w) for w in words), [w for w in words if not HANGUL.match(w)]
    assert not set(ADJECTIVES) & set(NOUNS)


def test_words_are_short_enough_to_read_in_a_chat_line():
    assert all(2 <= len(w) <= 5 for w in ADJECTIVES), [w for w in ADJECTIVES if not 2 <= len(w) <= 5]
    assert all(2 <= len(w) <= 4 for w in NOUNS), [w for w in NOUNS if not 2 <= len(w) <= 4]


def test_there_are_far_more_combinations_than_a_classroom_needs():
    # 한 강좌는 200명까지다. 겹쳐서 다시 뽑는 일이 드물도록 열 배 넘게 있어야 한다
    assert len(ADJECTIVES) * len(NOUNS) >= 2000


# --- 생성 ------------------------------------------------------------------------------


def test_a_nickname_is_an_adjective_and_a_noun_with_one_space():
    for _ in range(200):
        adjective, noun = generate_nickname(set()).split(" ")
        assert adjective in ADJECTIVES and noun in NOUNS


def test_every_word_can_come_up(monkeypatch):
    seen_adjectives, seen_nouns = set(), set()
    for _ in range(4000):
        a, n = generate_nickname(set()).split(" ")
        seen_adjectives.add(a)
        seen_nouns.add(n)
    assert seen_adjectives == set(ADJECTIVES) and seen_nouns == set(NOUNS)


def test_two_hundred_students_in_one_classroom_all_get_different_nicknames():
    taken: set[str] = set()
    for _ in range(200):
        name = generate_nickname(taken)
        assert name not in taken
        taken.add(name)
    assert len(taken) == 200


def test_a_collision_is_redrawn_and_the_taken_name_is_never_returned():
    class Scripted(random.Random):
        def __init__(self, picks):
            super().__init__()
            self.picks = list(picks)
            self.draws = 0

        def choice(self, seq):
            self.draws += 1
            return seq[self.picks.pop(0) % len(seq)]

    first = f"{ADJECTIVES[0]} {NOUNS[0]}"
    rng = Scripted([0, 0, 1, 1])  # 첫 뽑기(0,0)는 이미 쓰는 이름, 다음(1,1)은 비어 있다
    got = generate_nickname({first}, rng=rng)
    assert got == f"{ADJECTIVES[1]} {NOUNS[1]}"
    assert rng.draws == 4  # 한 번 뽑을 때 형용사와 명사를 하나씩, 두 번 뽑았다


def test_when_random_draws_keep_colliding_it_still_finds_a_free_name(monkeypatch):
    # 거의 다 찼을 때도 무작위로 계속 부딪히지 않고, 남은 조합 중에서 고른다
    monkeypatch.setattr(nicknames, "ADJECTIVES", ("가나", "다라"))
    monkeypatch.setattr(nicknames, "NOUNS", ("마바", "사아"))
    all_names = {f"{a} {n}" for a in nicknames.ADJECTIVES for n in nicknames.NOUNS}
    free = "다라 사아"
    for _ in range(50):
        assert generate_nickname(all_names - {free}) == free


def test_when_every_combination_is_taken_it_says_so_instead_of_looping(monkeypatch):
    monkeypatch.setattr(nicknames, "ADJECTIVES", ("가나",))
    monkeypatch.setattr(nicknames, "NOUNS", ("마바", "사아"))
    with pytest.raises(NicknamesExhausted) as err:
        generate_nickname({"가나 마바", "가나 사아"})
    assert "닉네임" in str(err.value)


def test_the_taken_set_is_not_changed(monkeypatch):
    taken = {"가나 마바"}
    generate_nickname(taken)
    assert taken == {"가나 마바"}


# --- 강좌마다 독립 (DB) ---------------------------------------------------------------------


def make_classroom(world, owner="kim"):
    from conftest import ORIGIN

    client = world.client(owner)
    return client.post("/api/classrooms", json={"name": "웹"}, headers=ORIGIN).json()["id"]


def add_member(db, classroom_id, nickname):
    db.execute(
        "INSERT INTO memberships(classroom_id, nickname, created_at) VALUES (?, ?, ?)",
        (classroom_id, nickname, NOW),
    )


def test_new_nickname_avoids_the_names_already_in_that_classroom(world, monkeypatch):
    cid = make_classroom(world)
    db = world.db()
    monkeypatch.setattr(nicknames, "ADJECTIVES", ("가나", "다라"))
    monkeypatch.setattr(nicknames, "NOUNS", ("마바", "사아"))
    names = set()
    for _ in range(4):
        n = new_nickname(db, cid)
        assert n not in names
        names.add(n)
        add_member(db, cid, n)
    assert len(names) == 4
    with pytest.raises(NicknamesExhausted):
        new_nickname(db, cid)


def test_two_hundred_students_fill_a_classroom_without_a_duplicate(world):
    cid = make_classroom(world)
    db = world.db()
    for _ in range(200):
        add_member(db, cid, new_nickname(db, cid))  # 겹치면 표의 고유 조건이 오류를 낸다
    assert db.execute("SELECT COUNT(DISTINCT nickname) FROM memberships").fetchone()[0] == 200


def test_classrooms_are_independent_the_same_name_may_appear_in_two_classrooms(world, monkeypatch):
    # 강좌를 가로질러 닉네임을 맞춰 보지 않는다. 같은 학생의 강좌별 닉네임이 서로 이어지지 않게 하려는 것(C7)이다
    a = make_classroom(world)
    b = make_classroom(world, "lee")
    db = world.db()
    monkeypatch.setattr(nicknames, "ADJECTIVES", ("가나",))
    monkeypatch.setattr(nicknames, "NOUNS", ("마바",))
    add_member(db, a, new_nickname(db, a))
    assert new_nickname(db, b) == "가나 마바"  # 다른 강좌에서 쓰는 이름은 막지 않는다


def test_new_nickname_reads_only_the_memberships_of_the_classroom_asked(world, monkeypatch):
    a = make_classroom(world)
    b = make_classroom(world, "lee")
    db = world.db()
    monkeypatch.setattr(nicknames, "ADJECTIVES", ("가나",))
    monkeypatch.setattr(nicknames, "NOUNS", ("마바", "사아"))
    add_member(db, a, "가나 마바")
    add_member(db, b, "가나 사아")
    assert new_nickname(db, a) == "가나 사아"
    assert new_nickname(db, b) == "가나 마바"


@pytest.mark.constitution
def test_c7_the_nickname_module_never_touches_personal_data():
    from pathlib import Path

    text = (Path(nicknames.__file__).read_text() + Path(nicknames.__file__).with_name("nickname_words.py").read_text())
    for forbidden in ("email", "roster_entries", "accounts", "member_identities", "student_no"):
        assert forbidden not in text, f"닉네임 모듈이 {forbidden}를 건드린다"


def test_the_default_source_is_the_operating_systems_randomness():
    # 서버를 다시 시작해도 같은 순서로 같은 이름이 나오지 않게(씨앗이 정해진 난수를 쓰지 않는다)
    assert isinstance(nicknames._SYSTEM, random.SystemRandom)
