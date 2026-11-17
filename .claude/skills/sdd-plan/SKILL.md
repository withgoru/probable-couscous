---
name: sdd-plan
description: 승인된 스펙으로 기술 계획을 만든다. docs/specs/<id>/plan.md에 기술 선택, 데이터 모델, 인터페이스, 위험, constitution 점검을 쓴다. 사용자가 /sdd-plan <스펙 id>로 호출할 때만 쓴다.
argument-hint: <스펙 id>
disable-model-invocation: true
---

# /sdd-plan

승인된 스펙을 "어떻게 만들 것인가"로 바꾼다. 요구사항을 다시 쓰지 않는다.

## 상태 규칙

`approved`는 사용자만 설정한다. 앞 단계가 바뀌면 아래 단계는 `stale`로 바꾼다. INDEX.md도 갱신한다. (자세한 규칙은 /sdd-spec 참조)

## 순서

1. **확인**: `docs/specs/<id>/spec.md`의 status가 `approved`가 아니면 멈추고 알린다.
2. **읽기**: `docs/constitution.md`, `CLAUDE.md`(확정된 기술 스택), spec.md, `docs/templates/plan.md`, `docs/specs/000-prototype-validation/README.md`의 결과, 이미 approved된 다른 스펙의 plan.md(데이터 모델과 인터페이스 일관성), 화면이 걸린 스펙이면 `docs/design/screens.md`, `tokens.md`, `theme.css`.
3. **작성**: `docs/specs/<id>/plan.md`를 템플릿대로 쓴다. `status: draft`.
   - 기술 선택은 CLAUDE.md의 스택을 따른다. 바꾸려면 이유를 "기술 선택과 근거"에 쓰고 사용자에게 알린다.
   - 데이터 모델: 모든 테이블에 강의실 식별자(C5), 활동 기록에 이메일 금지(C7), 이벤트는 추가만(C6).
   - 권한 판단은 단일 함수를 통한다(C8).
   - 확인되지 않은 가정은 "위험과 검증"에 쓰고, 필요하면 000-prototype-validation에 항목을 추가하자고 제안한다. **추측으로 확정하지 않는다.**
   - 새 의존성은 constitution C17 절차(다운로드 수, 최신 갱신, 버전 고정)로 확인한 결과를 적는다.
   - 필수 회귀 테스트 중 이 스펙이 만드는 것을 "테스트 전략"에 적는다.
4. **constitution 점검 표**를 원칙별로 채운다. 충족할 수 없는 원칙이 있으면 멈추고 보고한다.
5. **금지**: 스펙의 시나리오나 AC를 그대로 옮겨 적는 것, 코드 구현.
6. **마무리**: 짧게 보고한다(핵심 선택, 남은 위험, 점검 결과). "읽고 `status: approved`로 바꿔 주세요. 그다음 /sdd-tasks <id>를 실행합니다."라고 안내한다.

## Git 규칙 (GitHub Flow)

- main에서 직접 작업하지 않는다. 시작할 때 현재 브랜치가 main이면 `plan/<번호>-<이름>` 브랜치를 만든다(먼저 `git switch main`과 원격 최신 확인). 다른 브랜치에 있으면 그 브랜치가 이 작업용이 맞는지 사용자에게 확인한다.
- 끝나면 `docs(<번호>): plan 작성` 형식으로 커밋하고 push한 뒤 **Draft PR**을 연다. `gh`가 있으면 `gh pr create --draft`, 없으면 제목과 본문(`.github/PULL_REQUEST_TEMPLATE.md` 형식)을 출력한다.
- **머지, `status: approved` 변경, main에 직접 push, force push는 하지 않는다.** 이 PR은 사용자가 읽고 직접 approved로 바꾼 뒤 Ready로 전환해 합친다.
