-- migrate: foreign_keys=off
-- 002 스펙 변경(2026-11-26): 묶음 공개·비공개, 가장 멀리 간 위치 없애기.
--
--  * decks.public: 교수가 고른다. 새로 올리거나 바꾼 묶음(새 행)은 0(비공개)으로 시작한다(AC47, AC41).
--  * class_sessions의 furthest_slide, furthest_click을 없앤다. CHECK에 걸려 있어 DROP COLUMN이 안 되므로 표를
--    다시 만든다. decks와 session_items가 이 표를 가리키므로 외래 키를 끄고 돌린다(첫 줄 표시, db.migrate가
--    끝나기 전에 foreign_key_check로 확인한다). 색인과 다른 규칙은 0002와 같다.

ALTER TABLE decks ADD COLUMN public INTEGER NOT NULL DEFAULT 0 CHECK (public IN (0, 1));

CREATE TABLE class_sessions_new (
    id               INTEGER PRIMARY KEY,
    classroom_id     INTEGER NOT NULL REFERENCES classrooms(id),
    title            TEXT NOT NULL CHECK (length(trim(title)) > 0 AND length(title) <= 40),  -- 회차 이름(AC2)
    sort_order       INTEGER NOT NULL,
    status           TEXT NOT NULL DEFAULT 'scheduled' CHECK (status IN ('scheduled', 'live', 'ended')),
    current_slide    INTEGER NOT NULL DEFAULT 1 CHECK (current_slide >= 1),
    current_click    INTEGER NOT NULL DEFAULT 0 CHECK (current_click >= 0),
    version          INTEGER NOT NULL DEFAULT 0,   -- 바뀔 때마다 1 증가. 화면이 놓친 발행을 알아본다
    first_started_at TEXT,                         -- 한 번이라도 시작한 시각(진행 회차 수, 삭제 가능 여부)
    started_at       TEXT,
    ended_at         TEXT,
    created_at       TEXT NOT NULL,
    UNIQUE (id, classroom_id)
);

INSERT INTO class_sessions_new (id, classroom_id, title, sort_order, status, current_slide, current_click, version,
                                first_started_at, started_at, ended_at, created_at)
SELECT id, classroom_id, title, sort_order, status, current_slide, current_click, version,
       first_started_at, started_at, ended_at, created_at
  FROM class_sessions;

DROP TABLE class_sessions;
ALTER TABLE class_sessions_new RENAME TO class_sessions;

CREATE INDEX class_sessions_by_classroom ON class_sessions(classroom_id, sort_order);
CREATE UNIQUE INDEX class_sessions_one_live ON class_sessions(classroom_id) WHERE status = 'live';
