---
spec: 001-classroom-entry
status: draft        # draft | approved | stale
updated: 2026-11-17
---

# 계획: 로그인, 강좌, 학생 입장

> 규칙: 스펙의 요구사항을 다시 쓰지 않습니다. "어떻게 만들 것인가"만 씁니다. 확인되지 않은 가정은 아래 "위험과 검증"으로 보냅니다.

## 접근 요약

서버(`server/`)는 FastAPI 단일 프로세스와 SQLite 한 파일로 만들고, 클라이언트(`client/`)는 SvelteKit SPA를 같은 서버가 정적 파일로 내려준다(같은 출처라 쿠키가 단순하다). 교수는 GitHub 로그인(허용 목록, 숫자 ID 기준)과 서버가 저장하는 로그인 상태로 인증하고, 학생은 이메일 코드로 인증한다. 코드는 **저장하지 않고 서버 비밀값과 챌린지 번호에서 계산**하며(교수 화면에 보여 줄 때도 계산), 요청한 기기의 쿠키와 묶는다. 이름·이메일·학번은 "명단" 쪽에만 두고, 닉네임을 가진 "멤버십"은 개인정보 없이 가명만 가진다. 둘의 연결은 한 모듈만 읽는다. 상태는 먼저 DB에 쓴 뒤 화면에 알리고(C13), 교수 관리 페이지의 실시간 갱신(입장 요청, 대기 중인 인증)만 WebSocket으로 보낸다.

## 기술 선택과 근거

