import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { expect, test, type Page } from '@playwright/test';
import { expectNoAxeViolations, noTransitions } from './a11y-helpers';
import { classroomWith } from './helpers';

// 002 T018: 실제 서버와 실제 슬라이드 묶음(템플릿으로 빌드한 4장, 단계 0/3/0/1)으로 교수 수업 화면을 연다.
// 한 탭에서 넘기면 서버가 기록하고 발행해 다른 탭의 같은 화면이 따라오는지 본다(AC13, AC14, AC16, AC17).
const DECK_ZIP = fileURLToPath(new URL('../../server/tests/fixtures/deck-small.zip', import.meta.url));
const LAPTOP = { width: 1280, height: 800 };

test.use({ viewport: LAPTOP });

async function liveClass() {
	const room = await classroomWith([], `수업 화면 ${Date.now()}`);
	const session = await (await room.api.post(`/api/classrooms/${room.id}/sessions`, { data: { title: '3주차 1회차' } })).json();
	const upload = await room.api.put(`/api/classrooms/${room.id}/sessions/${session.id}/deck?filename=deck.zip`, {
		headers: { 'Content-Type': 'application/zip' },
		data: readFileSync(DECK_ZIP)
	});
	expect(upload.status(), await upload.text()).toBe(200);
	expect((await room.api.post(`/api/classrooms/${room.id}/sessions/${session.id}/start`)).status()).toBe(200);
	return { ...room, sessionId: session.id as number };
}

/** 현재 슬라이드 iframe의 주소(애드온이 `#/{슬라이드}?clicks=…`로 바꾼다). */
async function slideOf(page: Page): Promise<string> {
	return page.frameLocator('iframe[title="현재 슬라이드"]').locator('body').evaluate(() => location.hash);
}

/** 슬라이드가 서버 위치를 그려 넘길 수 있게 된 뒤에 누른다(그 전에 누르면 화면이 받지 않는다). */
async function press(page: Page, name: '이전' | '다음') {
	const button = page.getByRole('button', { name });
	await expect(button).toHaveAttribute('aria-disabled', 'false');
	await button.click();
}

async function openLive(page: Page, id: number) {
	await page.goto('/api/auth/github/login');
	await page.waitForURL('**/courses');
	await page.goto(`/courses/${id}/live`);
	await noTransitions(page);
	await expect(page.getByRole('heading', { level: 1, name: '3주차 1회차' })).toBeVisible();
}

test('넘기면 다른 탭의 교수 수업 화면이 따라오고, 다시 열어도 마지막 위치에서 이어진다', async ({ browser }) => {
	const room = await liveClass();
	const context = await browser.newContext({ viewport: LAPTOP });
	const first = await context.newPage();
	const second = await context.newPage();
	await openLive(first, room.id);
	await openLive(second, room.id);

	// 메뉴바가 없고 위쪽 줄이 있다(AC12)
	await expect(first.getByRole('button', { name: '@kim' })).toHaveCount(0);
	await expect(first.getByRole('button', { name: '프로젝터 화면 열기' })).toBeVisible();
	// 동기화 현황(AC15): 아직 학생이 없으니 0명이다
	await expect(first.getByText('따라가는 중 0명 · 직접 넘겨 보는 중 0명')).toBeVisible();

	// 1번 슬라이드는 단계가 없다: 다음은 2번 슬라이드 첫 단계
	await expect.poll(() => slideOf(first)).toMatch(/^#\/1/);
	await press(first, '다음');
	await expect.poll(() => slideOf(first)).toMatch(/^#\/2/);
	await expect.poll(() => slideOf(second)).toMatch(/^#\/2/); // 다른 탭이 따라온다(AC17)
	await expect(first.getByText('노트 2: 하나씩 보여 준다')).toBeVisible(); // 발표자 노트

	// 2번 슬라이드는 단계가 3개다: 키보드 →로 단계를 넘긴다(AC13, AC14)
	await expect(first.getByRole('button', { name: '다음' })).toHaveAttribute('aria-disabled', 'false');
	await first.getByRole('button', { name: '다음' }).focus();
	await first.keyboard.press('ArrowRight');
	await expect.poll(() => slideOf(second)).toMatch(/^#\/2\?clicks=1/);

	// 서버가 진실이다: 다시 열면 마지막 위치에서 이어진다(AC16)
	await second.reload();
	await expect(second.getByRole('heading', { level: 1, name: '3주차 1회차' })).toBeVisible();
	await expect.poll(() => slideOf(second)).toMatch(/^#\/2\?clicks=1/);
	const state = await (await room.api.get(`/api/class/${room.id}/sessions/${room.sessionId}/live`)).json();
	expect(state.current).toEqual({ slide: 2, click: 1 });

	await expectNoAxeViolations(first, '교수 수업 화면');
	await context.close();
});

test('처음에는 이전이 흐려지고, 끝까지 넘기면 다음이 흐려진다 (AC14)', async ({ page }) => {
	const room = await liveClass();
	await openLive(page, room.id);
	const prev = page.getByRole('button', { name: '이전' });
	const next = page.getByRole('button', { name: '다음' });
	await expect(prev).toBeDisabled();
	// 1 → 2(0) → 2(1) → 2(2) → 2(3) → 3 → 4(0) → 4(1): 일곱 번 넘기면 끝이다
	for (let i = 0; i < 7; i += 1) await press(page, '다음');
	await expect(next).toBeDisabled();
	await expect(page.getByText('마지막 슬라이드입니다.')).toBeVisible();
	await expect.poll(() => slideOf(page)).toMatch(/^#\/4\?clicks=1/);
});
