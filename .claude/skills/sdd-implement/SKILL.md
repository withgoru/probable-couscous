---
name: sdd-implement
description: 승인된 작업 목록에서 작업 하나를 테스트 먼저 방식으로 구현한다. 한 번에 한 작업만 하고 AC와 constitution을 대조해 보고한다. 사용자가 /sdd-implement <스펙 id> [작업 id]로 호출할 때만 쓴다.
argument-hint: <스펙 id> [작업 id]
disable-model-invocation: true
---

# /sdd-implement

작업 하나를 구현한다. 한 번 호출에 **작업 하나만** 한다. 사용자가 "계속"이라고 하기 전에는 다음 작업으로 넘어가지 않는다.

## 순서

1. **확인**: spec.md, plan.md, tasks.md가 모두 `approved`가 아니면 멈추고 알린다. 작업 id가 없으면 tasks.md에서 의존이 모두 끝난 첫 미완료 작업을 고르고, 어떤 작업인지 먼저 알린다.
2. **읽기**: `docs/constitution.md`, 해당 스펙의 spec/plan/tasks, 작업이 건드릴 기존 코드.
3. **작업 재진술**: 이 작업이 만족시킬 AC, 관련 원칙, 완료 기준을 3줄로 적는다.
4. **테스트 먼저**: "먼저 쓸 테스트"를 작성하고 **실행해서 실패하는 것을 확인**한다. 실패 출력을 보여준다.
5. **구현**: 테스트를 통과시키는 최소한의 코드를 쓴다. 범위 밖의 개선, 리팩터링, 추가 기능은 하지 않는다.
6. **검증**: 전체 테스트를 실행한다. 관련 constitution 필수 회귀 테스트가 있으면 반드시 포함한다. 접근성(C14)이 걸린 UI는 대비, 포커스, 터치 영역을 점검한다.
7. **기록**: tasks.md에서 해당 작업을 체크하고 INDEX.md를 갱신한다.
8. **커밋과 PR**: 아래 "Git 규칙"대로 커밋하고 Draft PR을 연다. PR 본문의 "수용 기준 대조" 표를 채운다.
9. **보고**: 아래 형식으로 짧게 보고하고 멈춘다.

```
작업 T00N 완료
- 만족한 AC: AC1, AC2 (각각 어떤 동작/테스트로 확인했는지 한 줄)
- constitution: C2, C7 이상 없음 (또는 문제)
- 변경한 파일: ...
- 다음 작업: T00M (의존 충족 여부)
```

## 중단 조건 (멈추고 사용자에게 보고)

- constitution 원칙을 어겨야 하는 경우. 우회하지 않는다.
- 스펙에 없는 동작이 필요해 보이는 경우. 구현하지 않고 "스펙 변경 제안"으로 올린다(`gh`가 있으면 `Type: Spec Change` 이슈, 없으면 `docs/specs/<id>/change-requests.md`에 필요한 이유와 제안 AC를 적는다). 그리고 보고한다.
- 계획과 현실이 어긋나는 경우(예: 선택한 라이브러리가 요구를 못 채움). 임의로 바꾸지 않고 보고한다.
- 테스트를 통과시키려고 테스트를 약하게 고쳐야 하는 경우.

## Git 규칙 (GitHub Flow)

- main에서 직접 작업하지 않는다. 시작할 때 현재 브랜치가 main이면 `feat/<번호>-T<nnn>-<요약>` 브랜치를 만든다(먼저 `git switch main`과 원격 최신 확인). 다른 브랜치에 있으면 그 브랜치가 이 작업용이 맞는지 사용자에게 확인한다.
- 끝나면 `feat(<번호>): T<nnn> <요약>` 형식으로 커밋하고 push한 뒤 **Draft PR**을 연다. `gh`가 있으면 `gh pr create --draft`, 없으면 제목과 본문(`.github/PULL_REQUEST_TEMPLATE.md` 형식)을 출력한다.
- **머지, `status: approved` 변경, main에 직접 push, force push는 하지 않는다.** 이 PR은 사용자가 읽고 직접 approved로 바꾼 뒤 Ready로 전환해 합친다.
- 작업을 시작하기 전에 spec, plan, tasks가 모두 approved인지 확인한다. 아니면 CI(`sdd-check`)가 실패한다.
- 구현 PR은 한 작업만 담는다. 범위가 커지면 멈추고 작업을 쪼개자고 제안한다.