| 영역 | 선택 | 근거 | 대안 |
|---|---|---|---|
| 서버 | FastAPI, uvicorn, 단일 프로세스 | CLAUDE.md 확정 스택. 프로토타입 1·4·5번에서 WebSocket과 단일 프로세스가 200~400명 동시 접속을 감당함 | 없음 |
| DB | **SQLite**(WAL, `synchronous=FULL`) | 프로토타입 4번: SQLite 200명 동시 제출 p95 약 12ms, 400명 p95 22ms, 유실 0. 쓰기는 한 프로세스가 직렬로 처리해도 충분. 단일 파일이라 백업과 복원이 쉬움. 이슈 #12의 결정이며, 프로토타입은 `synchronous=NORMAL`로 쟀으므로 `FULL`은 재측정한다(아래 위험 1) | PostgreSQL: 다중 프로세스나 외부 DB가 필요해질 때. 데이터 접근을 한 모듈에 모아 두어 교체 비용을 낮춘다 |
| 데이터 접근 | 표준 `sqlite3`와 직접 쓴 SQL, 번호 붙은 `.sql` 마이그레이션 파일과 얇은 실행기 | 테이블이 10개 안팎이고 의존성을 늘리지 않음(C17). 강의실 식별자 조건을 모든 조회에 눈으로 확인하기 쉬움 | SQLAlchemy+Alembic: 모델이 커지면 도입. 지금은 과함 |
| 교수 로그인 | GitHub OAuth 웹 흐름(`state` 검증), 허용 목록은 환경 설정의 **숫자 ID** 목록. 요청 범위는 공개 프로필만 | CLAUDE.md 확정 스택. 로그인 이름은 바뀔 수 있어 숫자 ID로 비교. 이메일은 읽지 않음(C11) | GitHub 외 로그인: 범위 밖 |
| GitHub 호출 | 표준 `urllib`로 토큰 교환과 사용자 조회 2회만 호출 | 호출이 두 번뿐이라 HTTP 클라이언트 의존성이 필요 없음 | httpx: 마지막 릴리스가 2024-12(약 11개월 전). 런타임에 넣지 않고 테스트용으로만 둠 |
| 로그인 상태 | 서버에 저장하는 불투명 토큰(256비트 난수), 쿠키에는 토큰만, DB에는 해시만. `HttpOnly`, `Secure`, `SameSite=Lax` | 로그아웃·끊기·보관 때 즉시 폐기해야 함(AC4, AC9, AC20). 서명 토큰은 즉시 폐기가 어려움 | JWT: 폐기 목록이 필요해져 이득이 없음 |
| 변경 요청 보호 | 변경 요청(POST/PUT/DELETE)은 `Origin` 헤더가 서비스 주소와 같을 때만 처리 | `SameSite=Lax`에 더한 두 번째 방어. 의존성 없음 | CSRF 토큰: 같은 출처 SPA에서는 과함 |
| 인증 코드 | 6자리 숫자. `HMAC-SHA256(서버 비밀값, 챌린지 번호:난수)`에서 계산하고 **저장하지 않는다**. 검증도 다시 계산해 상수 시간으로 비교 | 교수가 코드를 볼 수 있어야 함(AC45)과 DB가 새도 코드를 복원할 수 없어야 함을 함께 만족 | 평문 저장: DB 유출 시 바로 쓸 수 있음. 암호화 저장: 추가 의존성과 키 관리 |
| 기기 묶음 | 서버가 처음 방문 때 심는 기기 쿠키(128비트 난수, DB에는 해시). 챌린지에 기기 해시를 기록하고 일치할 때만 검증 | AC33. 브라우저가 쿠키를 지우면 새 기기가 됨(스펙과 일치) | 지문 기반 식별: 정확하지 않고 개인정보 부담 |
| 메일 발송 | **Resend**(사용자 결정). `Mailer` 인터페이스 + 두 구현(`OutboxMailer`: 개발·테스트용, `ResendMailer`: 표준 `urllib`로 HTTPS 호출, SDK 미사용). 발송 요청은 DB의 발송 대기 표에 먼저 쓰고 같은 프로세스의 작업 스레드가 **초당 8건 이하**로 보냄(상한은 팀당 초당 10회). 429나 실패는 지수 대기 뒤 재시도 | C13, C15. 코드가 DB에 먼저 남으므로 메일이 늦어도 교수 대체 경로(AC44~AC47)는 동작함. 발신은 **직접 소유한 도메인을 인증**해야 함. 무료 플랜은 하루 100통, 월 3,000통이라 200명 강좌에는 부족하고 Pro(월 $20, 월 5만 통, 일 한도 없음)가 필요함(2026-11-17 가격 페이지 확인). 한도와 가격은 바뀔 수 있어 구현 전에 다시 확인 | SMTP(`smtplib`): 서비스를 바꿔야 할 때 `Mailer` 구현 하나만 교체 |
| 실시간(교수 화면만) | FastAPI 내장 WebSocket `/ws/admin/{강좌}`. 서버→클라이언트 이벤트만 보내고, 재접속하면 목록을 다시 불러옴 | AC40, AC45의 "새로고침 없이". 프로토타입 5번에서 끊김·재시작 복구 확인. 학생 화면은 실시간이 필요 없음 | 폴링: 200명 입장 때 교수 화면 지연이 커짐 |
| 클라이언트 | SvelteKit(SPA 모드), Svelte 5, Tailwind CSS v4, shadcn-svelte, Iconoir | CLAUDE.md 확정 스택. 토큰은 `docs/design/theme.css`와 `tokens.md` | 없음 |
| CSV | 표준 `csv`, `utf-8-sig`로 엄격하게 디코딩, 1MB 제한 | 의존성 없음. 디코딩 실패는 AC13 오류 문구로 안내 | CSV 라이브러리: 불필요 |
| 시간 | `Clock` 인터페이스 주입 | 만료·보관 후 6개월 삭제를 시계를 돌려 테스트하려면 필요 | 없음 |
| 닉네임 | 형용사+명사 한국어 단어 목록에서 무작위 조합, 강좌 안에서 겹치면 다시 뽑음 | AC29. 목록은 저장소에 두고 사용자가 검토 | 숫자 닉네임: 읽기 어려움 |

### 의존성 확인 (C17, 2026-11-17 조회)

버전은 구현할 때 lockfile로 고정한다. 아래 값은 조회 당시 최신이다.

