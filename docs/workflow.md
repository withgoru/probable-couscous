# 작업 방식: GitHub Flow + 스펙 주도 개발

GitHub Flow를 그대로 씁니다. **main은 언제나 수업에 쓸 수 있는 상태**이고, 모든 변경은 짧게 사는 브랜치와 PR을 거칩니다. 스펙 주도 개발(SDD)의 승인 관문은 PR 안에서 이루어집니다.

## 한눈에 보기

```
main ──●──────────────●──────────────●──▶
        \            /  \           /
         spec/001 ──●    feat/001-T001 ──●   (PR → 검토 → squash merge → 브랜치 삭제)
```

1. main에서 브랜치를 만든다.
2. 커밋하고 push한 뒤 **Draft PR**을 연다.
3. CI와 자기 검토(PR 체크리스트)를 거친다.
4. Draft를 풀고(Ready) **Squash and merge**로 합친다.
5. 브랜치는 지운다.

## SDD 단계와 PR의 대응

| 단계 | 브랜치 | PR 제목 | 머지 조건 |
|---|---|---|---|
| spec | `spec/<번호>-<이름>` | `docs(001): spec 작성` | 사용자가 읽고 spec.md의 status를 **직접** approved로 바꿈, CI 통과 |
| plan | `plan/<번호>-<이름>` | `docs(001): plan 작성` | 동일 |
| tasks | `tasks/<번호>-<이름>` | `docs(001): tasks 작성` | 동일 |
| 구현 | `feat/<번호>-T<nnn>-<요약>` | `feat(001): T003 이메일 인증 코드 발송` | 테스트와 CI 통과, tasks.md에서 해당 작업 체크, AC 대조, 사용자 확인 |
| 버그 | `fix/<요약>` | `fix: ...` | 재현 테스트 추가 후 통과 |
| 기타 | `chore/…`, `docs/…`, `ci/…` | `chore: ...` | CI 통과 |

- **main에는 draft 상태의 문서가 들어갈 수 없습니다.** draft는 Draft PR 안에서만 존재합니다. 승인은 "Draft PR에서 검토 → 사용자가 status를 approved로 바꾸는 커밋 → Ready로 전환 → 머지"입니다.
- 구현 브랜치는 spec, plan, tasks가 모두 approved일 때만 CI를 통과합니다. 승인 전 구현은 CI가 막습니다.
- 스펙을 고치는 PR이 머지되면 plan과 tasks가 stale이 됩니다. 열려 있던 구현 PR은 CI에서 멈추므로, 다시 승인될 때까지 기다립니다.

## 브랜치

- 이름 형식은 위 표를 따릅니다. 번호는 스펙 번호 3자리(`001`), 요약은 영문 소문자와 하이픈.
- main에서 따서 **며칠 안에** 합칩니다. 오래 열어 두지 않습니다.
- 합친 브랜치는 자동으로 지웁니다(저장소 설정).
- 프로토타입 코드는 `proto/<이름>` 브랜치에 두고 main에 합치지 않습니다. 끝나면 태그(`proto-<이름>-v1`)를 붙이고 브랜치를 지웁니다. 결과는 `docs/specs/000-prototype-validation/README.md`에만 남깁니다.

## 커밋과 PR 제목

Conventional Commits 형식입니다. 범위에는 스펙 번호를 씁니다.

```
feat(001): T003 이메일 인증 코드 발송
fix(003): 코드 유예 시간 경계에서 출석이 거부되는 문제
docs(001): spec 작성
test(004): 작성자 확인 사유 필수 회귀 테스트
chore: 의존성 갱신
```

- 유형: `feat`, `fix`, `docs`, `test`, `refactor`, `chore`, `ci`.
- 한 PR은 한 작업(또는 한 문서)입니다. 크면 작업을 쪼갭니다.
- 머지는 **Squash and merge**만 씁니다. PR 제목이 main의 커밋 메시지가 되므로 제목 형식을 지킵니다.

## 이슈와 마일스톤

