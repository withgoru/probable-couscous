"""T001: 서버 테스트가 쓰는 테스트용 슬라이드 묶음이 템플릿(`slides-template/`)의 약속을 지키는지 본다.

- 빌드는 고정 기준 경로 `/__deck__/`로 되어 있어 서버가 올릴 때 묶음별 경로로 바꿀 수 있다(plan 기술 선택).
- `classroom-deck.json`에 슬라이드 수와 슬라이드별 제목·노트가 있고, 빌드 파일에는 노트가 없다(AC30).
- 빌드 파일은 외부 주소를 부르지 않는다(학생 IP가 밖으로 나가지 않고, 교실 인터넷이 없어도 열린다).
"""

import json
import zipfile
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "deck-small.zip"
SENTINEL = "/__deck__/"
META = "classroom-deck.json"
TEXT_SUFFIXES = (".html", ".js", ".css", ".json")
EXTERNAL_HOSTS = ("fonts.googleapis.com", "fonts.gstatic.com", "cdn.jsdelivr.net", "unpkg.com")


@pytest.fixture(scope="module")
def deck() -> dict[str, bytes]:
    assert FIXTURE.is_file(), (
        "테스트용 묶음이 없습니다. slides-template에서 npm run build:fixture를 실행하세요."
    )
    with zipfile.ZipFile(FIXTURE) as zf:
        return {info.filename: zf.read(info) for info in zf.infolist() if not info.is_dir()}


def built_texts(deck: dict[str, bytes]) -> dict[str, str]:
    return {
        name: data.decode("utf-8")
        for name, data in deck.items()
        if name != META and name.endswith(TEXT_SUFFIXES)
    }


def test_index_is_at_the_root_and_uses_the_fixed_base(deck):
    assert "index.html" in deck
    assert SENTINEL + "assets/" in deck["index.html"].decode("utf-8")
    assert any(name.startswith("assets/") and name.endswith(".js") for name in deck)


def test_meta_lists_every_slide_with_title_and_note(deck):
    meta = json.loads(deck[META])
    assert meta["format"] == 1
    assert meta["slide_count"] == 4
    assert [s["no"] for s in meta["slides"]] == [1, 2, 3, 4]
    assert meta["slides"][1]["title"] == "2. 단계 세 개"
    assert meta["slides"][1]["note"].startswith("노트 2")
    assert meta["slides"][2]["note"] == ""


def test_notes_are_only_in_the_meta_file(deck):
    notes = [s["note"] for s in json.loads(deck[META])["slides"] if s["note"]]
    assert notes
    for name, text in built_texts(deck).items():
        for note in notes:
            assert note not in text, f"{name}에 발표자 노트가 들어 있습니다"


def test_build_does_not_call_external_hosts(deck):
    for name, text in built_texts(deck).items():
        for host in EXTERNAL_HOSTS:
            assert host not in text, f"{name}이 외부 주소 {host}를 부릅니다"


def test_build_has_the_sync_bridge(deck):
    # 동기화 애드온이 들어간 빌드인지: 다리 메시지 이름이 JS 안에 있다
    js = "".join(text for name, text in built_texts(deck).items() if name.endswith(".js"))
    for message in (
        "deck:ready",
        "deck:goto",
        "deck:limit",
        "deck:mode",
        "deck:moved",
        "deck:intent",
    ):
        assert message in js, f"{message}가 빌드에 없습니다"
