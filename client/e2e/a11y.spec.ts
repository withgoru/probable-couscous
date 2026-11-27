import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { expect, test, type Page } from '@playwright/test';
import { checkFocused, expectNoAxeViolations, expectNoHorizontalScroll, noTransitions, tabTo, unique, type FocusIssue } from './a11y-helpers';
import { classroomWith, lastCode, requestCode, student, typeCode } from './helpers';

// T034(AC50, AC51, C14): 키보드만으로 끝까지 가는지, 지나가는 모든 요소의 포커스 링과 44px, 390px 가로 스크롤,
// 그리고 axe로 화면마다 WCAG 2.2 AA 자동 점검.
const DESKTOP = { width: 1280, height: 800 };
const PHONE = { width: 390, height: 844 };
// 슬라이드 템플릿으로 빌드한 4장짜리 테스트용 묶음(서버 테스트와 같은 파일)
const DECK_ZIP = fileURLToPath(new URL('../../server/tests/fixtures/deck-small.zip', import.meta.url));

test('키보드만으로 교수 로그인 → 강좌 만들기 → 명단 올리기 → 학생 입장을 끝낸다 (AC51)', async ({ browser }) => {
	const issues: FocusIssue[] = [];
	const email = student('keyboard').email;

	// --- 교수: 노트북 화면 ---
	const prof = await (await browser.newContext({ viewport: DESKTOP })).newPage();
	await prof.goto('/login');
	await noTransitions(prof);
	await tabTo(prof, prof.getByRole('link', { name: 'GitHub로 로그인' }), issues);
	await prof.keyboard.press('Enter');
	await prof.waitForURL('**/courses');
	await noTransitions(prof);

	await tabTo(prof, prof.getByRole('button', { name: '새 강좌 만들기' }), issues);
	await prof.keyboard.press('Enter');
	await expect(prof.getByLabel('강좌 이름')).toBeFocused(); // 폼이 열리면 이름 칸으로 간다
	await prof.keyboard.type('키보드 강좌');
	await tabTo(prof, prof.getByRole('button', { name: '만들기', exact: true }), issues);
	await prof.keyboard.press('Enter');
	await expect(prof.getByRole('heading', { level: 2, name: '키보드 강좌' })).toBeVisible();

	await tabTo(prof, prof.getByRole('link', { name: '열기' }).first(), issues);
	await prof.keyboard.press('Enter');
	await expect(prof.getByRole('heading', { level: 1, name: '관리 페이지' })).toBeVisible();
	await noTransitions(prof);

	// CSV 올리기: 파일 칸에서 Space로 파일 선택 창을 연다
	await tabTo(prof, prof.getByLabel('CSV 파일'), issues);
	const chooser = prof.waitForEvent('filechooser');
	await prof.keyboard.press('Space');
	await (await chooser).setFiles({
		name: 'roster.csv',
		mimeType: 'text/csv',
		buffer: Buffer.from(`학번,이름,이메일\n20240001,김철수,${email}\n20240002,이영희,lee-${email}\n`)
	});
	await tabTo(prof, prof.getByRole('button', { name: '올리기' }), issues);
	await prof.keyboard.press('Enter');
	const table = prof.getByRole('region', { name: '수강생 명단 표' });
	await expect(table.getByRole('cell', { name: '김철수', exact: true })).toBeVisible();
	const link = await prof.getByLabel('초대 링크 주소').inputValue();

	// --- 학생: 휴대폰 화면 ---
	const phone = await (await browser.newContext({ viewport: PHONE })).newPage();
	await phone.goto(link);
	await noTransitions(phone);
	await tabTo(phone, phone.getByLabel('이메일'), issues);
	await phone.keyboard.type(email);
	await phone.keyboard.press('Enter');
	await expect(phone.getByRole('heading', { level: 1, name: '인증 코드를 입력하세요' })).toBeVisible();
	await tabTo(phone, phone.getByLabel('인증 코드 6자리'), issues);
	await phone.keyboard.type(await lastCode(email));
	await phone.keyboard.press('Enter');
	await expect(phone.getByRole('region', { name: '채팅 이용 안내' })).toBeVisible();
	await tabTo(phone, phone.getByRole('button', { name: '확인하고 입장' }), issues);
	await phone.keyboard.press('Enter');
	await expect(phone.getByText('입장했습니다')).toBeVisible();

	// --- 교수: 학생이 입장한 것이 명단에 보인다 ---
	await prof.reload();
	await expect(table.getByText('입장함')).toBeVisible();

	expect(unique(issues), '키보드로 지나간 요소의 포커스 링·크기 문제').toEqual([]);
});