| 패키지 | 용도 | 최신(공개일) | 다운로드 | 판단 |
|---|---|---|---|---|
| fastapi | 서버 | 0.163.1 (2026-11-15) | 월 5.3억 | 사용 |
| uvicorn | 서버 실행 | 0.54.0 (2026-09-25) | 월 6.6억 | 사용 |
| python-multipart | CSV 업로드(파일 폼) | 0.0.34 (2026-11-16) | 월 4.9억 | 사용 |
| pytest, pytest-asyncio | 테스트 | 9.2.0 (2026-10-27), 1.5.0 (2026-11-12) | 월 9.6억, 2.8억 | 개발용 |
| ruff | 린트 | 0.17.5 (2026-11-12) | 월 4.2억 | 개발용 |
| httpx | 서버 테스트 클라이언트가 요구 | 0.28.1 (**2024-12-06**) | 월 7.9억 | **개발용으로만**. 갱신이 오래되어 런타임에는 넣지 않음 |
| @sveltejs/kit, svelte, tailwindcss | 클라이언트(확정 스택) | 3.2.0, 5.57.3, 4.3.5 (2026-10~11) | 주 530만, 980만, 1.8억 | 사용 |
| vitest, @playwright/test | 클라이언트·E2E 테스트 | 5.1.0, 1.65.1 | 주 1.9억, 1.3억 | 개발용 |
| bits-ui | shadcn-svelte가 쓰는 구성요소 | 2.21.0 (2026-11-11) | 주 180만 | 사용 |
| iconoir | 아이콘(확정 스택) | 7.12.2 (2026-11-04) | 주 약 4.5만 | **소규모**. 필요한 아이콘만 가져오고 버전을 고정 |

## 데이터 모델 변경

원칙: 강좌(강의실)에 속한 모든 표는 `classroom_id`를 가진다(C5). 계정층 표(`accounts`, `device_logins`, `professors`)는 정의상 강좌를 넘나들므로 `classroom_id`가 없다(C5 해석, 아래 점검표와 위험 8 참고). 시각은 UTC 저장.

**계정층 (C7의 1층)**
- `professors`: `github_id`(숫자, 기본키), `login`, `created_at`. 허용 목록은 설정에 있고 이 표는 로그인한 사람의 기록이다.
- `professor_sessions`: 토큰 해시, `github_id`, 만료, 폐기 시각.
- `accounts`: `id`, `email_norm`(고유), `created_at`. 학생의 이메일은 여기와 명단에만 있다.
- `devices`: 기기 쿠키 해시, 첫 방문 시각.
- `device_logins`: 토큰 해시, `account_id`, `device_id`, `persistent`(로그인 유지), 만료(유지 끔은 24시간 안전 상한), 폐기 시각.

**강좌와 명단 (개인정보는 여기)**
- `classrooms`: `id`, `owner_github_id`, `name`, `section_name`, `term`(비어 있을 수 있음, 학기 표기는 스펙 미결정이라 화면에서 쓰지 않음), `status`(active/archived), `archived_at`, `invite_token`(고유), `source_classroom_id`(복제 원본), `organization_id`(비어 있음, 자리만. C5), `created_at`.
- `roster_entries`: `classroom_id`, `student_no`, `name`, `email_norm`, `created_at`, `removed_at`. 고유: 같은 강좌에서 살아 있는 `email_norm`과 `student_no`는 각각 하나. 한 강좌 200건 상한은 입력 전 같은 쓰기 트랜잭션 안에서 센다.
- `join_requests`: `classroom_id`, `email_norm`, `name`, `student_no`, `status`(pending/approved/rejected), `created_at`, `decided_at`. 고유: 같은 강좌에서 pending인 `email_norm`은 하나(AC43).

