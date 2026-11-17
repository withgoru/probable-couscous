---
name: sdd-tasks
description: 승인된 계획을 작업 목록으로 쪼갠다. docs/specs/<id>/tasks.md에 의존 순서, 먼저 쓸 테스트, 완료 기준, AC 대응표를 쓴다. 사용자가 /sdd-tasks <스펙 id>로 호출할 때만 쓴다.
argument-hint: <스펙 id>
disable-model-invocation: true
---

# /sdd-tasks

승인된 계획을 혼자 검토할 수 있는 크기의 작업으로 나눈다.

## 상태 규칙

`approved`는 사용자만 설정한다. 앞 단계가 바뀌면 아래 단계는 `stale`로 바꾼다. INDEX.md도 갱신한다.

## 순서

1. **확인**: spec.md와 plan.md가 모두 `approved`가 아니면 멈추고 알린다.
2. **읽기**: `docs/constitution.md`, spec.md, plan.md, `docs/templates/tasks.md`.
3. **작성**: `docs/specs/<id>/tasks.md`를 템플릿대로 쓴다. `status: draft`.
   - 작업 하나는 한 번에 검토할 수 있는 크기로 쪼갠다. 한 작업이 여러 AC를 한꺼번에 바꾸면 더 쪼갠다.
   - 의존 순서로 정렬한다. 의존이 있으면 명시한다.
   - 작업마다 **먼저 쓸 테스트**(실패해야 하는 테스트)와 **완료 기준**을 쓴다.
   - constitution의 필수 회귀 테스트가 이 스펙에 해당하면 별도 작업으로 먼저 둔다.
   - 모든 AC가 하나 이상의 작업에 대응되게 하고, 맨 아래 "AC 대응표"를 채운다. 대응되지 않는 AC가 있으면 멈추고 보고한다.
4. **금지**: 설계 논의, 스펙에 없는 작업.
5. **마무리**: 짧게 보고한다(작업 수, 첫 작업). "읽고 `status: approved`로 바꿔 주세요. 그다음 /sdd-analyze <id>로 점검하거나 /sdd-implement <id>로 시작합니다."라고 안내한다.

## Git 규칙 (GitHub Flow)

- main에서 직접 작업하지 않는다. 시작할 때 현재 브랜치가 main이면 `tasks/<번호>-<이름>` 브랜치를 만든다(먼저 `git switch main`과 원격 최신 확인). 다른 브랜치에 있으면 그 브랜치가 이 작업용이 맞는지 사용자에게 확인한다.
- 끝나면 `docs(<번호>): tasks 작성` 형식으로 커밋하고 push한 뒤 **Draft PR**을 연다. `gh`가 있으면 `gh pr create --draft`, 없으면 제목과 본문(`.github/PULL_REQUEST_TEMPLATE.md` 형식)을 출력한다.
- **머지, `status: approved` 변경, main에 직접 push, force push는 하지 않는다.** 이 PR은 사용자가 읽고 직접 approved로 바꾼 뒤 Ready로 전환해 합친다.
