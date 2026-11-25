"""002 T005: 슬라이드 묶음 검사와 저장(`DeckStore`). AC6, plan 위험 7(위험한 zip).

- 템플릿으로 만든 묶음만 받아들인다: 맨 위에 `index.html`(기준 경로 `/__deck__/` 포함)과 `classroom-deck.json`.
- 경로 탈출, 심볼릭 링크, 압축 폭탄, 파일 수 폭증은 풀기 전에 거절한다.
- 기준 경로를 `/decks/{묶음 번호}/`로 바꿔 저장한다.
- 임시 폴더에 풀고 다 되면 이름을 바꿔 한 번에 둔다. 실패하면 아무것도 남지 않는다.
"""

import io
import json
import stat
import zipfile
from pathlib import Path

import pytest

from app.deck_store import BAD_DECK, DeckError, DeckStore

FIXTURE = Path(__file__).parent / "fixtures" / "deck-small.zip"


def fixture_entries() -> dict[str, bytes]:
    with zipfile.ZipFile(FIXTURE) as zf:
        return {i.filename: zf.read(i) for i in zf.infolist() if not i.is_dir()}


def make_zip(tmp_path: Path, entries: dict[str, bytes], name="deck.zip", symlinks=()) -> Path:
    path = tmp_path / name
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for filename, data in entries.items():
            zf.writestr(filename, data)
        for filename, target in symlinks:
            info = zipfile.ZipInfo(filename)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, target)
    return path


@pytest.fixture
def store(tmp_path):
    return DeckStore(tmp_path / "data" / "decks", max_unzipped_bytes=50_000_000, max_files=5000)


def text_files(root: Path):
    for p in root.rglob("*"):
        if p.is_file() and p.suffix in (".html", ".js", ".css", ".json"):
            yield p, p.read_text(encoding="utf-8")


# --- 받아들이기 ----------------------------------------------------------------------------


def test_installs_the_template_deck_and_rewrites_the_base(store, tmp_path):
    meta = store.install(classroom_id=3, deck_id=17, zip_path=FIXTURE)
    assert meta.slide_count == 4
    assert [s["title"] for s in meta.slides][1] == "2. 단계 세 개"
    root = store.path_for(3, 17)
    assert root == tmp_path / "data" / "decks" / "3" / "17"
    index = (root / "index.html").read_text(encoding="utf-8")
    assert "/decks/17/assets/" in index
    for path, text in text_files(root):
        assert "/__deck__/" not in text, f"{path.name}에 기준 경로가 남았다"
    assert (root / "classroom-deck.json").is_file()


def test_reading_meta_back_from_disk(store):
    store.install(1, 2, FIXTURE)
    assert store.read_meta(1, 2).slide_count == 4
    assert store.exists(1, 2)
    assert not store.exists(1, 3)


def test_install_does_not_touch_another_deck(store):
    store.install(1, 1, FIXTURE)
    store.install(1, 2, FIXTURE)
    assert (store.path_for(1, 1) / "index.html").read_text().count("/decks/1/") > 0
    assert (store.path_for(1, 2) / "index.html").read_text().count("/decks/2/") > 0


def test_remove_deletes_the_folder_and_is_quiet_when_missing(store):
    store.install(1, 5, FIXTURE)
    store.remove(1, 5)
    assert not store.path_for(1, 5).exists()
    store.remove(1, 5)  # 이미 없어도 오류가 아니다


# --- 거절하기 ------------------------------------------------------------------------------


def rejected(store, zip_path):
    with pytest.raises(DeckError) as err:
        store.install(1, 9, zip_path)
    assert str(err.value) == BAD_DECK
    assert not store.path_for(1, 9).exists()
    leftovers = [p for p in store.root.rglob("*")] if store.root.exists() else []
    assert [p for p in leftovers if p.is_file()] == [], "실패한 뒤 파일이 남았다"


def test_rejects_something_that_is_not_a_zip(store, tmp_path):
    path = tmp_path / "x.zip"
    path.write_bytes(b"PK\x03\x04 not really a zip")
    rejected(store, path)


def test_rejects_a_zip_without_index_or_meta(store, tmp_path):
    entries = fixture_entries()
    no_index = {k: v for k, v in entries.items() if k != "index.html"}
    no_meta = {k: v for k, v in entries.items() if k != "classroom-deck.json"}
    rejected(store, make_zip(tmp_path, no_index, "a.zip"))
    rejected(store, make_zip(tmp_path, no_meta, "b.zip"))


def test_rejects_a_build_that_did_not_use_the_template_base(store, tmp_path):
    entries = fixture_entries()
    entries["index.html"] = entries["index.html"].replace(b"/__deck__/", b"/")
    rejected(store, make_zip(tmp_path, entries))