**가명층 (C7의 2~3층)**
- `memberships`: `id`, `classroom_id`, `nickname`, `created_at`, `notice_ack_at`(채팅 이용 안내 확인), `reverify_after`(로그인 끊기 시각). 고유: `(classroom_id, nickname)`. **이메일·이름·학번 열이 없다.** 이후 채팅·출석·퀴즈 표는 이 `id`만 참조한다.
- `member_identities`: `membership_id`, `classroom_id`, `account_id`, `roster_entry_id`. 멤버십과 사람을 잇는 **유일한 표**이며 `identity` 모듈만 읽는다(C9). 004의 작성자 확인이 이 모듈을 쓴다.
- `classroom_verifications`: `device_login_id`, `classroom_id`, `membership_id`, `verified_at`. 이 기기가 이 강좌에서 인증을 마친 기록. 접근은 `verified_at > reverify_after`일 때만 허용한다(AC20).

**인증 챌린지와 메일**
- `login_challenges`: `id`, `classroom_id`, `email_norm`, `device_id`, `nonce`, `created_at`, `expires_at`, `attempts`, `status`(active/used/expired/superseded), `professor_notified_at`, `used_at`. **코드 열이 없다.**
- `mail_outbox`: `id`, `classroom_id`, `kind`, `to_email`, `body_ref`(챌린지 번호), `status`(pending/sent/failed), `attempts`, `next_try_at`, `sent_at`. 발송 뒤 `to_email`은 비운다.

**기록 (C6)**
- `events`: `id`, `classroom_id`, `type`, `actor_kind`(professor/student/system), `actor_ref`(교수는 `github_id`, 학생은 `membership_id`), `subject_roster_entry_id`(비어 있을 수 있음), `payload`(JSON, 이메일·이름·학번 금지), `created_at`. `BEFORE UPDATE`와 `BEFORE DELETE` 트리거가 오류를 내서 추가만 가능하다. 종류: `code_revealed`, `join_request_approved/rejected`, `roster_removed`, `login_revoked`, `classroom_archived`, `pii_purged`.

**보관 후 6개월 삭제 (C11)**
하루 한 번 도는 정리 작업이 `archived_at + 6개월`이 지난 강좌에서 `roster_entries`, `member_identities`, `join_requests`, `login_challenges`, `mail_outbox`, `device_logins`와 이들만 가리키던 `accounts`를 지운다(다른 살아 있는 강좌에 쓰이는 계정은 남긴다). `memberships`(가명)와 `events`는 남는다. 정리 결과는 `pii_purged` 기록으로 쌓는다. 작업은 같은 입력에 여러 번 돌려도 결과가 같다.

## 인터페이스

경로 앞에 `/api`가 붙는다. 변경 요청은 `Origin` 검사를 거친다. 모든 처리기는 권한 판단 함수(아래)를 호출한다.

- HTTP, 교수:
  - `GET /auth/github/login`, `GET /auth/github/callback`, `POST /auth/logout`, `GET /me`, `GET /me/summary`
  - `GET /classrooms`, `POST /classrooms`, `GET /classrooms/{id}`, `POST /classrooms/{id}/archive`, `POST /classrooms/{id}/clone`
  - `GET /classrooms/{id}/roster`, `POST /classrooms/{id}/roster/import`(CSV), `POST /classrooms/{id}/roster`, `DELETE /classrooms/{id}/roster/{entry}`, `POST /classrooms/{id}/roster/{entry}/revoke-login`
  - `GET /classrooms/{id}/invite`, `POST /classrooms/{id}/invite/regenerate`
  - `GET /classrooms/{id}/join-requests`, `POST …/join-requests/{req}/approve`, `POST …/join-requests/{req}/reject`
  - `GET /classrooms/{id}/pending-auth`(교수가 알림을 받은 챌린지만, 코드는 이때 계산해 응답. 응답할 때마다 `code_revealed`를 기록)
- HTTP, 학생(강좌 지정은 초대 토큰):
  - `GET /join/{token}`(강좌 이름·상태, 이 기기의 입장 상태)
  - `POST /join/{token}/email`, `POST /join/{token}/code`, `POST /join/{token}/resend`, `POST /join/{token}/notify-professor`, `POST /join/{token}/request-access`, `POST /join/{token}/enter`('확인하고 입장'), `GET /join/{token}/me`