/** 화면의 모든 포커스 가능한 요소를 Tab으로 한 바퀴 돌며 점검한다. */
async function tabAround(page: Page, issues: FocusIssue[], max = 80) {
	await page.locator('body').click({ position: { x: 1, y: 1 } }).catch(() => {});
	const seen = new Set<string>();
	for (let i = 0; i < max; i++) {
		await page.keyboard.press('Tab');
		const key = await page.evaluate(() => {
			const el = document.activeElement;
			return el ? `${el.tagName}#${el.id}|${el.getAttribute('aria-label') ?? ''}|${el.textContent?.slice(0, 20)}` : '';
		});
		if (seen.has(key)) break; // 한 바퀴 돌았다
		seen.add(key);
		issues.push(...(await checkFocused(page)));
	}
}

test.describe('교수 화면 (노트북)', () => {
	test.use({ viewport: DESKTOP });

	test('로그인 화면', async ({ page }) => {
		await page.goto('/login');
		await noTransitions(page);
		await expectNoAxeViolations(page, '로그인');
		await expectNoHorizontalScroll(page, '로그인');
		const issues: FocusIssue[] = [];
		await tabAround(page, issues);
		expect(unique(issues)).toEqual([]);
	});

	test('내 강좌, 새 강좌 폼, 보관 확인 창, 마이페이지, 관리 페이지, 빼기 확인 창', async ({ page, context }) => {
		const room = await classroomWith([student('a11y'), student('a11y', '이영희', '20240002')], '접근성 강좌');
		// 같은 브라우저로 교수 로그인(가짜 GitHub)
		await page.goto('/api/auth/github/login');
		await page.waitForURL('**/courses');
		await noTransitions(page);
		const issues: FocusIssue[] = [];

		await expectNoAxeViolations(page, '내 강좌');
		await tabAround(page, issues);
		await page.getByRole('button', { name: '새 강좌 만들기' }).click();
		await expectNoAxeViolations(page, '새 강좌 폼');
		await page.getByRole('button', { name: '취소' }).click();

		await page.getByRole('button', { name: /^보관: 접근성 강좌/ }).click();
		await expect(page.getByRole('alertdialog')).toBeVisible();
		await expectNoAxeViolations(page, '보관 확인 창');
		await page.keyboard.press('Escape');

		await page.goto('/mypage');
		await noTransitions(page);
		await expectNoAxeViolations(page, '마이페이지');
		await tabAround(page, issues);

		// 관리 페이지: 입장 요청과 대기 중인 인증이 하나씩 있는 상태
		const s = await (await context.browser()!.newContext()).newPage();
		await s.goto(`/join/${room.token}`);
		await s.request.post(`/api/join/${room.token}/request-access`, {
			headers: { Origin: new URL(page.url()).origin },
			data: { email: student('req').email, name: '박민수', student_no: '9' }
		});
		await page.goto(`/courses/${room.id}/admin`);
		await noTransitions(page);
		await expect(page.getByText('박민수')).toBeVisible();
		await expectNoAxeViolations(page, '관리 페이지');
		await tabAround(page, issues, 120);
		await page.getByRole('button', { name: /^빼기: / }).first().click();
		await expect(page.getByRole('alertdialog')).toBeVisible();
		await expectNoAxeViolations(page, '빼기 확인 창');
		await page.keyboard.press('Escape');

		// 회차 선택(002 AC1~AC4): 키보드만으로 만들고, 목록을 열고, 지우기 확인 창까지 간다
		await page.getByRole('button', { name: '회차 만들기' }).focus();
		await page.keyboard.press('Enter');
		await page.keyboard.type('1주차 1회차');
		await page.keyboard.press('Enter');
		const picker = page.getByRole('button', { name: /^회차 선택: 1주차 1회차/ });
		await expect(picker).toBeVisible();
		await expectNoAxeViolations(page, '회차를 만든 관리 페이지');
		// 슬라이드 없이 시작하려 하면 먼저 묻는다(AC9). 여기서는 취소한다
		await page.getByRole('button', { name: '수업 시작' }).click();
		await expect(page.getByRole('alertdialog')).toContainText('슬라이드 없이 시작할까요?');
		await expectNoAxeViolations(page, '슬라이드 없이 시작 확인 창');
		await page.keyboard.press('Escape');
		// 이 회차의 자료(AC5): 테스트용 묶음을 올린다
		await page.getByLabel('슬라이드 묶음(zip) 올리기').setInputFiles(DECK_ZIP);
		const materials = page.getByRole('region', { name: '이 회차의 자료' });
		await expect(materials.getByText('업로드됨')).toBeVisible();
		await expect(materials.getByText('슬라이드 4장')).toBeVisible();
		await expectNoAxeViolations(page, '묶음을 올린 관리 페이지');
		// 학생에게 공개(AC47): 키보드만으로 켠다
		const publicSwitch = page.getByRole('switch', { name: '학생에게 공개' });
		await publicSwitch.focus();
		issues.push(...(await checkFocused(page))); // 포커스 링과 눌리는 범위(44px)
		await page.keyboard.press('Space');
		await expect(publicSwitch).toHaveAttribute('aria-checked', 'true');
		await expect(materials.getByText('공개 · 학생이 언제든 처음부터 끝까지 볼 수 있습니다.')).toBeVisible();
		await expectNoAxeViolations(page, '슬라이드를 공개한 관리 페이지');
		if (process.env.E2E_SHOTS) await page.screenshot({ path: `${process.env.E2E_SHOTS}/session-picker.png`, fullPage: true });
		await picker.focus();
		await page.keyboard.press('Enter');
		await expect(page.getByRole('menuitemradio', { name: /1주차 1회차/ })).toBeVisible();
		await expectNoAxeViolations(page, '회차 선택 목록');
		if (process.env.E2E_SHOTS) await page.screenshot({ path: `${process.env.E2E_SHOTS}/session-menu.png` });
		await page.keyboard.press('Escape');
		await page.getByRole('button', { name: '삭제', exact: true }).click();
		await expect(page.getByRole('alertdialog')).toContainText('1주차 1회차 회차를 삭제할까요? 올린 슬라이드도 함께 지워집니다.');
		await expectNoAxeViolations(page, '회차 삭제 확인 창');
		await tabAround(page, issues, 40);

		expect(unique(issues), '교수 화면의 포커스 링·크기 문제').toEqual([]);
	});
});

