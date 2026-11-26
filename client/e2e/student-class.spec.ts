import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { expect, test, type Page } from '@playwright/test';
import { expectNoAxeViolations, expectNoHorizontalScroll, noTransitions } from './a11y-helpers';
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

test('넘기면 따라가기가 풀리고, 가장 멀리 간 위치까지만 가며, 교수 화면으로 다시 따라간다 (AC26~AC28)', async ({ page }) => {
	const park = student('browse');
	const room = await classroomWith([park], `직접 넘겨 보기 ${Date.now()}`);
	const session = await (await room.api.post(`/api/classrooms/${room.id}/sessions`, { data: { title: '5주차' } })).json();
	await room.api.put(`/api/classrooms/${room.id}/sessions/${session.id}/deck?filename=deck.zip`, {
		headers: { 'Content-Type': 'application/zip' },
		data: readFileSync(DECK_ZIP)
	});
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

	// 교수님이 2번 슬라이드 0단계까지만 보였다: 다음은 흐리고 안내가 보인다(AC27)
	await expect(page.getByRole('button', { name: '다음' })).toBeDisabled();
	await expect(page.getByText('교수님이 아직 보여 주지 않은 슬라이드입니다.')).toBeVisible();

	// 이전을 누르면 따라가기가 풀리고 1번으로(AC26)
	await page.getByRole('button', { name: '이전' }).click();
	await expect.poll(() => slideOf(page)).toMatch(/^#\/1/);
	await expect(page.getByText('직접 넘겨 보는 중 · 교수 화면은 2번 슬라이드입니다.')).toBeVisible();

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