- 토큰이 틀리거나 폐기됐으면 강좌 존재 여부를 알려 주지 않는 같은 응답을 준다(AC22).
- WebSocket: `/ws/admin/{classroom_id}`, 교수 로그인과 강좌 소유를 확인한 뒤 연결. 서버→클라이언트 이벤트: `join_request.created`, `join_request.updated`, `pending_auth.created`, `pending_auth.updated`, `roster.updated`. 모두 DB 기록이 끝난 뒤에 보낸다. 재접속한 화면은 목록을 HTTP로 다시 받는다.
- 권한 판단(C8): `authz.decide(행위자, 행동, 대상)` 한 함수. 행동은 `classroom.read`, `classroom.manage`, `roster.manage`, `joinrequest.decide`, `pendingauth.view`, `student.enter`. 라우트마다 의존성으로 이 함수를 부르고, 호출하지 않는 라우트는 테스트가 실패하게 한다.
- 설정(환경 변수): 허용 GitHub 숫자 ID 목록, GitHub 클라이언트 ID·비밀값, 서버 비밀값, 서비스 주소(`Origin` 검사와 OAuth 콜백에 사용), Resend API 키, 발신 주소(인증한 도메인), 초당 발송 상한.

## 확장 지점 (자리만)

- `Mailer`: Resend 구현 하나만 만든다. 서비스를 바꾸게 되면 구현 하나만 교체한다.
- `RoomBus`(방 발행/구독, C15): 지금은 프로세스 안 메모리. 이후 스펙(002 이후)이 같은 인터페이스를 쓴다.
- 로그인 제공자: 교수 로그인은 `AuthProvider` 인터페이스 뒤에 두어 GitHub 외 제공자를 나중에 붙일 수 있게만 한다. 구현은 GitHub 하나.
- `organization_id`: 열만 만들고 쓰지 않는다.
- `identity` 모듈: 004의 작성자 확인이 사유 기록과 함께 호출하는 자리. 이 스펙에서는 입장 때 연결을 만드는 쓰기만 구현한다.

## 위험과 검증

