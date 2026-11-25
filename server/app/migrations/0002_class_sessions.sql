-- 002-slide-sync 회차 스키마 (plan 데이터 모델).
--
-- 규칙
--  * 세 표 모두 강좌 소속이라 classroom_id를 가진다(C5). 학생을 가리키는 열이 없다(C7).
--  * 회차의 진행 상태와 위치는 이 표가 진실이다(C13). 화면은 연결이 끊겨도 여기서 다시 읽는다.
--  * 강좌당 진행 중인 회차는 하나다. 두 화면이 동시에 시작해도 색인이 하나만 받아들인다(AC10).
--  * 넘기기는 위치 열만 바꾸고 events에 쌓지 않는다. 시작·종료·보내기·거두기 같은 행동은 events에 쌓는다(C6).

CREATE TABLE class_sessions (
    id               INTEGER PRIMARY KEY,
    classroom_id     INTEGER NOT NULL REFERENCES classrooms(id),
    title            TEXT NOT NULL CHECK (length(trim(title)) > 0 AND length(title) <= 40),  -- 회차 이름(AC2)
    sort_order       INTEGER NOT NULL,
    status           TEXT NOT NULL DEFAULT 'scheduled' CHECK (status IN ('scheduled', 'live', 'ended')),
    current_slide    INTEGER NOT NULL DEFAULT 1 CHECK (current_slide >= 1),
    current_click    INTEGER NOT NULL DEFAULT 0 CHECK (current_click >= 0),
    furthest_slide   INTEGER NOT NULL DEFAULT 1 CHECK (furthest_slide >= 1),
    furthest_click   INTEGER NOT NULL DEFAULT 0 CHECK (furthest_click >= 0),
    version          INTEGER NOT NULL DEFAULT 0,   -- 바뀔 때마다 1 증가. 화면이 놓친 발행을 알아본다
    first_started_at TEXT,                         -- 한 번이라도 시작한 시각(진행 회차 수, 삭제 가능 여부)
    started_at       TEXT,
    ended_at         TEXT,
    created_at       TEXT NOT NULL,
    -- 가장 멀리 간 위치는 현재 위치보다 앞일 수 없다(되돌아가도 줄지 않는다)
    CHECK (furthest_slide > current_slide OR (furthest_slide = current_slide AND furthest_click >= current_click)),
    UNIQUE (id, classroom_id)
);
CREATE INDEX class_sessions_by_classroom ON class_sessions(classroom_id, sort_order);
CREATE UNIQUE INDEX class_sessions_one_live ON class_sessions(classroom_id) WHERE status = 'live';

-- 슬라이드 묶음. 한 번 저장하면 바꾸지 않는다. 바꾸기는 새 행 + 이전 행에 removed_at.
-- 파일은 DATA_DIR/decks/{classroom_id}/{id}/ 에 있다.
CREATE TABLE decks (
    id            INTEGER PRIMARY KEY,
    classroom_id  INTEGER NOT NULL REFERENCES classrooms(id),
    session_id    INTEGER NOT NULL,
    original_name TEXT NOT NULL,
    slide_count   INTEGER NOT NULL CHECK (slide_count >= 1),   -- 노트 파일(classroom-deck.json) 기준
    size_bytes    INTEGER NOT NULL CHECK (size_bytes >= 0),
    uploaded_at   TEXT NOT NULL,
    removed_at    TEXT,
    FOREIGN KEY (session_id, classroom_id) REFERENCES class_sessions(id, classroom_id)
);
CREATE UNIQUE INDEX decks_one_live_per_session ON decks(session_id) WHERE removed_at IS NULL;

-- 교수가 수업 중 보낸 글과 링크. 거두면 retracted_at만 쓰고 본문은 남긴다(C6, 기록은 events에도).
CREATE TABLE session_items (
    id           INTEGER PRIMARY KEY,
    classroom_id INTEGER NOT NULL REFERENCES classrooms(id),
    session_id   INTEGER NOT NULL,
    body         TEXT CHECK (body IS NULL OR (length(trim(body)) > 0 AND length(body) <= 2000)),
    url          TEXT CHECK (url IS NULL OR url LIKE 'http://_%' OR url LIKE 'https://_%'),
    client_key   TEXT NOT NULL,   -- 보내는 화면이 만든 난수. 다시 눌러도 한 번만 저장한다
    created_at   TEXT NOT NULL,
    retracted_at TEXT,
    CHECK (body IS NOT NULL OR url IS NOT NULL),
    UNIQUE (session_id, client_key),
    FOREIGN KEY (session_id, classroom_id) REFERENCES class_sessions(id, classroom_id)
);
CREATE INDEX session_items_by_session ON session_items(session_id, id);
