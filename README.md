# 스펙 주도 개발 키트 (가벼운 버전)

Claude Code에서 쓰는 스펙 주도 개발 틀입니다. 외부 도구 없이 마크다운 템플릿과 프로젝트 스킬 5개로 운영합니다.

## 설치

1. 이 폴더의 `.claude/`, `docs/`, `CLAUDE.md`를 프로젝트 저장소 루트에 복사합니다.
2. **Claude Code를 다시 시작합니다.** 저장소에 `.claude/skills/` 폴더가 처음 생겼다면 재시작해야 스킬이 인식됩니다.
3. 대화에서 `/sdd-spec`을 입력해 스킬 목록에 나오는지 확인합니다.

스킬 이름에 `sdd-` 접두어를 붙인 것은 Claude Code의 기본 제공 스킬과 이름이 겹치면 프로젝트 스킬이 조용히 덮어쓰기 때문입니다.

## 구성

```
CLAUDE.md                       프로젝트 개요, 확정 스택, 항상 지킬 규칙 (Claude가 매번 읽음)
docs/constitution.md            원칙 C1~C17 + 필수 회귀 테스트 (사용자만 수정)
docs/templates/                 spec.md, plan.md, tasks.md 템플릿
docs/specs/INDEX.md             스펙 목록과 단계별 상태
docs/design/                    화면 설명(screens.md), 토큰(tokens.md), theme.css, 목업 원본
docs/workflow.md                GitHub Flow + SDD 작업 방식 (브랜치, 커밋, PR, GitHub 설정 체크리스트)
.github/                        PR 템플릿, 이슈 템플릿, CI(ci.yml), dependabot.yml
scripts/sdd-check.py            스펙 규칙 자동 점검 (CI의 sdd-check)
docs/specs/000-prototype-validation/README.md   plan의 가정을 확인하는 실험 목록
.claude/skills/                 /sdd-spec /sdd-plan /sdd-tasks /sdd-analyze /sdd-implement
```

## 작업 방식

GitHub Flow를 씁니다. 스펙·계획·작업 문서와 구현 작업마다 브랜치 하나, Draft PR 하나입니다. 승인(`status: approved`)은 Draft PR 안에서 사용자가 직접 하며, `sdd-check`가 이를 CI에서 점검합니다. **먼저 `docs/workflow.md`의 "GitHub에서 직접 설정할 것"을 한 번 해 주세요.**

## 진행 순서

스펙 하나마다 아래를 끝낸 뒤 다음 스펙으로 갑니다.

| 단계 | 호출 | 산출물 | 사용자가 할 일 |
|---|---|---|---|
| 1 | `/sdd-spec 001-classroom-entry` | spec.md (질문에 먼저 답함) | 읽고 `status: approved` |
| 2 | `/sdd-plan 001-classroom-entry` | plan.md | 읽고 `status: approved` |
| 3 | `/sdd-tasks 001-classroom-entry` | tasks.md | 읽고 `status: approved` |
| 4 | `/sdd-analyze 001-classroom-entry` | 점검 보고 (파일 수정 없음) | 문제 있으면 고치게 함 |
| 5 | `/sdd-implement 001-classroom-entry` | 작업 하나 구현 | 결과 확인 후 "계속" |

- 모든 스킬은 `disable-model-invocation: true`라서 사용자가 직접 입력할 때만 실행됩니다.
- **`approved`로 바꾸는 것은 사용자의 유일한 관문입니다.** 스킬은 스스로 바꾸지 않습니다.
- spec을 고치면 plan, tasks가 `stale`이 되어 다시 검토해야 합니다.
- 구현 중 스펙에 없는 필요가 생기면 `change-requests.md`에 제안이 쌓이고, 다음 `/sdd-spec` 때 반영합니다.

## 권장 순서

1. `docs/specs/000-prototype-validation/README.md`의 실험부터 합니다(Slidev 동기화, 200명 동시 제출, 재접속 복구 등). 결과 표를 채우고 plan에서 참조합니다.
2. M1 스펙 4개를 001 → 004 순서로 진행합니다.
3. 001을 끝낸 직후, 템플릿과 스킬에서 불편했던 점을 고칩니다. (스킬은 코드처럼 버전 관리하고 검토합니다.)

## 한계

- 승인 관문은 CI(`sdd-check`)가 일부 강제하지만, GitHub 브랜치 규칙을 설정하지 않으면 CI를 우회해 머지할 수 있습니다. 규칙 설정은 직접 해야 합니다.
- `sdd-check`는 status와 순서, 승인 커밋의 Claude 공동 작성자 표시만 봅니다. 스펙의 내용이 좋은지는 판단하지 못합니다.
- 스킬의 정확한 인식 방식은 Claude Code 버전에 따라 다를 수 있습니다. 동작하지 않으면 현재 버전의 스킬 문서를 확인하세요.