- 마일스톤 `M1`, `M2`, `M3`을 만들어 스펙 단위 이슈를 묶고 싶을 때만 씁니다. 작업 목록의 원본은 `tasks.md`입니다(이슈로 복제하지 않습니다).
- **스펙 변경 제안**과 **버그**는 이슈 템플릿으로 올립니다. 라벨은 `spec-change`, `bug`.
- 구현 중 스펙에 없는 필요가 생기면 구현하지 않고 `spec-change` 이슈로 올립니다(GitHub CLI가 없으면 `docs/specs/<id>/change-requests.md`).

## CI가 점검하는 것

| 작업 | 내용 |
|---|---|
| `sdd-check` | `scripts/sdd-check.py`. status 값, draft 금지(Draft PR 제외), 앞 단계 승인 순서, 구현 브랜치의 승인 상태와 작업 체크, **Claude가 approved로 바꾼 커밋 탐지** |
| `server` | 서버 린트와 테스트(필수 회귀 테스트 제외) |
| `client` | 클라이언트 린트, 타입 검사, 테스트, 빌드 |
| `constitution-tests` | constitution의 필수 회귀 테스트만 따로 실행(`pytest -m constitution`, `npm run test:constitution`) |

`server/`, `client/` 폴더가 아직 없으면 해당 작업은 건너뛰고 통과합니다. 필수 회귀 테스트는 해당 기능이 만들어지는 스펙에서 먼저 작성하고, 반드시 `constitution` 표시(마커)를 붙입니다.

## Claude Code가 해도 되는 것 / 안 되는 것

| 해도 됨 | 하면 안 됨 |
|---|---|
| 브랜치 생성, 커밋, push | main에 직접 push |
| Draft PR 열기, 본문 작성 | PR 머지 |
| 문서와 코드 작성, 테스트 실행 | `status: approved`로 변경 |
| `spec-change` 이슈 제안 | force push, 브랜치 보호 규칙 변경 |
| tasks.md 체크 | 시크릿·토큰을 커밋에 포함 |

Claude가 만든 커밋에는 공동 작성자 표시가 붙을 수 있고, `approved` 변경 커밋에 그 표시가 있으면 CI가 실패합니다. 승인 변경은 사용자가 직접 커밋하세요.

## GitHub에서 직접 설정할 것 (한 번만)

CI와 규칙 파일은 저장소에 들어 있지만, **아래 설정은 GitHub 웹 화면에서 직접 해야 합니다.** 화면 이름은 GitHub가 바꾸기도 하니 설정 화면에서 확인하세요.

1. **저장소 일반 설정**: 머지 방식은 Squash만 허용, 머지 후 브랜치 자동 삭제 켜기.
2. **브랜치 규칙(Rulesets)** → 기본 브랜치(main) 대상:
   - Require a pull request before merging (필요한 승인 수는 **0**: 혼자 쓸 때 본인 PR은 본인이 승인할 수 없다. 대신 PR 체크리스트로 자기 검토), 대화 해결 필수
   - Require status checks to pass: `sdd-check`, `server`, `client`, `constitution-tests`
   - Block force pushes, Restrict deletions
   - Require linear history (Squash만 쓰므로 가능)
   - 우회 허용 목록은 **비워서** 본인도 규칙을 따르게 한다
3. **보안**: Dependabot alerts와 security updates 켜기. 갱신 PR은 CI와 변경 내용을 확인한 뒤 합칩니다.
4. **라벨과 마일스톤**: 라벨 `spec-change`, `bug`, 마일스톤 `M1`, `M2`, `M3`.
5. **GitHub CLI**: Claude Code가 PR을 열려면 `gh auth login`이 필요합니다. 없으면 Claude Code가 PR 제목과 본문만 출력합니다.

## 배포 (미결정)

GitHub Flow는 "main은 배포 가능"을 전제로 합니다. 이 프로젝트는 수업 중에 서비스가 바뀌면 안 되므로 아래를 제안합니다. 확정은 plan이나 별도 결정으로 합니다.

- 배포는 머지와 분리합니다. 태그(`v2026.11.17-1` 형식)를 만들고 **수동 실행**으로 배포합니다.
- **수업 시간에는 배포하지 않습니다**(constitution C18). 되돌리기는 이전 태그로 다시 배포합니다.
- 배포 대상(개인 서버, 클라우드 등)과 방법은 아직 정하지 않았습니다.