test.describe('학생 화면 (390px)', () => {
	test.use({ viewport: PHONE });

	test('이메일, 명단 밖 안내, 입장 요청, 코드, 안내, 입장 완료, 닫힌 링크', async ({ page }) => {
		const kim = student('kim');
		const room = await classroomWith([kim], '학생 접근성 강좌');
		const issues: FocusIssue[] = [];
		const check = async (screen: string) => {
			await noTransitions(page);
			await expectNoAxeViolations(page, screen);
			await expectNoHorizontalScroll(page, screen);
			await tabAround(page, issues);
		};

		await page.goto(`/join/${room.token}`);
		await check('이메일 단계');
		await page.getByLabel('이메일').fill('kim@');
		await page.getByRole('button', { name: '인증 코드 받기' }).click();
		await check('이메일 형식 오류');

		await page.getByLabel('이메일').fill(student('stranger').email);
		await page.getByRole('button', { name: '인증 코드 받기' }).click();
		await expect(page.getByRole('button', { name: '입장 요청 보내기' })).toBeVisible();
		await check('명단 밖 안내');
		await page.getByRole('button', { name: '입장 요청 보내기' }).click();
		await check('입장 요청 폼');
		await page.getByRole('button', { name: '요청 보내기' }).click(); // 빈 칸 → 서버 안내
		await expect(page.getByText('학번을 입력해 주세요.')).toBeVisible(); // 서버는 칸 순서(학번 → 이름)대로 첫 오류를 준다
		await check('입장 요청 폼 오류');

		await page.getByRole('button', { name: '이메일 다시 입력' }).click();
		await page.getByLabel('이메일').fill(kim.email);
		await page.getByRole('button', { name: '인증 코드 받기' }).click();
		await expect(page.getByLabel('인증 코드 6자리')).toBeVisible();
		await check('코드 단계');
		await page.getByLabel('인증 코드 6자리').fill('12');
		await page.getByRole('button', { name: '확인하고 계속' }).click();
		await check('코드 단계 오류');

		await page.getByLabel('인증 코드 6자리').fill(await lastCode(kim.email));
		await page.getByRole('button', { name: '확인하고 계속' }).click();
		await expect(page.getByRole('region', { name: '채팅 이용 안내' })).toBeVisible();
		await check('채팅 이용 안내');
		await page.getByRole('button', { name: '확인하고 입장' }).click();
		await expect(page.getByText('입장했습니다')).toBeVisible();
		await check('입장 완료');

		await page.goto('/join/not-a-real-link');
		await check('닫힌 링크');

		expect(unique(issues), '학생 화면의 포커스 링·크기 문제').toEqual([]);
	});
});

