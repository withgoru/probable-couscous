-- 001-classroom-entry 핵심 스키마 (plan 데이터 모델).
--
-- 규칙
--  * 시각은 UTC ISO 8601 문자열(예: 2026-03-01T09:00:00+00:00)로 저장한다.
--  * 계정층 표(professors, professor_sessions, accounts, devices, device_logins)는 정의상 강좌를 넘나들어
--    classroom_id가 없다(C5 해석, 사용자 결정 2026-11-17). 나머지 표는 모두 classroom_id를 가진다.
--  * 이메일·이름·학번은 accounts, roster_entries, join_requests, login_challenges, mail_outbox에만 둔다(C7, C11).
--    memberships와 events에는 두지 않는다.
--  * 멤버십과 사람을 잇는 표는 member_identities 하나뿐이다(C9). identity 모듈만 읽는다.
--  * 인증 코드는 저장하지 않는다. 서버 비밀값과 챌린지 번호·nonce에서 계산한다.

-- ===== 계정층 (C7의 1층) =====

CREATE TABLE professors (
    github_id  INTEGER PRIMARY KEY,
    login      TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE professor_sessions (
    id         INTEGER PRIMARY KEY,
    token_hash TEXT NOT NULL UNIQUE,
    github_id  INTEGER NOT NULL REFERENCES professors(github_id),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT
);

CREATE TABLE accounts (
    id         INTEGER PRIMARY KEY,
    email_norm TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE devices (
    id            INTEGER PRIMARY KEY,
    token_hash    TEXT NOT NULL UNIQUE,
    first_seen_at TEXT NOT NULL
);

CREATE TABLE device_logins (
    id         INTEGER PRIMARY KEY,
    token_hash TEXT NOT NULL UNIQUE,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    device_id  INTEGER NOT NULL REFERENCES devices(id),
    persistent INTEGER NOT NULL CHECK (persistent IN (0, 1)),
    created_at TEXT NOT NULL,
    expires_at TEXT,           -- 로그인 유지는 비워 둔다(강좌가 보관될 때까지). 끔은 24시간 안전 상한
    revoked_at TEXT
);

-- ===== 강좌와 명단 =====

CREATE TABLE classrooms (
    id                  INTEGER PRIMARY KEY,
    owner_github_id     INTEGER NOT NULL REFERENCES professors(github_id),
    name                TEXT NOT NULL CHECK (length(trim(name)) > 0),
    section_name        TEXT,
    term                TEXT,   -- 학기 표기는 스펙 미결정이라 화면에서 쓰지 않는다
    status              TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    archived_at         TEXT,
    invite_token        TEXT NOT NULL UNIQUE,
    source_classroom_id INTEGER REFERENCES classrooms(id),
    organization_id     TEXT,   -- 조직 단위는 자리만 마련한다(C5)
    created_at          TEXT NOT NULL
);
CREATE INDEX classrooms_owner ON classrooms(owner_github_id, status);

CREATE TABLE roster_entries (
    id           INTEGER PRIMARY KEY,
    classroom_id INTEGER NOT NULL REFERENCES classrooms(id),
    student_no   TEXT NOT NULL,
    name         TEXT NOT NULL,
    email_norm   TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    removed_at   TEXT,
    UNIQUE (id, classroom_id)
);
CREATE UNIQUE INDEX roster_live_email ON roster_entries(classroom_id, email_norm) WHERE removed_at IS NULL;
CREATE UNIQUE INDEX roster_live_student_no ON roster_entries(classroom_id, student_no) WHERE removed_at IS NULL;

CREATE TABLE join_requests (
    id           INTEGER PRIMARY KEY,
    classroom_id INTEGER NOT NULL REFERENCES classrooms(id),
    email_norm   TEXT NOT NULL,
    name         TEXT NOT NULL,
    student_no   TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    created_at   TEXT NOT NULL,
    decided_at   TEXT
);
CREATE UNIQUE INDEX join_requests_one_pending ON join_requests(classroom_id, email_norm) WHERE status = 'pending';

-- ===== 가명층 (C7의 2~3층) =====

CREATE TABLE memberships (
    id             INTEGER PRIMARY KEY,
    classroom_id   INTEGER NOT NULL REFERENCES classrooms(id),
    nickname       TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    notice_ack_at  TEXT,        -- 채팅 이용 안내를 확인한 시각
    reverify_after TEXT,        -- 로그인 끊기 시각. 이 시각 뒤에 인증한 기기만 입장한다
    UNIQUE (classroom_id, nickname),
    UNIQUE (id, classroom_id)
);

CREATE TABLE member_identities (
    membership_id  INTEGER PRIMARY KEY,
    classroom_id   INTEGER NOT NULL,
    account_id     INTEGER NOT NULL REFERENCES accounts(id),
    roster_entry_id INTEGER NOT NULL,
    UNIQUE (classroom_id, account_id),
    UNIQUE (classroom_id, roster_entry_id),
    -- 같은 강좌의 멤버십과 명단만 연결할 수 있다(강좌 간 섞임 방지, C5)
    FOREIGN KEY (membership_id, classroom_id) REFERENCES memberships(id, classroom_id),
    FOREIGN KEY (roster_entry_id, classroom_id) REFERENCES roster_entries(id, classroom_id)
);

CREATE TABLE classroom_verifications (
    device_login_id INTEGER NOT NULL REFERENCES device_logins(id),
    classroom_id    INTEGER NOT NULL REFERENCES classrooms(id),
    membership_id   INTEGER NOT NULL,
    verified_at     TEXT NOT NULL,
    PRIMARY KEY (device_login_id, classroom_id),
    FOREIGN KEY (membership_id, classroom_id) REFERENCES memberships(id, classroom_id)
);

-- ===== 인증 챌린지와 메일 =====

CREATE TABLE login_challenges (
    id                    INTEGER PRIMARY KEY,
    classroom_id          INTEGER NOT NULL REFERENCES classrooms(id),
    email_norm            TEXT NOT NULL,
    device_id             INTEGER NOT NULL REFERENCES devices(id),
    nonce                 TEXT NOT NULL,   -- 코드 계산에 쓰는 난수. 코드 자체는 저장하지 않는다
    created_at            TEXT NOT NULL,
    expires_at            TEXT NOT NULL,
    attempts              INTEGER NOT NULL DEFAULT 0,
    status                TEXT NOT NULL DEFAULT 'active'
                          CHECK (status IN ('active', 'used', 'expired', 'superseded')),
    professor_notified_at TEXT,
    used_at               TEXT
);
CREATE INDEX login_challenges_lookup ON login_challenges(classroom_id, email_norm, status);
CREATE INDEX login_challenges_notified ON login_challenges(classroom_id, professor_notified_at);

CREATE TABLE mail_outbox (
    id           INTEGER PRIMARY KEY,
    classroom_id INTEGER NOT NULL REFERENCES classrooms(id),
    kind         TEXT NOT NULL,
    to_email     TEXT,                    -- 발송이 끝나면 비운다(C11)
    body_ref     INTEGER,                 -- 코드 메일이면 챌린지 번호
    status       TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'sent', 'failed')),
    attempts     INTEGER NOT NULL DEFAULT 0,
    next_try_at  TEXT,
    sent_at      TEXT,
    created_at   TEXT NOT NULL
);
CREATE INDEX mail_outbox_due ON mail_outbox(status, next_try_at);

