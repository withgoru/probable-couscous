-- 003-attendance 출석 스키마 (plan 데이터 모델).
--
-- 규칙
--  * 모든 표가 강좌 소속이라 classroom_id를 가진다(C5). 회차·멤버십·요청은 (id, classroom_id)로 같은 강좌 것만 가리킨다.
--  * 이메일·이름·학번 열이 없다(C7). 학생은 명단 항목 번호(roster_entry_id)와, 학생이 직접 한 일이면 멤버십 번호로
--    가리킨다. roster_entry_id에는 events.subject_roster_entry_id와 같이 외래 키를 두지 않는다(명단과 연결하는 표는
--    member_identities 하나뿐이다).
--  * 출석 기록, 수기 요청, 처리는 추가만 한다(C6, 아래 트리거). 출석 상태는 회차·학생별 마지막 기록에서 계산한다.
--    지우기는 보관 6개월 정리(purge.py)에서만 한다(사용자 결정 2026-11-27). 정리가 지울 수 있어야 해서 지우기는
--    트리거로 막지 않고, 다른 코드가 지우지 않는 것은 테스트(test_attendance_schema.py)로 고정한다.
--  * 출석코드는 저장하지 않는다. 창의 nonce와 서버 비밀값, 15초 칸 번호로 계산한다.

-- 강좌의 출석 받는 시간(분). 다음에 시작하는 수업부터 쓰인다(AC1).
ALTER TABLE classrooms ADD COLUMN attendance_minutes INTEGER NOT NULL DEFAULT 10
    CHECK (attendance_minutes IN (5, 10, 15));

-- 출석 받는 창. 수업 시작이나 '출석 다시 받기'마다 한 행. 열림 = closed_at IS NULL AND closes_at > 지금.
-- 연장은 closes_at을, 마감·다시 받기·수업 종료는 closed_at을 쓴다(상태 표. 행동은 events에 쌓는다).
CREATE TABLE attendance_windows (
    id           INTEGER PRIMARY KEY,
    classroom_id INTEGER NOT NULL REFERENCES classrooms(id),
    session_id   INTEGER NOT NULL,
    nonce        TEXT NOT NULL CHECK (length(nonce) = 32 AND nonce NOT GLOB '*[^0-9a-f]*'),  -- 난수 16바이트(16진)
    opened_at    TEXT NOT NULL,
    closes_at    TEXT NOT NULL,
    closed_at    TEXT,
    opened_by    TEXT NOT NULL CHECK (opened_by IN ('start', 'reopen')),
    CHECK (closes_at > opened_at),
    CHECK (closed_at IS NULL OR closed_at >= opened_at),
    FOREIGN KEY (session_id, classroom_id) REFERENCES class_sessions(id, classroom_id)
);
-- 회차마다 "아직 닫지 않은 창"은 하나다. 다시 받기는 이전 창을 닫고 새 행을 넣는다
CREATE UNIQUE INDEX attendance_windows_one_unclosed ON attendance_windows(session_id) WHERE closed_at IS NULL;

-- 수기 출석 요청. 회차마다 학생 한 번(AC17). 사유는 앞뒤 공백을 뺀 1~200자.
CREATE TABLE attendance_requests (
    id              INTEGER PRIMARY KEY,
    classroom_id    INTEGER NOT NULL REFERENCES classrooms(id),
    session_id      INTEGER NOT NULL,
    roster_entry_id INTEGER NOT NULL,
    membership_id   INTEGER NOT NULL,
    reason          TEXT NOT NULL CHECK (length(trim(reason)) BETWEEN 1 AND 200 AND length(reason) <= 200),
    created_at      TEXT NOT NULL,
    UNIQUE (session_id, roster_entry_id),
    UNIQUE (id, classroom_id),
    UNIQUE (id, classroom_id, session_id, roster_entry_id),  -- 승인 기록이 요청과 같은 회차·학생을 가리키게
    FOREIGN KEY (session_id, classroom_id) REFERENCES class_sessions(id, classroom_id),
    FOREIGN KEY (membership_id, classroom_id) REFERENCES memberships(id, classroom_id)
);

-- 요청 처리. 요청마다 한 번이고 되돌리지 않는다(AC19). 승인은 같은 트랜잭션에서 attendance_marks에 request_approved.
CREATE TABLE attendance_decisions (
    request_id   INTEGER PRIMARY KEY,
    classroom_id INTEGER NOT NULL REFERENCES classrooms(id),
    decision     TEXT NOT NULL CHECK (decision IN ('approved', 'rejected')),
    github_id    INTEGER NOT NULL,
    decided_at   TEXT NOT NULL,
    FOREIGN KEY (request_id, classroom_id) REFERENCES attendance_requests(id, classroom_id)
);