// --- 002 T029(AC45, C14): 회차 관리·교수 수업 화면·프로젝터·학생 수업 화면 ----------------------------------------
// 키보드만으로 수업을 시작하고 넘기고 보내고 거두며, 학생은 이전·다음·교수 화면으로·복사를 키보드로 한다.
// 지나가는 모든 요소의 포커스 링과 44px, axe, iframe 제목, 학생 화면 390px 가로 넘침을 본다.

async function classroomWithDeck(title: string, publish: boolean) {
	const kim = student('a11y-class');
	const room = await classroomWith([kim], `접근성 수업 ${Date.now()}`);
	const session = await (await room.api.post(`/api/classrooms/${room.id}/sessions`, { data: { title } })).json();
	const upload = await room.api.put(`/api/classrooms/${room.id}/sessions/${session.id}/deck?filename=deck.zip`, {
		headers: { 'Content-Type': 'application/zip' },
		data: readFileSync(DECK_ZIP)
	});
	expect(upload.status(), await upload.text()).toBe(200);
	if (publish) await room.api.put(`/api/classrooms/${room.id}/sessions/${session.id}/deck/visibility`, { data: { public: true } });
	const state = async () => (await room.api.get(`/api/class/${room.id}/sessions/${session.id}/live`)).json();
	return { ...room, sessionId: session.id as number, student: kim, state };
}

/** 화면의 모든 iframe에 제목이 있다(화면 낭독기가 무엇인지 읽는다). */
async function expectTitledFrames(page: Page, screen: string) {
	const untitled = await page.locator('iframe').evaluateAll((frames) => frames.filter((f) => !f.getAttribute('title')?.trim()).length);
	expect(untitled, `${screen}: 제목 없는 iframe`).toBe(0);
}

