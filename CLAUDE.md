# 강의 상호작용 도구

오프라인 대형 강의(방당 40~200명)에서 학생이 닉네임으로 질문하고, 교수가 슬라이드 밖의 자료를 수업 흐름을 끊지 않고 전달하며, 출석과 퀴즈를 한 화면에서 처리하는 본인 강의용 도구입니다.

## 항상 지킬 것

1. `docs/constitution.md`의 원칙(C1~C18)을 지킨다. 어겨야 하면 구현을 멈추고 사용자에게 보고한다.
2. **스펙 없이 기능을 구현하지 않는다.** 작업은 `/sdd-spec` → `/sdd-plan` → `/sdd-tasks` → `/sdd-implement` 순서로 진행한다. 각 문서는 사용자가 `status: approved`로 바꾼 뒤에만 다음 단계로 간다.
3. 구현은 한 번에 작업 하나, 테스트를 먼저 쓴다.
4. 화면 문구는 한국어, 짧고 정확하게. 오류는 무엇이 잘못됐고 어떻게 고치는지 말한다.
5. 접근성은 WCAG 2.2 AA(C14). 색 토큰은 아래 디자인 시스템을 따른다.

## Git 규칙 (GitHub Flow, 자세한 내용은 `docs/workflow.md`)

- **main에 직접 작업하지 않는다.** 작업을 시작할 때 현재 브랜치가 main이면 새 브랜치를 만든다. 이름: `spec/<번호>-<이름>`, `plan/…`, `tasks/…`, `feat/<번호>-T<nnn>-<요약>`, `fix/<요약>`, `chore/<요약>`.
- 커밋과 PR 제목은 `feat(001): T003 설명`, `docs(001): spec 작성` 형식(Conventional Commits, 범위=스펙 번호).
- 작업이 끝나면 커밋하고 push한 뒤 **Draft PR**을 연다(`gh`가 있으면 `gh pr create --draft`, 없으면 제목과 본문을 출력). 본문은 `.github/PULL_REQUEST_TEMPLATE.md`를 따른다.
- **하지 않는 것**: PR 머지, `status: approved`로 변경, main에 push, force push, 브랜치 보호 규칙 변경, 시크릿 커밋. 이 일은 사용자가 한다.
- CI의 `sdd-check`는 승인 순서와 구현 브랜치의 승인 상태를 점검한다. 실패하면 우회하지 말고 이유를 보고한다.

## 확정된 기술 스택

| 영역 | 선택 |
|---|---|
| 서버 | FastAPI, 내장 WebSocket, 단일 프로세스(방 관리는 메모리, 상태는 DB에 먼저 기록) |
| DB | plan에서 확정 (SQLite 또는 PostgreSQL) |
| 클라이언트 | SvelteKit(SPA 모드), Svelte 5, Tailwind CSS v4, shadcn-svelte |
| 아이콘 | Iconoir |
| 슬라이드 | Slidev 정적 빌드 + 자체 동기화 애드온(FastAPI WebSocket에 연결). 교수가 로컬에서 빌드해 업로드 |
| 교수 로그인 | GitHub (허용 목록, 숫자 ID 기준) |
| 교수 화면 | 노트북 한 대 구성은 presenter와 채팅 패널을 한 화면에 두는 통합 보기가 기본, 보조 기기(태블릿)는 선택 구성 |
| 학생 입장 | 초대 링크 → 이메일 입력 → 인증 코드 → 자동 로그인 |
| 수업 후 공개(M3) | GitHub App로 지정 경로(`published/`)에만 커밋 |

기술 선택을 바꿔야 하면 plan에 이유를 쓰고 사용자에게 알린다.

## 화면 목업

- 저장소 안의 자료: `docs/design/` (`screens.md` 화면 설명, `tokens.md` 토큰, `theme.css`, `mockups/`)
- 원본 캔버스(비공개): https://claude.ai/artifact/XbYFtDAXHQc4PnXY1Hh4hw
- 화면: 교수 로그인(Login), 강좌 목록(Courses), 마이페이지(MyPage), 설정(Settings), 교수 관리 페이지(Admin), 교수 수업 화면(Main), 교수 보조 화면(ProfessorSplit), 프로젝터 화면(Projector), 학생 모바일 화면(Student), 디자인 시스템(Components)
- 목업은 **참고 자료**이며 스펙이 우선한다. 목업에서 정한 내용은 동작으로 풀어서 spec에 다시 적는다.

## 디자인 토큰 (WCAG 2.2 AA 검증 완료, 전체는 `docs/design/tokens.md`)

primary #0a2463 / foreground #1e1b18 / secondary #fffaff / info #3e92cc(채움·테두리·아이콘, 글자는 #285f86) / destructive #d8315b(채움), #b82a4d(글자·호버) / 보조 글자 #6b6560 / 입력 테두리 #8a8480 / 포커스 링 primary 2px 불투명 + 간격 2px / success #17713f(글자 #0f5c36) / warning #a16207(글자 #7a4a00) / 어두운 면 #1e1b18 위 #fffaff. 버튼과 입력 높이는 44px 이상.

## 스펙 현황

`docs/specs/INDEX.md`를 본다.