def test_rejects_a_folder_wrapped_zip(store, tmp_path):
    # dist 폴더째 묶으면 index.html이 맨 위에 없다. 템플릿 스크립트는 맨 위에 둔다
    wrapped = {f"dist/{k}": v for k, v in fixture_entries().items()}
    rejected(store, make_zip(tmp_path, wrapped))


@pytest.mark.parametrize(
    "meta",
    [
        b"not json",
        json.dumps({"format": 2, "slide_count": 4, "slides": []}).encode(),
        json.dumps({"format": 1, "slide_count": 0, "slides": []}).encode(),
        json.dumps({"format": 1, "slide_count": 3, "slides": [{"no": 1, "title": "", "note": ""}]}).encode(),
        json.dumps({"format": 1, "slide_count": "4", "slides": []}).encode(),
    ],
)
def test_rejects_a_broken_meta_file(store, tmp_path, meta):
    entries = fixture_entries()
    entries["classroom-deck.json"] = meta
    rejected(store, make_zip(tmp_path, entries))


@pytest.mark.parametrize("evil", ["../evil.js", "assets/../../evil.js", "/etc/evil.js", "C:/evil.js", "assets\\..\\evil.js"])
def test_rejects_paths_that_escape_the_folder(store, tmp_path, evil):
    entries = fixture_entries()
    entries[evil] = b"alert(1)"
    rejected(store, make_zip(tmp_path, entries))
    assert not (tmp_path / "evil.js").exists()


def test_rejects_symbolic_links(store, tmp_path):
    rejected(store, make_zip(tmp_path, fixture_entries(), symlinks=[("assets/link.js", "/etc/passwd")]))


def test_rejects_a_zip_bomb_before_unpacking(tmp_path):
    small = DeckStore(tmp_path / "decks", max_unzipped_bytes=2_000_000, max_files=5000)
    entries = fixture_entries()
    entries["assets/zeros.bin"] = b"\0" * 3_000_000  # 압축하면 몇 KB다
    path = make_zip(tmp_path, entries)
    assert path.stat().st_size < 1_000_000
    rejected(small, path)


def test_zip_bomb_is_refused_from_the_declared_size_without_unpacking(tmp_path, monkeypatch):
    import app.deck_store as module

    def never(*args, **kwargs):
        raise AssertionError("선언된 크기로 거절해야 하는데 풀기 시작했다")

    monkeypatch.setattr(module, "_write_member", never)
    small = DeckStore(tmp_path / "decks", max_unzipped_bytes=2_000_000, max_files=5000)
    entries = fixture_entries()
    entries["assets/zeros.bin"] = b"\0" * 3_000_000
    rejected(small, make_zip(tmp_path, entries))


def test_unpacking_stops_when_real_bytes_pass_the_budget(tmp_path):
    # 선언된 크기를 믿지 않는다: 실제로 쓴 바이트가 남은 한도를 넘으면 멈춘다
    from app.deck_store import _write_member

    path = make_zip(tmp_path, {"big.bin": b"x" * 10_000})
    with zipfile.ZipFile(path) as zf, pytest.raises(DeckError):
        _write_member(zf, zf.getinfo("big.bin"), tmp_path / "out" / "big.bin", [9_999])
    with zipfile.ZipFile(path) as zf:
        budget = [10_000]
        _write_member(zf, zf.getinfo("big.bin"), tmp_path / "ok" / "big.bin", budget)
        assert budget == [0]


def test_rejects_too_many_files(tmp_path):
    few = DeckStore(tmp_path / "decks", max_unzipped_bytes=50_000_000, max_files=30)
    entries = fixture_entries()
    entries.update({f"assets/x{i}.txt": b"x" for i in range(40)})
    rejected(few, make_zip(tmp_path, entries))


def test_a_failure_while_unpacking_leaves_nothing(store, tmp_path, monkeypatch):
    import app.deck_store as module

    calls = {"n": 0}
    real = module._write_member

    def explode(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 5:
            raise OSError("disk full")
        return real(*args, **kwargs)

    monkeypatch.setattr(module, "_write_member", explode)
    with pytest.raises(OSError):
        store.install(1, 9, FIXTURE)
    assert not store.path_for(1, 9).exists()
    assert [p for p in store.root.rglob("*") if p.is_file()] == []


def test_zip_entries_from_memory_work_too(store, tmp_path):
    # 같은 내용을 다시 묶어도(다른 압축 방식) 받아들인다
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        for k, v in fixture_entries().items():
            zf.writestr(k, v)
    path = tmp_path / "stored.zip"
    path.write_bytes(buf.getvalue())
    assert store.install(1, 4, path).slide_count == 4