/** 슬라이드가 그 위치를 그려 넘길 수 있게 될 때까지 기다린다(그 전에 누르면 화면이 받지 않는다). */
async function ready(page: Page, name: string) {
	await expect(page.getByRole('button', { name, exact: true })).toHaveAttribute('aria-disabled', 'false');
}

test.describe('002 수업 화면 (AC45)', () => {
	test('교수: 키보드만으로 수업 시작 → 넘기기 → 보내기·거두기 → 프로젝터 열기', async ({ browser }) => {
		const issues: FocusIssue[] = [];
		const room = await classroomWithDeck('6주차 1회차', false);
		const context = await browser.newContext({ viewport: DESKTOP });
		const prof = await context.newPage();
		await prof.goto('/api/auth/github/login');
		await prof.waitForURL('**/courses');
		await prof.goto(`/courses/${room.id}/admin`);
		await noTransitions(prof);
		await expectNoAxeViolations(prof, '회차와 묶음이 있는 관리 페이지');
		await tabAround(prof, issues, 80); // 회차 선택, 이 회차의 자료, 수업 시작 등 지나가는 모든 요소

		// 회차 관리: 학생에게 공개 스위치와 수업 시작(AC47, AC9)
		await tabTo(prof, prof.getByRole('switch', { name: '학생에게 공개' }), issues);
		await prof.keyboard.press('Space');
		await expect(prof.getByRole('switch', { name: '학생에게 공개' })).toHaveAttribute('aria-checked', 'true');
		await expect.poll(async () => (await room.state()).deck.public).toBe(true);
		await tabTo(prof, prof.getByRole('button', { name: '수업 시작' }), issues);
		await prof.keyboard.press('Enter');
		await expect(prof).toHaveURL(new RegExp(`/courses/${room.id}/live$`));
		await noTransitions(prof);

		// 교수 수업 화면: 다음 버튼을 Enter로, 그다음은 →키로 넘긴다(AC13)
		await ready(prof, '다음');
		await tabTo(prof, prof.getByRole('button', { name: '다음', exact: true }), issues);
		await prof.keyboard.press('Enter');
		await expect.poll(async () => (await room.state()).current).toEqual({ slide: 2, click: 0 });
		await ready(prof, '다음');
		await prof.keyboard.press('ArrowRight');
		await expect.poll(async () => (await room.state()).current).toEqual({ slide: 2, click: 1 });
		await expectTitledFrames(prof, '교수 수업 화면');
		await expectNoAxeViolations(prof, '교수 수업 화면');

		// 슬라이드 안으로 Tab해 들어가면 링이 보이고(checkFocused), 그 안에서 →를 눌러도 넘어간다(AC13)
		await tabTo(prof, prof.getByTitle('현재 슬라이드'), issues);
		await ready(prof, '다음');
		await prof.keyboard.press('ArrowRight');
		await expect.poll(async () => (await room.state()).current).toEqual({ slide: 2, click: 2 });

		// 보내기와 거두기(AC31, AC35). 글 칸에서는 →가 넘기기가 아니다
		await tabTo(prof, prof.getByLabel('글'), issues);
		await prof.keyboard.type('키보드로 보낸 안내');
		await prof.keyboard.press('ArrowRight');
		await tabTo(prof, prof.getByRole('button', { name: '학생에게 보내기' }), issues);
		await prof.keyboard.press('Enter');
		await expect.poll(async () => (await room.state()).items.map((i: { body: string }) => i.body)).toEqual(['키보드로 보낸 안내']);
		expect((await room.state()).current).toEqual({ slide: 2, click: 2 }); // 글 칸의 →는 넘기지 않았다(보내기가 끝난 뒤에도)
		await tabTo(prof, prof.getByRole('button', { name: '거두기: 키보드로 보낸 안내' }), issues);
		await prof.keyboard.press('Enter');
		const dialog = prof.getByRole('alertdialog');
		await expect(dialog).toBeVisible();
		await expectNoAxeViolations(prof, '거두기 확인 창');
		await tabTo(prof, dialog.getByRole('button', { name: '거두기' }), issues, 10);
		await prof.keyboard.press('Enter');
		await expect.poll(async () => (await room.state()).items[0].retracted_at).not.toBeNull();
		await tabAround(prof, issues, 60);

		// 프로젝터 화면(AC19): Enter로 열고, 슬라이드에 제목이 있으며 전체 화면 버튼에 이름이 있다
		await tabTo(prof, prof.getByRole('button', { name: '프로젝터 화면 열기' }), issues);
		const popup = context.waitForEvent('page');
		await prof.keyboard.press('Enter');
		const projector = await popup;
		await noTransitions(projector);
		await expect(projector.getByTitle('슬라이드')).toBeVisible();
		await expectTitledFrames(projector, '프로젝터 화면');
		await expectNoAxeViolations(projector, '프로젝터 화면');
		await tabTo(projector, projector.getByRole('button', { name: '전체 화면' }), issues, 10);

		// 수업 종료 확인 창(AC37)
		await tabTo(prof, prof.getByRole('button', { name: '수업 종료' }), issues);
		await prof.keyboard.press('Enter');
		await expect(prof.getByRole('alertdialog')).toContainText('수업을 끝낼까요?');
		await expectNoAxeViolations(prof, '수업 종료 확인 창');
		await prof.keyboard.press('Escape');
		await expect(prof.getByRole('button', { name: '수업 종료' })).toBeFocused(); // 초점이 돌아온다

		expect(unique(issues), '교수 수업 화면의 포커스 링·크기 문제').toEqual([]);
		await context.close();
	});

	test('학생(390px): 키보드만으로 이전·다음, 교수 화면으로, 복사', async ({ browser }) => {
		const issues: FocusIssue[] = [];
		const room = await classroomWithDeck('6주차 2회차', true);
		await room.api.post(`/api/classrooms/${room.id}/sessions/${room.sessionId}/start`);
		await room.api.post(`/api/classrooms/${room.id}/sessions/${room.sessionId}/items`, {
			data: { body: '키보드로 복사할 글', client_key: 'k1' }
		});
		const context = await browser.newContext({ viewport: PHONE });
		await context.grantPermissions(['clipboard-read', 'clipboard-write']);
		const phone = await context.newPage();
		await requestCode(phone, room.token, room.student.email);
		await typeCode(phone, await lastCode(room.student.email));
		await phone.getByRole('button', { name: '확인하고 입장' }).click();
		await expect(phone.getByText('교수 화면 따라가는 중')).toBeVisible();
		await noTransitions(phone);
		await expectTitledFrames(phone, '학생 수업 화면');
		await expectNoAxeViolations(phone, '학생 수업 화면');
		await expectNoHorizontalScroll(phone, '학생 수업 화면');

		// 다음을 Enter로 누르면 따라가기가 풀리고 넘어간다(AC26)
		await ready(phone, '다음');
		await tabTo(phone, phone.getByRole('button', { name: '다음', exact: true }), issues);
		await phone.keyboard.press('Enter');
		await expect(phone.getByText('직접 넘겨 보는 중 · 교수 화면은 1번 슬라이드입니다.')).toBeVisible();
		await expect(phone.getByRole('button', { name: '다음', exact: true })).toBeFocused(); // 초점을 잃지 않는다
		await ready(phone, '이전');
		await tabTo(phone, phone.getByRole('button', { name: '이전', exact: true }), issues);
		await phone.keyboard.press('Enter');
		await expectNoAxeViolations(phone, '직접 넘겨 보는 학생 화면');
		await expectNoHorizontalScroll(phone, '직접 넘겨 보는 학생 화면');

		// 교수 화면으로(AC28): 누른 버튼이 사라지면 초점은 넘기기 버튼으로 간다
		await tabTo(phone, phone.getByRole('button', { name: '교수 화면으로' }), issues);
		await phone.keyboard.press('Enter');
		await expect(phone.getByText('교수 화면 따라가는 중', { exact: true })).toBeVisible();
		await expect(phone.getByRole('button', { name: '다음', exact: true })).toBeFocused();

		// 복사(AC34)
		await tabTo(phone, phone.getByRole('button', { name: '복사: 키보드로 복사할 글' }), issues);
		await phone.keyboard.press('Enter');
		await expect(phone.getByRole('list', { name: '자료' }).getByText('복사했습니다.')).toBeVisible();
		expect(await phone.evaluate(() => navigator.clipboard.readText())).toBe('키보드로 복사할 글');
		await tabAround(phone, issues, 40);

		expect(unique(issues), '학생 수업 화면의 포커스 링·크기 문제').toEqual([]);
		await context.close();
	});

	test('학생(390px): 대기 화면, 미리 보기, 다시 보기', async ({ browser }) => {
		const issues: FocusIssue[] = [];
		const room = await classroomWithDeck('7주차 1회차', true); // 공개 묶음이 있는 예정 회차 → 미리 보기
		const ended = await (await room.api.post(`/api/classrooms/${room.id}/sessions`, { data: { title: '6주차 3회차' } })).json();
		await room.api.post(`/api/classrooms/${room.id}/sessions/${ended.id}/start`);
		await room.api.post(`/api/classrooms/${room.id}/sessions/${ended.id}/items`, { data: { body: '지난 자료', client_key: 'p1' } });
		await room.api.post(`/api/classrooms/${room.id}/sessions/${ended.id}/end`);
		const context = await browser.newContext({ viewport: PHONE });
		const phone = await context.newPage();
		await requestCode(phone, room.token, room.student.email);
		await typeCode(phone, await lastCode(room.student.email));
		await phone.getByRole('button', { name: '확인하고 입장' }).click();
		await expect(phone.getByRole('heading', { name: '미리 볼 수 있는 회차' })).toBeVisible();
		await noTransitions(phone);
		await expectNoAxeViolations(phone, '미리 볼 수 있는 회차와 지난 회차가 있는 대기 화면');
		await expectNoHorizontalScroll(phone, '대기 화면');
		await tabAround(phone, issues, 30);

		// 미리 보기: 키보드로 열고, 슬라이드 안으로 들어가면 링이 보인다
		await tabTo(phone, phone.getByRole('button', { name: '7주차 1회차 미리 보기' }), issues);
		await phone.keyboard.press('Enter');
		await expect(phone.getByRole('heading', { level: 1, name: '7주차 1회차 미리 보기' })).toBeFocused();
		await expectTitledFrames(phone, '미리 보기');
		await expectNoAxeViolations(phone, '미리 보기');
		await expectNoHorizontalScroll(phone, '미리 보기');
		await tabTo(phone, phone.getByTitle('미리 보는 슬라이드'), issues);
		await tabTo(phone, phone.getByRole('button', { name: '회차 목록으로' }), issues);
		await phone.keyboard.press('Enter');

		// 다시 보기
		await tabTo(phone, phone.getByRole('button', { name: '6주차 3회차 다시 보기' }), issues);
		await phone.keyboard.press('Enter');
		await expect(phone.getByRole('heading', { level: 1, name: '6주차 3회차 다시 보기' })).toBeFocused();
		await expect(phone.getByText('이 회차는 슬라이드 없이 진행했습니다.')).toBeVisible(); // 묶음 없이 진행한 회차
		await expect(phone.getByRole('list', { name: '자료' })).toContainText('지난 자료');
		await expectNoAxeViolations(phone, '다시 보기');
		await expectNoHorizontalScroll(phone, '다시 보기');
		await tabAround(phone, issues, 30);

		expect(unique(issues), '대기·미리 보기·다시 보기의 포커스 링·크기 문제').toEqual([]);
		await context.close();
	});
});
