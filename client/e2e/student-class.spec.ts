import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { expect, test, type Page } from '@playwright/test';
import { expectNoAxeViolations, expectNoHorizontalScroll, noTransitions } from './a11y-helpers';
import { controlSockets } from './class-helpers';
import { classroomWith, lastCode, requestCode, student, typeCode } from './helpers';

// 002 T023: 입장한 학생의 수업 화면. 수업이 없으면 대기, 교수가 시작하면 새로 고치지 않고 수업 화면이 되고
// 교수가 넘기면 따라간다(AC23~AC25, AC29, AC30). 학생 화면은 390px(AC24).
const DECK_ZIP = fileURLToPath(new URL('../../server/tests/fixtures/deck-small.zip', import.meta.url));
const PHONE = { width: 390, height: 844 };
test.use({ viewport: PHONE });

async function enter(page: Page, token: string, email: string) {
	await requestCode(page, token, email);
	await typeCode(page, await lastCode(email));
	await page.getByRole('button', { name: '확인하고 입장' }).click();
	await expect(page.getByText('입장했습니다')).toBeVisible();
}

async function slideOf(page: Page): Promise<string> {
	return page.frameLocator('iframe[title="수업 슬라이드"]').locator('body').evaluate(() => location.hash);
}

test('대기하다가 수업이 시작되면 수업 화면이 되고, 교수가 넘기면 따라간다', async ({ page }) => {
	const kim = student('class');
	const room = await classroomWith([kim], `학생 수업 ${Date.now()}`);
	const session = await (await room.api.post(`/api/classrooms/${room.id}/sessions`, { data: { title: '3주차 1회차' } })).json();
	expect(
		(
			await room.api.put(`/api/classrooms/${room.id}/sessions/${session.id}/deck?filename=deck.zip`, {
				headers: { 'Content-Type': 'application/zip' },
				data: readFileSync(DECK_ZIP)
			})
		).status()
	).toBe(200);

	await enter(page, room.token, kim.email);
	await noTransitions(page);
	await expect(page.getByText('지금 진행 중인 수업이 없습니다. 수업이 시작되면 이 화면이 바뀝니다.')).toBeVisible();
	await expect(page.getByText('아직 끝난 회차가 없습니다.')).toBeVisible();
	await expectNoAxeViolations(page, '학생 대기 화면');

	// 교수가 수업을 시작하고 자료를 하나 보낸다: 학생 화면은 새로 고치지 않고 바뀐다(AC23)
	expect((await room.api.post(`/api/classrooms/${room.id}/sessions/${session.id}/start`)).status()).toBe(200);
	await room.api.post(`/api/classrooms/${room.id}/sessions/${session.id}/items`, { data: { body: '오늘 실습 안내', client_key: 'e2e1' } });
	await expect(page.getByTitle('수업 슬라이드')).toBeVisible();
	await expect(page.getByText('교수 화면 따라가는 중')).toBeVisible();
	await expect(page.getByRole('list', { name: '자료' })).toContainText('오늘 실습 안내'); // AC29
	await expect.poll(() => slideOf(page)).toMatch(/^#\/1/);
	await expect(page.getByText(/노트/)).toHaveCount(0); // AC30: 화면에도
	await expect(page.frameLocator('iframe[title="수업 슬라이드"]').locator('body')).not.toContainText('노트'); // 슬라이드 안에도
	await expectNoAxeViolations(page, '학생 수업 화면');
	await expectNoHorizontalScroll(page, '학생 수업 화면');

	// 교수가 넘기면 따라간다(AC25). 넘기기는 수업 WebSocket으로 보낸다
	const professor = await page.context().browser()!.newContext();
	const teacher = await professor.newPage();
	await teacher.goto('/api/auth/github/login');
	await teacher.waitForURL('**/courses');
	await teacher.goto(`/courses/${room.id}/live`);
	const next = teacher.getByRole('button', { name: '다음' });
	await expect(next).toHaveAttribute('aria-disabled', 'false');
	await next.click();
	await expect.poll(() => slideOf(page)).toMatch(/^#\/2/);

	// 교수가 빠르게 두 번 넘겨도(2번 슬라이드의 단계 1, 2) 학생이 뒤처지지 않는다
	await expect(next).toHaveAttribute('aria-disabled', 'false');
	await next.click();
	await expect(next).toHaveAttribute('aria-disabled', 'false');
	await next.click();
	await expect.poll(() => slideOf(page)).toMatch(/^#\/2\?clicks=2/);
	await professor.close();
});

test('수업 중에 들어온 학생은 교수의 현재 위치에서 시작한다 (AC29)', async ({ page }) => {
	const lee = student('late');
	const room = await classroomWith([lee], `늦게 온 학생 ${Date.now()}`);
	const session = await (await room.api.post(`/api/classrooms/${room.id}/sessions`, { data: { title: '4주차' } })).json();
	await room.api.put(`/api/classrooms/${room.id}/sessions/${session.id}/deck?filename=deck.zip`, {
		headers: { 'Content-Type': 'application/zip' },
		data: readFileSync(DECK_ZIP)
	});
	await room.api.post(`/api/classrooms/${room.id}/sessions/${session.id}/start`);
	// 교수 화면으로 3번 슬라이드까지 넘겨 둔다
	const professor = await page.context().browser()!.newContext();
	const teacher = await professor.newPage();
	await teacher.goto('/api/auth/github/login');
	await teacher.waitForURL('**/courses');
	await teacher.goto(`/courses/${room.id}/live`);
	for (let i = 0; i < 5; i += 1) {
		const next = teacher.getByRole('button', { name: '다음' });
		await expect(next).toHaveAttribute('aria-disabled', 'false');
		await next.click();
	}
	await expect.poll(async () => (await (await room.api.get(`/api/class/${room.id}/sessions/${session.id}/live`)).json()).current).toEqual({ slide: 3, click: 0 });
	await professor.close();

	await requestCode(page, room.token, lee.email);
	await typeCode(page, await lastCode(lee.email));
	await page.getByRole('button', { name: '확인하고 입장' }).click();
	await expect(page.getByText('교수 화면 따라가는 중')).toBeVisible();
	await expect.poll(() => slideOf(page)).toMatch(/^#\/3/);
});

test('넘기면 따라가기가 풀리고, 교수보다 앞으로도 넘겨 보며, 교수 화면으로 다시 따라간다 (AC26, AC28)', async ({ page }) => {
	const park = student('browse');
	const room = await classroomWith([park], `직접 넘겨 보기 ${Date.now()}`);
	const session = await (await room.api.post(`/api/classrooms/${room.id}/sessions`, { data: { title: '5주차' } })).json();
	await room.api.put(`/api/classrooms/${room.id}/sessions/${session.id}/deck?filename=deck.zip`, {
		headers: { 'Content-Type': 'application/zip' },
		data: readFileSync(DECK_ZIP)
	});
	// 공개 묶음이라 교수보다 앞으로도 넘겨 본다(AC26, AC47). 비공개 묶음의 따라가기만은 T035
	await room.api.put(`/api/classrooms/${room.id}/sessions/${session.id}/deck/visibility`, { data: { public: true } });
	await room.api.post(`/api/classrooms/${room.id}/sessions/${session.id}/start`);
	const professor = await page.context().browser()!.newContext();
	const teacher = await professor.newPage();
	await teacher.goto('/api/auth/github/login');
	await teacher.waitForURL('**/courses');
	await teacher.goto(`/courses/${room.id}/live`);
	const teacherNext = teacher.getByRole('button', { name: '다음' });
	async function professorNext() {
		await expect(teacherNext).toHaveAttribute('aria-disabled', 'false');
		await teacherNext.click();
	}
	await professorNext(); // 교수: 2번 슬라이드 0단계

	await enterLive(page, room.token, park.email);
	await expect.poll(() => slideOf(page)).toMatch(/^#\/2$/);

	// 교수보다 앞으로도 넘겨 볼 수 있다(가장 멀리 간 위치 제한이 없어졌다, 2026-11-26). 다음을 누르면 따라가기가 풀린다(AC26)
	const studentNext = page.getByRole('button', { name: '다음' });
	const studentPrev = page.getByRole('button', { name: '이전' });
	await expect(studentNext).toHaveAttribute('aria-disabled', 'false');
	await studentNext.click();
	await expect.poll(() => slideOf(page)).toMatch(/^#\/2\?clicks=1/);
	await expect(page.getByText('직접 넘겨 보는 중 · 교수 화면은 2번 슬라이드입니다.')).toBeVisible();
	await expect(page.getByText('교수님이 아직 보여 주지 않은 슬라이드입니다.')).toHaveCount(0);

	// 이전으로 1번까지 돌아간다
	await expect(studentPrev).toHaveAttribute('aria-disabled', 'false');
	await studentPrev.click();
	await expect.poll(() => slideOf(page)).toMatch(/^#\/2$/);
	await expect(studentPrev).toHaveAttribute('aria-disabled', 'false');
	await studentPrev.click();
	await expect.poll(() => slideOf(page)).toMatch(/^#\/1/);

	// 교수가 넘겨도 학생 슬라이드는 그대로, 교수 위치 번호만 바뀐다
	await professorNext(); // 2번 1단계
	await professorNext(); // 2번 2단계
	await professorNext(); // 2번 3단계
	await professorNext(); // 3번
	await expect(page.getByText('직접 넘겨 보는 중 · 교수 화면은 3번 슬라이드입니다.')).toBeVisible();
	await expect.poll(() => slideOf(page)).toMatch(/^#\/1/);
	await expectNoAxeViolations(page, '직접 넘겨 보는 학생 화면');

	// '교수 화면으로'를 누르면 교수 위치로 가고 다시 따라간다(AC28)
	await page.getByRole('button', { name: '교수 화면으로' }).click();
	await expect(page.getByText('교수 화면 따라가는 중')).toBeVisible();
	await expect.poll(() => slideOf(page)).toMatch(/^#\/3/);
	await professorNext(); // 4번
	await expect.poll(() => slideOf(page)).toMatch(/^#\/4/);

	// 슬라이드 안에서 ←를 눌러도(애드온이 막고 방향만 알림) 따라가기가 풀리고 한 단계 움직인다
	await page.frameLocator('iframe[title="수업 슬라이드"]').locator('body').press('ArrowLeft');
	await expect(page.getByText('직접 넘겨 보는 중 · 교수 화면은 4번 슬라이드입니다.')).toBeVisible();
	await expect.poll(() => slideOf(page)).toMatch(/^#\/3/);
	await professor.close();
});

async function enterLive(page: Page, token: string, email: string) {
	await requestCode(page, token, email);
	await typeCode(page, await lastCode(email));
	await page.getByRole('button', { name: '확인하고 입장' }).click();
	await expect(page.getByText('교수 화면 따라가는 중')).toBeVisible();
}

test('교수가 보낸 자료가 바로 나타나고 알림이 뜨며, 복사할 수 있고, 거두면 사라진다 (AC33~AC35)', async ({ page, context }) => {
	await context.grantPermissions(['clipboard-read', 'clipboard-write']);
	const choi = student('materials');
	const room = await classroomWith([choi], `자료 받기 ${Date.now()}`);
	const session = await (await room.api.post(`/api/classrooms/${room.id}/sessions`, { data: { title: '6주차' } })).json();
	await room.api.post(`/api/classrooms/${room.id}/sessions/${session.id}/start`);
	await enterLive(page, room.token, choi.email);

	const professor = await page.context().browser()!.newContext();
	const teacher = await professor.newPage();
	await teacher.goto('/api/auth/github/login');
	await teacher.waitForURL('**/courses');
	await teacher.goto(`/courses/${room.id}/live`);
	const panel = teacher.getByRole('region', { name: '메시지·자료 보내기' });
	await panel.getByLabel('글').fill('과제는 금요일까지');
	await panel.getByRole('button', { name: '학생에게 보내기' }).click();
	await panel.getByLabel('글').fill('실습 코드 예시');
	await panel.getByLabel('링크(선택)').fill('https://example.com/lab');
	await panel.getByRole('button', { name: '학생에게 보내기' }).click();

	// 학생: 맨 위에 새 항목, 도착 알림(AC33)
	const list = page.getByRole('list', { name: '자료' });
	await expect(list.getByRole('listitem').first()).toContainText('실습 코드 예시');
	await expect(page.locator('[data-arrival]')).toContainText('교수님이 자료를 보냈습니다.');
	await expectNoAxeViolations(page, '자료를 받은 학생 화면');

	// 복사(AC34)
	await list.getByRole('button', { name: '복사: 과제는 금요일까지' }).click();
	await expect(list.getByText('복사했습니다.')).toBeVisible();
	expect(await page.evaluate(() => navigator.clipboard.readText())).toBe('과제는 금요일까지');
	const link = list.getByRole('link', { name: /https:\/\/example\.com\/lab/ });
	await expect(link).toHaveAttribute('target', '_blank');

	// 거두면 학생 화면에서 사라진다(AC35)
	await panel.getByRole('button', { name: '거두기: 과제는 금요일까지' }).click();
	await teacher.getByRole('alertdialog').getByRole('button', { name: '거두기' }).click();
	await expect(list.getByText('과제는 금요일까지')).toHaveCount(0);
	await expect(list.getByText('실습 코드 예시')).toBeVisible();
	await professor.close();
});

// 002 T026: 수업이 끝나면 새로 고치지 않고 다시 보기로 바뀌고, 지난 회차를 처음부터 다시 볼 수 있다(AC38, AC39)
test('수업이 끝나면 다시 보기로 바뀌고, 지난 회차를 처음부터 다시 본다 (AC38, AC39)', async ({ page }) => {
	const choi = student('replay');
	const room = await classroomWith([choi], `다시 보기 ${Date.now()}`);
	const session = await (await room.api.post(`/api/classrooms/${room.id}/sessions`, { data: { title: '6주차' } })).json();
	await room.api.put(`/api/classrooms/${room.id}/sessions/${session.id}/deck?filename=deck.zip`, {
		headers: { 'Content-Type': 'application/zip' },
		data: readFileSync(DECK_ZIP)
	});
	await room.api.put(`/api/classrooms/${room.id}/sessions/${session.id}/deck/visibility`, { data: { public: true } }); // 다시 보기에서 끝까지(AC39)
	await room.api.post(`/api/classrooms/${room.id}/sessions/${session.id}/start`);
	await room.api.post(`/api/classrooms/${room.id}/sessions/${session.id}/items`, { data: { body: '과제 안내', client_key: 'r1' } });
	// 교수가 2번 슬라이드의 단계 1까지 넘긴다
	const professor = await page.context().browser()!.newContext();
	const teacher = await professor.newPage();
	await teacher.goto('/api/auth/github/login');
	await teacher.waitForURL('**/courses');
	await teacher.goto(`/courses/${room.id}/live`);
	for (let i = 0; i < 2; i += 1) {
		const next = teacher.getByRole('button', { name: '다음' });
		await expect(next).toHaveAttribute('aria-disabled', 'false');
		await next.click();
	}
	await expect
		.poll(async () => (await (await room.api.get(`/api/class/${room.id}/sessions/${session.id}/live`)).json()).current)
		.toEqual({ slide: 2, click: 1 });
	await professor.close();

	await requestCode(page, room.token, choi.email); // 수업 중에 들어오면 바로 수업 화면이다
	await typeCode(page, await lastCode(choi.email));
	await page.getByRole('button', { name: '확인하고 입장' }).click();
	await expect(page.getByText('교수 화면 따라가는 중')).toBeVisible();
	await noTransitions(page);
	await expect.poll(() => slideOf(page)).toMatch(/^#\/2\?clicks=1/);

	await page.getByRole('button', { name: '이전' }).focus(); // 키보드 사용자가 수업 화면 안에 있다
	// 교수가 끝낸다: 새로 고치지 않고 끝났다는 안내와 같은 회차의 다시 보기(AC38)
	expect((await room.api.post(`/api/classrooms/${room.id}/sessions/${session.id}/end`)).status()).toBe(200);
	const endedNotice = page.locator('p:not([data-class-status])', { hasText: '수업이 끝났습니다.' });
	await expect(endedNotice).toBeVisible();
	await expect(page.locator('[data-class-status]')).toHaveText('수업이 끝났습니다.'); // 화면 낭독기에도
	await expect(page.getByRole('heading', { level: 1, name: '6주차 다시 보기' })).toBeFocused(); // 사라진 화면에서 초점을 옮겨 받는다
	const replayHash = () => page.frameLocator('iframe[title="다시 보는 슬라이드"]').locator('body').evaluate(() => location.hash);
	await expect.poll(replayHash).toMatch(/^#\/2\?clicks=1/); // 보던 곳에서 이어 본다
	await expect(page.getByRole('list', { name: '자료' })).toContainText('과제 안내');
	await expect(page.getByRole('button', { name: '다음' })).toHaveAttribute('aria-disabled', 'false'); // 묶음의 끝까지 넘긴다
	await expect(page.getByText('수업에서 보여 주지 않은 슬라이드입니다.')).toHaveCount(0);
	await expectNoAxeViolations(page, '수업이 끝난 뒤 다시 보기');
	await expectNoHorizontalScroll(page, '수업이 끝난 뒤 다시 보기');

	// 목록으로 돌아가 같은 회차를 처음부터 다시 본다(AC39)
	await page.getByRole('button', { name: '지난 회차 목록으로' }).click();
	await expect(page.getByText('지금 진행 중인 수업이 없습니다. 수업이 시작되면 이 화면이 바뀝니다.')).toBeVisible();
	await page.getByRole('button', { name: '6주차 다시 보기' }).click();
	await expect(page.getByRole('heading', { level: 1, name: '6주차 다시 보기' })).toBeFocused();
	await expect(endedNotice).toHaveCount(0);
	await expect.poll(replayHash).toMatch(/^#\/1/);
	const next = page.getByRole('button', { name: '다음' });
	await expect(next).toHaveAttribute('aria-disabled', 'false');
	await next.click();
	await expect.poll(replayHash).toMatch(/^#\/2/);
	await expectNoAxeViolations(page, '지난 회차 다시 보기');
});

// 002 T035: 비공개 묶음은 따라가기만, 수업 중 공개하면 직접 넘겨 보고, 다시 비공개로 바꾸면 교수 화면으로 돌아간다
// (AC27, AC48)
test('비공개 묶음은 따라가기만 하고, 수업 중 공개 여부가 바뀌면 바로 따른다 (AC27, AC48)', async ({ page }) => {
	const han = student('private');
	const room = await classroomWith([han], `비공개 묶음 ${Date.now()}`);
	const session = await (await room.api.post(`/api/classrooms/${room.id}/sessions`, { data: { title: '7주차' } })).json();
	await room.api.put(`/api/classrooms/${room.id}/sessions/${session.id}/deck?filename=deck.zip`, {
		headers: { 'Content-Type': 'application/zip' },
		data: readFileSync(DECK_ZIP)
	});
	await room.api.post(`/api/classrooms/${room.id}/sessions/${session.id}/start`);
	const visibility = (isPublic: boolean) =>
		room.api.put(`/api/classrooms/${room.id}/sessions/${session.id}/deck/visibility`, { data: { public: isPublic } });

	await enterLive(page, room.token, han.email);
	await noTransitions(page);
	// 새 묶음은 비공개: 넘기기 버튼이 없고, 슬라이드 안에서 →를 눌러도 움직이지 않는다(AC27)
	await expect(page.getByText('교수 화면 따라가는 중 · 교수님이 슬라이드를 공개하면 직접 넘겨 볼 수 있습니다.')).toBeVisible();
	await expect(page.getByRole('button', { name: '다음' })).toHaveCount(0);
	await expect.poll(() => slideOf(page)).toMatch(/^#\/1/);
	await page.frameLocator('iframe[title="수업 슬라이드"]').locator('body').press('ArrowRight');
	await page.waitForTimeout(300);
	expect(await slideOf(page)).toMatch(/^#\/1(\?|$)/);
	await expectNoAxeViolations(page, '비공개 묶음을 따라가는 학생 화면');

	// 교수가 수업 중에 공개한다: 이전·다음이 나타나고 끝까지 넘긴다(AC48, AC26)
	expect((await visibility(true)).status()).toBe(200);
	const next = page.getByRole('button', { name: '다음' });
	await expect(next).toBeVisible();
	await expect(next).toHaveAttribute('aria-disabled', 'false');
	await next.click();
	await expect(page.getByText('직접 넘겨 보는 중 · 교수 화면은 1번 슬라이드입니다.')).toBeVisible();
	await expect.poll(() => slideOf(page)).toMatch(/^#\/2/);

	// 다시 비공개로 바꾼다: 교수 위치로 돌아가 따라가고, 안내가 보이며 화면 낭독기에도 읽힌다(AC48)
	expect((await visibility(false)).status()).toBe(200);
	const notice = '교수님이 슬라이드를 비공개로 바꿨습니다. 교수 화면을 따라갑니다.';
	await expect(page.locator('p:not([data-class-status])', { hasText: notice })).toBeVisible();
	await expect(page.locator('[data-class-status]')).toHaveText(notice);
	await expect.poll(() => slideOf(page)).toMatch(/^#\/1(\?|$)/);
	await expect(page.getByRole('button', { name: '다음' })).toHaveCount(0);
	await expectNoAxeViolations(page, '비공개로 바뀐 학생 화면');
});

// 002 T037: 비공개 회차의 다시 보기는 자료만, 교수가 공개하면 새로 고치지 않고 슬라이드가 나타나 끝까지 넘긴다(AC39, AC41)
test('비공개 회차는 자료만 다시 보고, 공개하면 바로 슬라이드를 끝까지 넘겨 본다 (AC39, AC41)', async ({ page }) => {
	const yoon = student('replay-private');
	const room = await classroomWith([yoon], `비공개 다시 보기 ${Date.now()}`);
	const session = await (await room.api.post(`/api/classrooms/${room.id}/sessions`, { data: { title: '8주차' } })).json();
	await room.api.put(`/api/classrooms/${room.id}/sessions/${session.id}/deck?filename=deck.zip`, {
		headers: { 'Content-Type': 'application/zip' },
		data: readFileSync(DECK_ZIP)
	});
	await room.api.post(`/api/classrooms/${room.id}/sessions/${session.id}/start`);
	await room.api.post(`/api/classrooms/${room.id}/sessions/${session.id}/items`, { data: { body: '복습 자료', client_key: 'p1' } });
	await room.api.post(`/api/classrooms/${room.id}/sessions/${session.id}/end`);

	await enter(page, room.token, yoon.email);
	await noTransitions(page);
	await page.getByRole('button', { name: '8주차 다시 보기' }).click();
	await expect(page.getByRole('heading', { level: 1, name: '8주차 다시 보기' })).toBeFocused();
	// 비공개 묶음: 슬라이드 대신 안내, 자료는 보인다(AC39)
	await expect(page.getByText('이 회차의 슬라이드는 공개되지 않았습니다.')).toBeVisible();
	await expect(page.getByTitle('다시 보는 슬라이드')).toHaveCount(0);
	await expect(page.getByRole('list', { name: '자료' })).toContainText('복습 자료');
	await expectNoAxeViolations(page, '비공개 회차 다시 보기');

	// 교수가 공개한다: 새로 고치지 않아도 슬라이드가 나타나고 처음부터 끝까지 넘긴다
	expect(
		(await room.api.put(`/api/classrooms/${room.id}/sessions/${session.id}/deck/visibility`, { data: { public: true } })).status()
	).toBe(200);
	await expect(page.getByTitle('다시 보는 슬라이드')).toBeVisible();
	const replayHash = () => page.frameLocator('iframe[title="다시 보는 슬라이드"]').locator('body').evaluate(() => location.hash);
	await expect.poll(replayHash).toMatch(/^#\/1/);
	const next = page.getByRole('button', { name: '다음' });
	for (const expected of [/^#\/2(\?clicks=0)?$/, /^#\/2\?clicks=1/, /^#\/2\?clicks=2/, /^#\/2\?clicks=3/, /^#\/3/, /^#\/4(\?clicks=0)?$/, /^#\/4\?clicks=1/]) {
		await expect(next).toHaveAttribute('aria-disabled', 'false');
		await next.click();
		await expect.poll(replayHash).toMatch(expected);
	}
	await expect(next).toHaveAttribute('aria-disabled', 'true'); // 묶음의 끝
	await expectNoAxeViolations(page, '공개된 회차 다시 보기');
});

// 002 T036: 공개 묶음이 있는 예정 회차는 대기 화면에서 미리 본다(AC49). 공개 전에는 없고, 공개하면 새로 고치지 않고 나타난다
test('공개한 예정 회차를 대기 화면에서 미리 보고, 그 수업이 시작되면 수업 화면이 된다 (AC49, AC23)', async ({ page }) => {
	const jang = student('preview');
	const room = await classroomWith([jang], `미리 보기 ${Date.now()}`);
	const session = await (await room.api.post(`/api/classrooms/${room.id}/sessions`, { data: { title: '9주차' } })).json();
	await room.api.put(`/api/classrooms/${room.id}/sessions/${session.id}/deck?filename=deck.zip`, {
		headers: { 'Content-Type': 'application/zip' },
		data: readFileSync(DECK_ZIP)
	});

	await enter(page, room.token, jang.email);
	await noTransitions(page);
	await expect(page.getByText('지금 진행 중인 수업이 없습니다. 수업이 시작되면 이 화면이 바뀝니다.')).toBeVisible();
	await expect(page.getByRole('heading', { name: '미리 볼 수 있는 회차' })).toHaveCount(0); // 비공개라 없다

	// 교수가 공개한다: 새로 고치지 않아도 목록에 나타난다
	expect(
		(await room.api.put(`/api/classrooms/${room.id}/sessions/${session.id}/deck/visibility`, { data: { public: true } })).status()
	).toBe(200);
	const open = page.getByRole('button', { name: '9주차 미리 보기' });
	await expect(open).toBeVisible();
	await expectNoAxeViolations(page, '미리 볼 수 있는 회차가 있는 대기 화면');
	await expectNoHorizontalScroll(page, '미리 볼 수 있는 회차가 있는 대기 화면');
	await open.click();
	await expect(page.getByRole('heading', { level: 1, name: '9주차 미리 보기' })).toBeFocused();
	const previewHash = () => page.frameLocator('iframe[title="미리 보는 슬라이드"]').locator('body').evaluate(() => location.hash);
	await expect.poll(previewHash).toMatch(/^#\/1/);
	const next = page.getByRole('button', { name: '다음' });
	await expect(next).toHaveAttribute('aria-disabled', 'false');
	await next.click();
	await expect.poll(previewHash).toMatch(/^#\/2/);
	await expectNoAxeViolations(page, '미리 보기');

	// 미리 보는 중에 그 회차의 수업이 시작되면 수업 화면으로 바뀐다(AC23)
	expect((await room.api.post(`/api/classrooms/${room.id}/sessions/${session.id}/start`)).status()).toBe(200);
	await expect(page.getByTitle('수업 슬라이드')).toBeVisible();
	await expect(page.getByText('교수 화면 따라가는 중')).toBeVisible();
	await expect.poll(() => slideOf(page)).toMatch(/^#\/1/);
});

// 002 T027: 연결이 끊기면 안내하고 다시 붙으면 놓친 것을 채운다(C12). 명단에서 빠지면 입장 화면으로 간다(AC44)
test('끊기면 안내하고, 다시 붙으면 교수 위치와 놓친 자료로 돌아온다 (오류 동작, C12)', async ({ page }) => {
	test.setTimeout(60_000); // 다시 붙는 간격(1·2·5·10초)을 기다린다
	const sockets = await controlSockets(page);
	const oh = student('offline');
	const room = await classroomWith([oh], `연결 끊김 ${Date.now()}`);
	const session = await (await room.api.post(`/api/classrooms/${room.id}/sessions`, { data: { title: '10주차' } })).json();
	await room.api.put(`/api/classrooms/${room.id}/sessions/${session.id}/deck?filename=deck.zip`, {
		headers: { 'Content-Type': 'application/zip' },
		data: readFileSync(DECK_ZIP)
	});
	await room.api.post(`/api/classrooms/${room.id}/sessions/${session.id}/start`);
	await enterLive(page, room.token, oh.email);
	await noTransitions(page);
	await expect.poll(() => slideOf(page)).toMatch(/^#\/1/);

	await sockets.drop();
	await expect(page.getByText('연결이 끊겼습니다. 다시 연결하는 중…')).toBeVisible();
	await expect(page.getByTitle('수업 슬라이드')).toBeVisible(); // 슬라이드는 그대로
	await expectNoAxeViolations(page, '연결이 끊긴 학생 화면');

	// 끊긴 동안 교수가 넘기고 자료를 보낸다
	const professor = await page.context().browser()!.newContext();
	const teacher = await professor.newPage();
	await teacher.goto('/api/auth/github/login');
	await teacher.waitForURL('**/courses');
	await teacher.goto(`/courses/${room.id}/live`);
	const next = teacher.getByRole('button', { name: '다음' });
	await expect(next).toHaveAttribute('aria-disabled', 'false');
	await next.click();
	await expect
		.poll(async () => (await (await room.api.get(`/api/class/${room.id}/sessions/${session.id}/live`)).json()).current)
		.toEqual({ slide: 2, click: 0 });
	await room.api.post(`/api/classrooms/${room.id}/sessions/${session.id}/items`, { data: { body: '끊긴 동안 보낸 자료', client_key: 'o1' } });
	await professor.close();

	await sockets.restore();
	await expect(page.getByText('연결이 끊겼습니다. 다시 연결하는 중…')).toHaveCount(0, { timeout: 20_000 }); // 1·2·5·10초 간격으로 다시 붙는다
	await expect.poll(() => slideOf(page)).toMatch(/^#\/2/); // 따라가던 학생은 교수 위치로
	await expect(page.getByRole('list', { name: '자료' })).toContainText('끊긴 동안 보낸 자료'); // 놓친 항목 0개
});

test('수업 중에 명단에서 빠지면 입장 화면으로 가고 이유를 본다 (AC44)', async ({ page }) => {
	const ra = student('removed');
	const room = await classroomWith([ra], `명단에서 빠짐 ${Date.now()}`);
	const session = await (await room.api.post(`/api/classrooms/${room.id}/sessions`, { data: { title: '11주차' } })).json();
	await room.api.post(`/api/classrooms/${room.id}/sessions/${session.id}/start`);
	await enterLive(page, room.token, ra.email);
	const roster = await (await room.api.get(`/api/classrooms/${room.id}/roster`)).json();
	const entry = roster.entries.find((e: { email: string }) => e.email === ra.email);
	expect((await room.api.delete(`/api/classrooms/${room.id}/roster/${entry.id}`)).ok()).toBe(true);
	await expect(page.getByRole('alert')).toContainText('수강생 명단에서 빠져 이 수업을 볼 수 없습니다. 교수님께 문의해 주세요.');
	await expect(page.getByLabel('이메일')).toBeVisible();
	await expect(page.getByText('교수 화면 따라가는 중')).toHaveCount(0);
	await expectNoAxeViolations(page, '명단에서 빠진 뒤의 입장 화면');
});

test('끊긴 동안 명단에서 빠져도 입장 화면으로 간다 (AC44)', async ({ page }) => {
	test.setTimeout(60_000);
	const sockets = await controlSockets(page);
	const kwon = student('removed-offline');
	const room = await classroomWith([kwon], `끊긴 동안 빠짐 ${Date.now()}`);
	const session = await (await room.api.post(`/api/classrooms/${room.id}/sessions`, { data: { title: '12주차' } })).json();
	await room.api.post(`/api/classrooms/${room.id}/sessions/${session.id}/start`);
	await enterLive(page, room.token, kwon.email);
	await sockets.drop(); // 휴대폰 화면이 꺼지는 등
	await expect(page.getByText('연결이 끊겼습니다. 다시 연결하는 중…')).toBeVisible();
	const roster = await (await room.api.get(`/api/classrooms/${room.id}/roster`)).json();
	const entry = roster.entries.find((e: { email: string }) => e.email === kwon.email);
	expect((await room.api.delete(`/api/classrooms/${room.id}/roster/${entry.id}`)).ok()).toBe(true);
	await sockets.restore();
	// 서버는 빠진 학생의 연결을 받지 않는다(goodbye 없이). 화면이 물어보고 입장 화면으로 간다
	await expect(page.getByRole('alert')).toContainText('이 수업을 더 볼 수 없습니다. 이메일로 다시 입장해 주세요.', { timeout: 30_000 });
	await expect(page.getByLabel('이메일')).toBeVisible();
});

// 002 T038: 기다리는 동안 다음 수업의 공개 묶음을 미리 받아 두면, 수업이 시작될 때 해시 파일을 다시 받지 않는다(plan 위험 4)
test('공개 묶음은 대기 화면에서 미리 받아 두고, 수업이 시작되면 캐시에서 연다 (T038)', async ({ page }) => {
	const pre = student('preload');
	const room = await classroomWith([pre], `미리 받기 ${Date.now()}`);
	const session = await (await room.api.post(`/api/classrooms/${room.id}/sessions`, { data: { title: '13주차' } })).json();
	const upload = await (
		await room.api.put(`/api/classrooms/${room.id}/sessions/${session.id}/deck?filename=deck.zip`, {
			headers: { 'Content-Type': 'application/zip' },
			data: readFileSync(DECK_ZIP)
		})
	).json();
	const deckId = upload.deck.id as number;
	await room.api.put(`/api/classrooms/${room.id}/sessions/${session.id}/deck/visibility`, { data: { public: true } });

	// 네트워크에서 받은 것과 캐시에서 꺼낸 것을 브라우저에게서 직접 듣는다
	const cdp = await page.context().newCDPSession(page);
	await cdp.send('Network.enable');
	const fromNetwork: string[] = [];
	const fromCache: string[] = [];
	cdp.on('Network.responseReceived', (e) => {
		const url = new URL(e.response.url).pathname;
		if (!/^\/decks\/\d+\/assets\/.+-[\w-]{8,}\.(js|css)$/.test(url)) return;
		if (e.response.fromDiskCache || e.response.fromPrefetchCache || e.response.fromServiceWorker) fromCache.push(url);
		else fromNetwork.push(url); // 다시 확인(304)도 요청이다. 미리 받기는 요청 자체를 없앤다
	});

	await enter(page, room.token, pre.email);
	await expect(page.getByRole('button', { name: '13주차 미리 보기' })).toBeVisible();
	// 미리 받기가 끝날 때까지(해시 파일 7개가 네트워크로 왔다)
	await expect.poll(() => fromNetwork.filter((u) => u.startsWith(`/decks/${deckId}/`)).length).toBeGreaterThanOrEqual(7);
	await page.waitForTimeout(300);
	const before = fromNetwork.length;

	// 수업이 시작되면 슬라이드가 열리고, 미리 받은 해시 파일은 다시 받지 않는다
	expect((await room.api.post(`/api/classrooms/${room.id}/sessions/${session.id}/start`)).status()).toBe(200);
	await expect(page.getByTitle('수업 슬라이드')).toBeVisible();
	await expect.poll(() => slideOf(page)).toMatch(/^#\/1/);
	const again = fromNetwork.slice(before).filter((u) => u.startsWith(`/decks/${deckId}/`));
	const preloaded = new Set(fromNetwork.slice(0, before));
	expect(again.filter((u) => preloaded.has(u)), '미리 받은 파일을 다시 요청했다(받거나 확인)').toEqual([]);
	// 슬라이드는 미리 받은 파일을 캐시에서 꺼내 열었다
	expect(fromCache.filter((u) => preloaded.has(u)).length, '미리 받은 파일을 캐시에서 꺼내지 않았다').toBeGreaterThan(0);
});
