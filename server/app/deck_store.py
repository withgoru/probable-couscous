"""슬라이드 묶음 파일 저장소(002 plan `DeckStore`, C15).

묶음 파일을 검사하고, 풀고, 지우는 일은 이 모듈만 한다. 지금은 로컬 폴더 하나(`{root}/{강좌}/{묶음}/`)이고,
배포 대상이 정해져 다른 저장소가 필요해지면 이 모듈만 바꾼다.

받아들이는 묶음(`slides-template`의 `npm run build:classroom` 결과)
- 맨 위에 `index.html`이 있고 그 안에 고정 기준 경로 `/__deck__/`가 있다.
- 맨 위에 `classroom-deck.json`(`format` 1, `slide_count`, 슬라이드 수만큼의 `slides`)이 있다.

위험한 zip은 풀기 전에 거절한다(plan 위험 7): 폴더 밖 경로, 심볼릭 링크, 풀었을 때 너무 큰 것, 파일이 너무 많은 것.
풀 때도 실제로 쓴 바이트를 세어 선언한 크기를 믿지 않는다.

임시 폴더에 다 풀고 기준 경로를 바꾼 뒤 이름을 바꿔 한 번에 둔다. 도중에 실패하면 임시 폴더를 지운다.
"""

from __future__ import annotations

import json
import shutil
import stat
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

BAD_DECK = "슬라이드 묶음을 읽을 수 없습니다. Slidev로 빌드한 폴더(dist)를 zip으로 묶어 올려 주세요."
SENTINEL = b"/__deck__/"
META_NAME = "classroom-deck.json"
REWRITE_SUFFIXES = (".html", ".js", ".css", ".json")
CHUNK = 1024 * 1024


class DeckError(ValueError):
    """올린 묶음을 받아들일 수 없다. 메시지는 화면에 그대로 보인다."""


@dataclass(frozen=True)
class DeckMeta:
    slide_count: int
    slides: list[dict]


def _member_path(info: zipfile.ZipInfo) -> PurePosixPath | None:
    """안전한 상대 경로. 폴더 밖으로 나가거나 절대 경로·드라이브·역슬래시가 있으면 None."""
    name = info.filename
    if "\\" in name or name.startswith("/") or (len(name) > 1 and name[1] == ":"):
        return None
    path = PurePosixPath(name)
    if any(part in ("", ".", "..") for part in path.parts):
        return None
    return path


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    return stat.S_ISLNK(info.external_attr >> 16)


def _parse_meta(raw: bytes) -> DeckMeta:
    try:
        meta = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise DeckError(BAD_DECK) from None
    count = meta.get("slide_count") if isinstance(meta, dict) else None
    slides = meta.get("slides") if isinstance(meta, dict) else None
    if (
        meta.get("format") != 1
        or not isinstance(count, int)
        or isinstance(count, bool)
        or count < 1
        or not isinstance(slides, list)
        or len(slides) != count
        or not all(isinstance(s, dict) for s in slides)
    ):
        raise DeckError(BAD_DECK)
    return DeckMeta(slide_count=count, slides=slides)


def _write_member(zf: zipfile.ZipFile, info: zipfile.ZipInfo, target: Path, budget: list[int]) -> None:
    """한 파일을 푼다. 풀린 바이트가 남은 한도(budget[0])를 넘으면 멈춘다."""
    target.parent.mkdir(parents=True, exist_ok=True)
    with zf.open(info) as src, open(target, "wb") as dst:
        while chunk := src.read(CHUNK):
            budget[0] -= len(chunk)
            if budget[0] < 0:
                raise DeckError(BAD_DECK)
            dst.write(chunk)


class DeckStore:
    def __init__(self, root: Path, max_unzipped_bytes: int, max_files: int) -> None:
        self.root = root
        self.max_unzipped_bytes = max_unzipped_bytes
        self.max_files = max_files

    def path_for(self, classroom_id: int, deck_id: int) -> Path:
        return self.root / str(classroom_id) / str(deck_id)

    def exists(self, classroom_id: int, deck_id: int) -> bool:
        return (self.path_for(classroom_id, deck_id) / "index.html").is_file()

    def read_meta(self, classroom_id: int, deck_id: int) -> DeckMeta:
        return _parse_meta((self.path_for(classroom_id, deck_id) / META_NAME).read_bytes())

    def remove(self, classroom_id: int, deck_id: int) -> None:
        shutil.rmtree(self.path_for(classroom_id, deck_id), ignore_errors=True)

    def install(self, classroom_id: int, deck_id: int, zip_path: Path) -> DeckMeta:
        """검사하고 풀어 `path_for(강좌, 묶음)`에 둔다. 받아들일 수 없으면 `DeckError`."""
        final = self.path_for(classroom_id, deck_id)
        staging = self.root / ".incoming" / uuid.uuid4().hex
        try:
            with zipfile.ZipFile(zip_path) as zf:
                members = self._check(zf)
                meta = _parse_meta(zf.read(META_NAME))
                staging.mkdir(parents=True)
                budget = [self.max_unzipped_bytes]
                for info, path in members:
                    _write_member(zf, info, staging.joinpath(*path.parts), budget)
            self._rewrite(staging, deck_id)
            final.parent.mkdir(parents=True, exist_ok=True)
            if final.exists():  # 같은 번호가 남아 있으면(이전 실패) 지우고 둔다
                shutil.rmtree(final)
            staging.rename(final)
            return meta
        except zipfile.BadZipFile:
            raise DeckError(BAD_DECK) from None
        finally:
            shutil.rmtree(staging, ignore_errors=True)
            self._tidy(staging.parent)

    def _check(self, zf: zipfile.ZipFile) -> list[tuple[zipfile.ZipInfo, PurePosixPath]]:
        infos = zf.infolist()
        files = [i for i in infos if not i.is_dir()]
        if len(files) > self.max_files:
            raise DeckError(BAD_DECK)
        if sum(i.file_size for i in files) > self.max_unzipped_bytes:
            raise DeckError(BAD_DECK)  # 압축 폭탄: 풀기 전에 선언된 크기로 거절
        members = []
        for info in infos:
            path = _member_path(info)
            if path is None or _is_symlink(info):
                raise DeckError(BAD_DECK)
            if not info.is_dir():
                members.append((info, path))
        names = {str(p) for _, p in members}
        if "index.html" not in names or META_NAME not in names:
            raise DeckError(BAD_DECK)
        index = zf.getinfo("index.html")
        if index.file_size > CHUNK * 4 or SENTINEL not in zf.read(index):
            raise DeckError(BAD_DECK)
        return members

    @staticmethod
    def _rewrite(folder: Path, deck_id: int) -> None:
        base = f"/decks/{deck_id}/".encode()
        for path in folder.rglob("*"):
            if path.is_file() and path.suffix in REWRITE_SUFFIXES:
                data = path.read_bytes()
                if SENTINEL in data:
                    path.write_bytes(data.replace(SENTINEL, base))

    @staticmethod
    def _tidy(incoming: Path) -> None:
        try:
            incoming.rmdir()  # 비었으면 지운다
        except OSError:
            pass
