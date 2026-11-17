## 무엇을 하나요

<!-- 한두 문장. 제목은 영어 Conventional Commits 형식: `docs(001): write spec` 또는 `feat(001): T003 send email verification code` -->

## 관련 문서

- 스펙: `docs/specs/<번호>-<이름>/spec.md`
- 작업: T___ (구현 PR일 때)
- 관련 이슈: closes #

## 변경 유형

- [ ] 스펙·계획·작업 문서 (`docs`)
- [ ] 기능 구현 (`feat`)
- [ ] 버그 수정 (`fix`)
- [ ] 기타 (`chore`, `ci`, `test`)

## 문서 PR일 때

- [ ] 내가 직접 읽었고, `status`를 내가 직접 `approved`로 바꿨다 (Claude가 바꾸지 않았다)
- [ ] Draft PR에서 검토했고, 이제 Ready로 바꾼다

## 구현 PR일 때: 수용 기준 대조

| AC | 확인한 방법 (테스트 이름 또는 화면에서 확인한 동작) |
|---|---|
| AC1 | |

## constitution 점검

- [ ] 관련된 원칙(C번호): ___ 를 지켰다
- [ ] 필수 회귀 테스트가 통과한다
- [ ] 스펙에 없는 동작을 넣지 않았다 (필요하면 `Type: Spec Change` 이슈로 올렸다)
- [ ] UI가 있으면 대비, 포커스 링, 터치 영역 44px을 확인했다 (C14)
- [ ] 새 의존성이 있으면 다운로드 수와 최신 갱신을 확인했고 버전을 고정했다 (C17)

## 머지 전

- [ ] CI(`sdd-check`, `server`, `client`, `constitution-tests`)가 모두 통과했다
- [ ] Squash and merge로 합친다 (제목이 곧 main의 커밋 메시지)
