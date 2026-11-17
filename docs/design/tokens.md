# 디자인 토큰

`theme.css`가 정의의 원본입니다. 값은 WCAG 2.2 AA 대비를 계산해 확인했습니다(일반 글자 4.5:1, 큰 글자와 UI 구성요소 3:1).

## 기본

| 토큰 | 값 | 용도 | 대비 |
|---|---|---|---|
| background / card / popover | #ffffff | 페이지, 카드 | foreground 17.1 |
| foreground | #1e1b18 | 본문 글자 | 흰 17.1, secondary 16.6 |
| primary / primary-foreground | #0a2463 / #fffaff | 주요 버튼, 링크, 활성 탭, 포커스 링 | 14.1 |
| secondary | #fffaff | 보조 버튼 배경 (흰색과 1.03이라 **반드시 테두리 병행**) | |
| muted | #f4eff3 | 탭 바탕, 연한 영역 | foreground 15.1 |
| accent | #eaf3fa | 호버, 선택 틴트 | foreground 15.3 |
| muted-foreground | #6b6560 | 보조 글자 | 흰 5.74, muted 5.06 |
| border | #e6e0e4 | 카드, 구분선 (장식용, 식별에 필요한 경계에는 쓰지 않음) | |
| input | #8a8480 | 입력·보조 버튼 테두리 | 흰 3.69, secondary 3.58 |
| ring | #0a2463 | 포커스 링: 불투명 2px + 간격 2px | 흰 14.5 |

## 상태·강조

| 토큰 | 값 | 용도 | 대비 |
|---|---|---|---|
| destructive | #d8315b | 오류·종료 채움, 아이콘, 테두리 | 흰 글자 4.66 |
| destructive-strong | #b82a4d | 오류 글자, 호버 | 흰 6.04, 분홍 틴트 5.21 |
| info | #3e92cc | 채움·테두리·아이콘. 위 글자는 foreground | foreground 5.05, 흰 3.39(UI만) |
| info-tint / info-text | #e2eff7 / #285f86 | 교수 메시지 배경, 정보 글자 | foreground 14.6, 글자 5.84 |
| success / success-text / success-tint | #17713f / #0f5c36 / #e7f5ee | 출석, 완료 | 채움 흰 6.05, 글자 7.18 |
| warning / warning-text / warning-tint | #a16207 / #7a4a00 / #fff6dc | 출석코드, 읽기 전용 | 채움 흰 4.92, 글자 6.94 |
| inverse / inverse-foreground / inverse-muted | #1e1b18 / #fffaff / #b9b2ad | 슬라이드·프로젝터 배경과 글자 | 16.6 / 8.2 |

## 사용 규칙

- **info는 흰 배경 위 글자로 쓰지 않는다.** 글자가 필요하면 `info-text`. 흰 글자를 info 배경 위에 쓰지 않는다(3.39).
- **destructive 호버와 오류 글자는 `destructive-strong`.** shadcn 기본(배경을 밝게)을 쓰면 흰 글자 대비가 4.09로 떨어진다.
- 포커스 링은 `focus-visible:ring-2 ring-ring ring-offset-2`. shadcn 기본의 반투명(`ring-ring/50`)은 쓰지 않는다.
- 상태(성공, 경고, 오류, 정보)는 색만으로 전달하지 않고 **아이콘과 문구를 함께** 쓴다.
- 버튼과 입력 높이는 44px 이상(`h-11`), 큰 버튼은 48px(`h-12`). 학생 모바일의 출석코드·인증코드 입력은 72px.
- 다크 테마는 정하지 않았다.

## 글자

- 글꼴: Inter(영문, 숫자) + 한글은 시스템 폰트(Apple SD Gothic Neo, Malgun Gothic, Noto Sans CJK KR). 코드 숫자는 IBM Plex Mono, `tabular-nums`.
- 크기: 페이지 제목 `text-3xl font-bold`, 섹션 제목 `text-2xl font-semibold`, 카드 제목 `font-semibold`, 본문·컨트롤 `text-sm`, 보조 `text-xs text-muted-foreground`.
- 프로젝터 화면은 뒷줄에서 읽히도록 본문 30~36px, 제목 60~72px.

## shadcn-svelte 컴포넌트 대응

| 목업 클래스 | shadcn-svelte |
|---|---|
| `.btn` + `.btn-default/secondary/outline/ghost/destructive/link`, `.btn-lg`, `.btn-icon` | Button (variant, size) |
| `.input`, `.textarea`, `.label`, `.select` | Input, Textarea, Label, Select |
| `.card`, `.card-header/title/description/content/footer` | Card |
| `.badge` + `-default/secondary/outline/destructive/success/warning/info` | Badge (success, warning, info는 변형 추가) |
| `.tabs-list` + `.tabs-trigger` / `.tabs-line` + `.tabs-line-trigger` | Tabs (밑줄형은 변형 추가) |
| `.switch`, `.switch-thumb` | Switch |
| `.alert` + `-destructive/warning/info` | Alert |
| `.avatar`, `.avatar-fallback` | Avatar |
| `.table` | Table |
| `.menu`, `.menu-item`, `.menu-label`, `.menu-separator` | DropdownMenu |
| `.progress`, `.progress-bar` | Progress |
| `.dialog` | Dialog |
| `.separator` | Separator |

shadcn 기본에서 바꾼 점: 높이 44px 이상, 포커스 링 불투명, 입력 테두리·보조 글자색 진하게, 호버 destructive-strong. 컴포넌트를 가져온 뒤 이 값들을 다시 적용한다.