-- 출석 기록. code = 학생이 코드로 출석(회차마다 한 번, AC16). request_approved·manual_present = 출석 (수기).
-- manual_absent = 교수가 결석으로 바꿈. 기록이 없으면 결석.
CREATE TABLE attendance_marks (
    id              INTEGER PRIMARY KEY,
    classroom_id    INTEGER NOT NULL REFERENCES classrooms(id),
    session_id      INTEGER NOT NULL,
    roster_entry_id INTEGER NOT NULL,
    membership_id   INTEGER,
    kind            TEXT NOT NULL CHECK (kind IN ('code', 'request_approved', 'manual_present', 'manual_absent')),
    actor_kind      TEXT NOT NULL CHECK (actor_kind IN ('student', 'professor')),
    actor_ref       INTEGER NOT NULL,   -- 학생은 membership_id, 교수는 github_id
    request_id      INTEGER,
    client_key      TEXT,               -- 코드 출석을 보낸 화면의 난수. 같은 누름의 재전송을 알아본다
    created_at      TEXT NOT NULL,
    -- 코드 출석은 학생 본인이, 그 밖은 교수가 한다
    CHECK (
        (kind = 'code' AND actor_kind = 'student' AND membership_id IS NOT NULL AND actor_ref = membership_id
            AND client_key IS NOT NULL AND length(client_key) BETWEEN 1 AND 64)
        OR (kind <> 'code' AND actor_kind = 'professor' AND membership_id IS NULL AND client_key IS NULL)
    ),
    CHECK ((kind = 'request_approved') = (request_id IS NOT NULL)),
    FOREIGN KEY (session_id, classroom_id) REFERENCES class_sessions(id, classroom_id),
    FOREIGN KEY (membership_id, classroom_id) REFERENCES memberships(id, classroom_id),
    FOREIGN KEY (request_id, classroom_id, session_id, roster_entry_id)
        REFERENCES attendance_requests(id, classroom_id, session_id, roster_entry_id)
);
CREATE UNIQUE INDEX attendance_marks_one_approval ON attendance_marks(request_id) WHERE request_id IS NOT NULL;
CREATE UNIQUE INDEX attendance_marks_one_code ON attendance_marks(session_id, roster_entry_id) WHERE kind = 'code';
CREATE INDEX attendance_marks_latest ON attendance_marks(session_id, roster_entry_id, id);

CREATE TRIGGER attendance_marks_no_update BEFORE UPDATE ON attendance_marks
BEGIN
    SELECT RAISE(ABORT, 'attendance_marks는 추가만 가능합니다. 수정할 수 없습니다.');
END;

CREATE TRIGGER attendance_requests_no_update BEFORE UPDATE ON attendance_requests
BEGIN
    SELECT RAISE(ABORT, 'attendance_requests는 추가만 가능합니다. 수정할 수 없습니다.');
END;

CREATE TRIGGER attendance_decisions_no_update BEFORE UPDATE ON attendance_decisions
BEGIN
    SELECT RAISE(ABORT, 'attendance_decisions는 추가만 가능합니다. 수정할 수 없습니다.');
END;

-- INSERT OR REPLACE는 겹치는 행을 지우고 다시 넣어 UPDATE 트리거를 피한다(0001 events_no_replace와 같은 이유).
-- 고유 키가 겹치는 삽입을 트리거로 먼저 막는다. 오류는 sqlite3.IntegrityError로 올라간다.
CREATE TRIGGER attendance_marks_no_replace BEFORE INSERT ON attendance_marks
WHEN (NEW.id IS NOT NULL AND EXISTS (SELECT 1 FROM attendance_marks WHERE id = NEW.id))
  OR (NEW.kind = 'code' AND EXISTS (
        SELECT 1 FROM attendance_marks
        WHERE session_id = NEW.session_id AND roster_entry_id = NEW.roster_entry_id AND kind = 'code'))
  OR (NEW.request_id IS NOT NULL AND EXISTS (SELECT 1 FROM attendance_marks WHERE request_id = NEW.request_id))
BEGIN
    SELECT RAISE(ABORT, 'attendance_marks는 추가만 가능합니다. 같은 기록을 덮어쓸 수 없습니다.');
END;

CREATE TRIGGER attendance_requests_no_replace BEFORE INSERT ON attendance_requests
WHEN (NEW.id IS NOT NULL AND EXISTS (SELECT 1 FROM attendance_requests WHERE id = NEW.id))
  OR EXISTS (
        SELECT 1 FROM attendance_requests
        WHERE session_id = NEW.session_id AND roster_entry_id = NEW.roster_entry_id)
BEGIN
    SELECT RAISE(ABORT, 'attendance_requests는 추가만 가능합니다. 같은 요청을 덮어쓸 수 없습니다.');
END;

CREATE TRIGGER attendance_decisions_no_replace BEFORE INSERT ON attendance_decisions
WHEN EXISTS (SELECT 1 FROM attendance_decisions WHERE request_id = NEW.request_id)
BEGIN
    SELECT RAISE(ABORT, 'attendance_decisions는 추가만 가능합니다. 처리를 바꿀 수 없습니다.');
END;