| 위험·가정 | 확인 방법 | 결과 |
|---|---|---|
| 1. `synchronous=FULL`에서도 200명이 동시에 코드를 요청할 때 SQLite가 버틴다 | 구현 후 순수 WS가 아닌 HTTP 클라이언트 200개로 코드 요청 부하 측정(`/join/{token}/email` 동시 호출). 성공 기준: p95와 유실 값을 기록, 유실 0 | 미확인. 프로토타입 4번은 `NORMAL`로 측정(200명 p95 약 12ms) |
| 2. Resend로 200명의 코드 요청이 제때 도착한다. 걸리는 점: (a) 하루 100통 한도의 무료 플랜으로는 부족해 Pro가 필요하다 (b) API가 팀당 초당 10회라 200통은 한 번에 못 보내고 25초 이상 걸린다 (c) 직접 소유한 도메인 인증이 필요하다 (d) 학교 메일이 스팸함으로 분류할 수 있다 | **000에 7번 항목 추가를 제안**: 인증한 도메인으로 학교 도메인 주소 여러 개에 50~200통을 초당 8건 이하로 보내 도착 시간 p95와 스팸함 분류 건수를 기록. 제안 기준: p95 60초 이내, 스팸함 0건. 통과하지 못하면 교수 대체 경로(AC44~AC47)가 주 경로가 된다 | 미확인. 개발은 `OutboxMailer`로 진행. 사용자가 도메인과 플랜을 준비해야 함 |
| 3. 교실 한 개의 공유 IP 때문에 IP 기준 속도 제한을 쓸 수 없다 | IP 제한은 두지 않고 이메일(60초)과 기기 기준으로만 제한. 기기 쿠키 없이 보내는 반복 요청은 막지 못한다. 초대 링크를 가진 사람이 명단의 이메일을 알아내는 것(AC38)과 함께 위협 목록으로 점검 | 미확인. 위험을 받아들일지는 스펙 미결정 항목과 같은 질문 |
| 4. 기기 쿠키와 로그인 유지가 실제 학생 기기(iOS Safari, Android Chrome)에서 유지된다. **카카오톡 같은 앱 안 브라우저는 지원하지 않는다**(사용자 결정, 별도 안내도 하지 않음) | 실기기에서 AC25~AC36 시나리오를 따라 하고 결과를 기록 | 미확인. 앱 안 브라우저에서 열면 기기 묶음과 로그인 유지가 깨질 수 있고, 그 학생은 교수 대체 경로로 입장하게 됨. 받아들인 위험 |
| 5. 한국어 엑셀이 저장하는 CSV 두 가지(UTF-8, CP949)를 안내 문구대로 처리한다 | 실제 엑셀로 두 방식을 저장한 샘플 파일을 올려 AC13·AC14와 오류 문구 확인 | 미확인 |
| 6. GitHub OAuth 콜백 주소와 HTTPS가 배포 대상에 맞는다 | 배포 대상이 정해지면 설정값으로 확인. 그 전에는 로컬 개발 주소로 개발 | 미확인(배포 대상은 constitution 미결정) |
| 7. 닉네임 단어 목록에 부적절한 조합이 없고 200명 안에서 충돌 재시도가 문제없다 | 단위 테스트(한 강좌 200명 생성, 충돌 재시도 횟수 기록)와 사용자가 단어 목록을 검토 | 미확인 |
| 8. C5를 계정층 표에도 그대로 적용할지 | constitution 문구는 "모든 테이블"이라 계정층 표에는 강의실 식별자가 없다는 점이 걸린다. 사용자가 이 해석을 확인 | 미확인. 이 plan은 계정층은 정의상 강좌를 넘는다(C7 1층)고 해석함 |
| 9. 보관 후 6개월 삭제가 학교 규정과 맞는다 | 학교 정보 보호 담당 확인(스펙 미결정과 같음) | 미확인 |
| 10. 학기 표기(스펙 미결정)가 정해지기 전에는 카드의 "분반 · 학기"를 구현할 수 없다 | 스펙 결정 후 반영. 그 전에는 `term` 열만 만들어 둠 | 미확인 |

## constitution 점검

해당 없음: C1(채팅 점수), C2(공개 경로), C3(공개), C4(퀴즈 통계)는 이 스펙이 만들지 않는 기능이다.

| 원칙 | 충족 방법 |
|---|---|
| C5 | 강좌 소속 표는 모두 `classroom_id`를 가지고 모든 조회에 조건으로 쓴다. `classrooms.organization_id`는 자리만. 계정층 표(`professors`, `accounts`, `devices`, `device_logins`)는 강좌를 넘나들어 예외로 해석(위험 8) |
| C6 | `events`는 트리거로 수정·삭제를 막고, 교수 행동(코드 열람, 승인·거절, 빼기, 끊기, 보관)을 쌓는다. 삭제 작업도 `events`는 건드리지 않는다 |
| C7 | 계정(`accounts`)·멤버십(`memberships`, 닉네임만)·활동 기록(멤버십 번호만) 세 층. 이메일·이름·학번 열은 `memberships`와 `events`에 없다. 닉네임은 강좌마다 따로 발급 |
| C8 | `authz.decide` 한 함수. 라우트가 호출하지 않으면 테스트 실패 |
| C9 | 멤버십과 사람을 잇는 `member_identities`는 `identity` 모듈만 읽는다. 명단·대기 중인 인증 응답에 닉네임을 넣지 않는다(AC17, AC45). 작성자 확인 화면 자체는 004 |
| C10 | 채팅 이용 안내 문구는 스펙 AC27의 문장 그대로 화면에 둔다. "익명"이라는 단어를 쓰지 않는다 |
| C11 | 수집은 학번·이름·이메일로 한정(입장 요청은 이름·학번·이메일). 발송 후 메일 표의 수신 주소를 비움. 보관 후 6개월 정리 작업. 학교 규정 확인은 위험 9 |
| C12 | 코드가 DB에 먼저 남으므로 메일이 늦어도 교수가 코드를 보고 알려 줄 수 있다. 명단 밖 학생은 입장 요청 경로. `Mailer` 실패는 재시도하되 화면은 막지 않는다 |
| C13 | 명단, 챌린지, 멤버십, 로그인 상태, 입장 요청, 메일 대기열은 모두 DB가 진실이다. 서버를 다시 시작해도 남는다. 실시간 이벤트는 기록 뒤에 보낸다 |
| C14 | 색은 `theme.css` 토큰만 쓴다. 오류와 상태에 아이콘과 문구를 함께 쓰고, 버튼·입력 `h-11`, 코드 입력 72px, 포커스 링 `ring-2 ring-ring ring-offset-2`. 학생 화면 390px 기준 |
| C15 | `Mailer`, `RoomBus`, `AuthProvider`, `Clock`, 데이터 접근을 인터페이스 뒤에 모으고, 지금 필요 없는 구현은 만들지 않는다 |
| C16 | 설정 화면, 보관 해제, 출석, 채팅 등 스펙 밖 기능은 만들지 않는다 |
| C17 | 새 의존성은 위 표에서 확인했고, 마이그레이션 실행기·HTTP 호출·CSV는 표준 라이브러리로 해결해 늘리지 않는다. 구현 때 lockfile로 고정 |
| C18 | `server/pyproject.toml`과 `client/package.json`이 생기면 CI의 `server`, `client` 작업이 켜진다. 첫 작업이 이 폴더를 만들 때 Dependabot 주석 처리된 두 항목을 푼다 |

