# 목업 매크로

`docs/design/mockups/*.dc.html`은 목업 도구의 원본(소스)입니다. 아래 표기는 목업을 만들 때 쓴 매크로이며, 실제 구현에서는 일반 마크업으로 바꿉니다.

| 표기 | 뜻 |
|---|---|
| `[[icon:이름 클래스]]` | Iconoir 아이콘(regular, 선 두께 1.5). 구현에서는 `iconoir` 패키지의 같은 이름 아이콘을 쓴다. 클래스를 안 쓰면 `size-5` |
| `[[navbar 화면이름]]` | 로그인 후 모든 화면의 공통 상단 메뉴바. 아래 마크업 참조 |
| `[[head 제목]]`, `[[script ...]]`, `[[end]]` | 목업 도구용 문서 머리말·스크립트 경계. 구현에서는 무시 |
| `{{값}}`, `<sc-if>`, `<sc-for>` | 목업 도구의 데이터 바인딩과 조건·반복. 구현에서는 Svelte의 `{값}`, `{#if}`, `{#each}`로 바꾼다 |
| `data-state="active\|inactive"` | 탭 선택 상태. shadcn-svelte의 Tabs `data-state`와 같다 |
| `aria-checked` + `.switch` | 스위치. shadcn-svelte의 Switch로 대체 |

스크립트 블록(`class Component extends DCLogic`)은 화면의 **상태와 동작**을 보여 주는 참고용입니다. `state`가 화면 상태, `renderVals()`가 화면에 쓰는 값과 핸들러입니다.

## 공통 상단 메뉴바 (`[[navbar]]`)

```html
<header class="relative flex h-16 items-center justify-between gap-4 border-b bg-background px-6 sm:px-8">
  <div class="flex min-w-0 items-center gap-2">
    <a href="Courses.dc.html" class="flex min-h-11 items-center gap-2 text-sm font-semibold text-foreground no-underline">[[icon:presentation size-5]]강의 상호작용 도구</a>
    <!-- 선택: 현재 화면 이름. [[navbar 설정]]처럼 쓰면 "> 설정"이 붙는다 -->
  </div>
  <div class="relative">
    <button aria-haspopup="true" aria-expanded="{{menuOpen}}" onClick="{{toggleMenu}}" class="btn btn-outline rounded-full pl-2 pr-3">
      <span class="avatar size-8"><span class="avatar-fallback">교</span></span>
      @your-github-id
      [[icon:nav-arrow-down size-4]]
    </button>
    <sc-if value="{{menuOpen}}" hint-placeholder-val="{{ false }}">
      <div class="menu absolute right-0 top-14 w-60">
        <div class="menu-label">@your-github-id<div class="text-xs font-normal text-muted-foreground">GitHub 계정</div></div>
        <div class="menu-separator"></div>
        <a href="MyPage.dc.html" class="menu-item">[[icon:user]]마이페이지</a>
        <a href="Settings.dc.html" class="menu-item">[[icon:settings]]설정</a>
        <div class="menu-separator"></div>
        <a href="Login.dc.html" class="menu-item menu-item-destructive">[[icon:log-out]]로그아웃</a>
      </div>
    </sc-if>
  </div>
</header>
```

계정 드롭다운(마이페이지, 설정, 로그아웃)은 강좌 목록, 마이페이지, 설정, 관리 페이지에 똑같이 있고, 수업 중 화면(교수 수업 화면, 보조 화면, 프로젝터, 학생 화면)에는 없다.
