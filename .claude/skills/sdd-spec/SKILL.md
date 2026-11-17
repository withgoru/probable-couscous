---
name: sdd-spec
description: 스펙을 만든다. 모호한 점을 먼저 질문하고, 사용자의 답을 받은 뒤 docs/specs/<id>/spec.md를 작성한다. 사용자가 /sdd-spec <스펙 id>로 호출할 때만 쓴다.
argument-hint: <스펙 id> [한 줄 설명]
disable-model-invocation: true
---

# /sdd-spec

스펙 하나를 만든다. 목표는 "완성되었을 때 무엇이 참이어야 하는가"를 **관찰할 수 있는 동작**으로 적는 것이다.

## 상태 규칙 (모든 sdd 스킬 공통)

- 문서 맨 위 frontmatter의 `status`는 `draft`, `approved`, `stale` 중 하나다.
- **`approved`로 바꾸는 사람은 사용자뿐이다.** 절대 스스로 바꾸지 않는다.
- 앞 단계 문서가 바뀌면 그 아래 단계는 `stale`로 바꾼다. 예: spec을 고치면 plan.md와 tasks.md를 `stale`로 바꾼다.
- `docs/specs/INDEX.md`의 해당 행도 함께 갱신한다.

## 순서

1. **읽기**: `docs/constitution.md`, `docs/templates/spec.md`, `CLAUDE.md`, `docs/specs/INDEX.md`, `depends_on`에 해당하는 스펙, `docs/specs/000-prototype-validation/README.md`, 관련 화면이 있으면 `docs/design/screens.md`를 읽는다.
2. **의존 확인**: `depends_on` 스펙이 `approved`가 아니면 어떤 스펙이 비어 있는지 알리고 멈춘다.
3. **질문 먼저**: 모호한 점과 빠진 결정을 우선순위 순서로 질문 목록(최대 7개)으로 정리해 사용자에게 보여주고 **답을 기다린다**. 답을 받기 전에는 spec.md를 쓰지 않는다. 사용자가 이미 말한 내용은 다시 묻지 않는다. 가능한 질문은 선택지를 함께 제시한다.
4. **작성**: 답을 받은 뒤 `docs/specs/<id>/spec.md`를 템플릿대로 쓴다. 폴더가 없으면 만든다. `status: draft`로 둔다.
   - 시나리오는 "누가·언제 / 무엇을 제공하나 / 완료할 작업"으로 쓴다.
   - 수용 기준(AC)은 번호를 붙이고, 사람이 화면에서 확인할 수 있는 문장으로 쓴다.
   - 실패했을 때의 동작(constitution C12 대체 경로 포함)을 반드시 쓴다.
   - 관련 화면 이름을 `screens`에 적는다(`docs/design/screens.md` 참조). 목업의 동작은 그대로 베끼지 말고 관찰 가능한 문장으로 다시 쓴다. 목업과 사용자 답이 다르면 사용자 답을 따른다.
5. **금지**: 프레임워크, 테이블, API 경로, 라이브러리 이름, 코드. 이런 내용이 필요해 보이면 plan으로 미룬다고 적는다.
6. **constitution 점검**: 스펙이 원칙과 충돌하면 쓰기를 멈추고 어느 원칙과 어떻게 충돌하는지 보고한다. 관련 원칙은 "constitution 영향" 절에 적는다.
7. **마무리**: 짧게 보고한다(AC 개수, 남은 미결정 질문, 충돌 여부). "읽고 확인한 뒤 `status: approved`로 바꿔 주세요. 그다음 /sdd-plan <id>를 실행합니다."라고 안내한다.

## 이미 spec.md가 있는 경우

제자리에서 고친다. 이전 status가 `approved`였다면 `draft`로 내리고 plan.md, tasks.md를 `stale`로 바꾼다. 무엇을 바꿨는지 보고한다.

## Git 규칙 (GitHub Flow)

- main에서 직접 작업하지 않는다. 시작할 때 현재 브랜치가 main이면 `spec/<번호>-<이름>` 브랜치를 만든다(먼저 `git switch main`과 원격 최신 확인). 다른 브랜치에 있으면 그 브랜치가 이 작업용이 맞는지 사용자에게 확인한다.
- 끝나면 `docs(<번호>): spec 작성` 형식으로 커밋하고 push한 뒤 **Draft PR**을 연다. `gh`가 있으면 `gh pr create --draft`, 없으면 제목과 본문(`.github/PULL_REQUEST_TEMPLATE.md` 형식)을 출력한다.
- **머지, `status: approved` 변경, main에 직접 push, force push는 하지 않는다.** 이 PR은 사용자가 읽고 직접 approved로 바꾼 뒤 Ready로 전환해 합친다.