## 테스트 전략

테스트를 먼저 쓴다. 필수 회귀 테스트 중 이 스펙이 만드는 것에는 `constitution` 표시를 붙인다.

- **필수 회귀(constitution 표시)**
  - (C7) `memberships`, `events`, 이후 활동 기록 표에 이메일·이름·학번 열이 없고, 이벤트 내용에도 이메일이 없다. 닉네임으로 이메일을 조회할 수 있는 공개 경로가 없다.
  - (C6) `events`는 수정·삭제가 실패한다.
  - (C8) 모든 라우트가 권한 판단 함수를 호출한다.
  - (C9에 가까운 확인) 명단 응답과 대기 중인 인증 응답에 닉네임이 없다.
  - (C11) 시계를 6개월 넘겨 정리 작업을 돌리면 개인정보 표가 비고 `memberships`와 `events`는 남으며, 두 번 돌려도 같다.
  - 004에서 만드는 (C9) 신원 조회 테스트는 이 스펙 범위가 아니다.
- **단위 테스트**: 이메일 정규화(AC16), 코드 계산·검증·만료·횟수·재요청 간격(AC30~AC32), 기기 묶음(AC33), 닉네임 생성과 충돌, CSV 행 검사(AC14), 200명 상한(AC18), 권한 판단 함수의 행동별 표.
- **통합 테스트(서버, `OutboxMailer`와 가짜 `Clock`)**: S1~S11 흐름, 교수 소유 확인(AC8), 보관 뒤 접근(AC10), 링크 재생성(AC22), 로그인 끊기(AC20), 로그인 유지와 다른 강좌 입장(AC35~AC37), 입장 요청 상태 전이(AC38~AC43), 대기 중인 인증과 `code_revealed` 기록(AC44~AC48), 서버 재시작 뒤 상태 유지(C13), 마이페이지 합계(AC49).
- **클라이언트 테스트(vitest)**: 학생 4단계 화면의 오류 문구와 비활성 버튼, 오류가 글로 나오는지(AC50).
- **E2E(Playwright)**: 학생 입장 전체(AC24~AC28)를 서로 다른 브라우저 컨텍스트 두 개로 실행해 기기 묶음(AC33)을 확인한다. 키보드만으로 로그인·입장(AC51)과 390px 폭 가로 스크롤 없음을 확인한다.
- **측정(구현 후)**: 위험 1의 200명 부하, 위험 4의 실기기 확인은 자동 테스트가 아니라 수동 확인 목록으로 두고 결과를 위험 표에 쓴다.