-- ===== 기록 (C6: 추가만) =====

CREATE TABLE events (
    id                      INTEGER PRIMARY KEY,
    classroom_id            INTEGER NOT NULL REFERENCES classrooms(id),
    type                    TEXT NOT NULL,
    actor_kind              TEXT NOT NULL CHECK (actor_kind IN ('professor', 'student', 'system')),
    actor_ref               INTEGER,       -- 교수는 github_id, 학생은 membership_id. 외래 키를 두지 않는다
    subject_roster_entry_id INTEGER,       -- 개인정보 정리 뒤에도 기록이 남도록 외래 키를 두지 않는다
    payload                 TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(payload)),  -- 이메일·이름·학번 금지
    created_at              TEXT NOT NULL
);
CREATE INDEX events_by_classroom ON events(classroom_id, id);

CREATE TRIGGER events_no_update BEFORE UPDATE ON events
BEGIN
    SELECT RAISE(ABORT, 'events는 추가만 가능합니다. 수정할 수 없습니다.');
END;

CREATE TRIGGER events_no_delete BEFORE DELETE ON events
BEGIN
    SELECT RAISE(ABORT, 'events는 추가만 가능합니다. 지울 수 없습니다.');
END;

-- INSERT OR REPLACE는 같은 번호의 행을 지우고 다시 넣어 덮어쓸 수 있다. SQLite는 기본 설정에서
-- 이때 삭제 트리거를 실행하지 않으므로(연결 설정에 기대지 않으려고) 번호가 겹치는 삽입을 막는다.
CREATE TRIGGER events_no_replace BEFORE INSERT ON events
WHEN NEW.id IS NOT NULL AND EXISTS (SELECT 1 FROM events WHERE id = NEW.id)
BEGIN
    SELECT RAISE(ABORT, 'events는 추가만 가능합니다. 같은 번호로 덮어쓸 수 없습니다.');
END;
