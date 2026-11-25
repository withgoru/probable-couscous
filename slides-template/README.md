# 수업 슬라이드 템플릿

수업 도구에 올릴 슬라이드 묶음(zip)을 만드는 Slidev 프로젝트입니다. 교수 컴퓨터에서만 씁니다. 서버와 CI는 이 폴더를 빌드하지 않습니다.

## 처음 한 번

Node 22 이상이 필요합니다.

```bash
cd slides-template
npm ci
```

## 슬라이드 만들기

- 이 폴더의 `slides.md`를 고치거나, 다른 폴더에 강의마다 `slides.md`를 둡니다. 그림 같은 파일은 그 `slides.md` 옆에 둡니다.
- **맨 위 머리말(`---` 사이)은 템플릿 `slides.md`의 것을 그대로 둡니다.** 특히 아래 세 줄이 없으면 묶음을 만들지 않습니다.

```yaml
routerMode: hash        # 수업 도구 안에서 열리려면 필요
fonts:
  provider: none        # 외부 글꼴을 부르지 않는다(학생 기기가 외부로 나가지 않고, 교실 인터넷이 없어도 열린다)
favicon: false          # 외부 아이콘을 부르지 않는다
```

- 발표자 노트(`<!-- ... -->`)는 교수 수업 화면에만 보이고 학생과 프로젝터에는 가지 않습니다.
- 미리 보기: `npm run dev` (이 폴더의 `slides.md`), 다른 폴더는 `npx slidev ../강의/3주차/slides.md`

## 묶음 만들기

```bash
npm run build:classroom
```

```bash
npm run build:classroom -- ../강의/3주차/slides.md --out 3주차.zip
```

만든 zip을 수업 도구의 관리 페이지 '이 회차의 자료'에서 올립니다.

## 주의

- **슬라이드에 외부 스크립트나 다른 사이트의 코드를 넣지 마세요.** 슬라이드는 수업 도구와 같은 주소에서 열려, 슬라이드 안의 코드가 학생의 로그인 상태로 동작할 수 있습니다(002 plan 위험 6).
- 수업 화면과 이어 주는 다리(`setup/root.ts`)는 묶음을 만들 때 항상 이 템플릿의 것으로 넣습니다. 슬라이드 폴더에 같은 이름의 파일이 있어도 바뀝니다.
- 학생은 교수가 보여 준 곳까지만 넘겨 볼 수 있지만, 화면에서 막는 것이라 묶음 파일 자체에는 모든 슬라이드가 들어 있습니다(002 plan 위험 5). 끝까지 숨겨야 하는 내용은 슬라이드에 넣지 마세요.

## 개발용

- `npm run build:fixture`: 서버 테스트가 쓰는 4장짜리 묶음(`server/tests/fixtures/deck-small.zip`)을 `fixture/slides.md`로 다시 만듭니다. 같은 입력이면 같은 zip이 나옵니다. 다리나 Slidev 버전을 바꾸면 다시 만들어 커밋합니다.
- lockfile은 npm 10으로 만듭니다(`npx -y npm@10.9.4 install`).
