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

test('메시지·자료를 보내고 거둔다 (AC31, AC32, AC35, AC36)', async ({ page }) => {
	const room = await liveClass();
	await openLive(page, room.id);
	const panel = page.getByRole('region', { name: '메시지·자료 보내기' });
	await expect(panel.getByText('아직 보낸 항목이 없습니다.')).toBeVisible();

	// 링크 형식이 틀리면 보내지 않는다
	await panel.getByLabel('링크(선택)').fill('example.com');
	await panel.getByRole('button', { name: '학생에게 보내기' }).click();
	await expect(panel.getByText('링크는 http:// 또는 https://로 시작해야 합니다.')).toBeVisible();

	await panel.getByLabel('글').fill('과제는 금요일까지 올려 주세요.');
	await panel.getByLabel('링크(선택)').fill('https://example.com/hw');
	await panel.getByRole('button', { name: '학생에게 보내기' }).click();
	const list = panel.getByRole('list', { name: '보낸 항목' });
	await expect(list.getByRole('listitem').first()).toContainText('과제는 금요일까지 올려 주세요.');
	await expect(panel.getByLabel('글')).toHaveValue('');
	const state = await (await room.api.get(`/api/class/${room.id}/sessions/${room.sessionId}/live`)).json();
	expect(state.items.map((i: { body: string }) => i.body)).toEqual(['과제는 금요일까지 올려 주세요.']);
	await expectNoAxeViolations(page, '보내기 탭');
	if (process.env.E2E_SHOTS) await page.screenshot({ path: `${process.env.E2E_SHOTS}/class-live.png`, fullPage: true });

	await panel.getByRole('button', { name: '거두기: 과제는 금요일까지 올려 주세요.' }).click();
	await page.getByRole('alertdialog').getByRole('button', { name: '거두기' }).click();
	await expect(list.getByText('거둔 항목 · 학생에게 보이지 않습니다.')).toBeVisible();
	await expect(panel.getByText('보낸 항목은 수업이 끝난 뒤 공개할 목록으로 정리됩니다.')).toBeVisible();
});

test('수업 종료를 확인하면 관리 페이지로 돌아가고 회차가 종료다 (AC37)', async ({ page }) => {
	const room = await liveClass();
	await openLive(page, room.id);
	await page.getByRole('button', { name: '수업 종료' }).click();
	const dialog = page.getByRole('alertdialog');
	await expect(dialog).toContainText('수업을 끝낼까요?');
	await expect(dialog).toContainText('학생은 이번 수업에서 본 슬라이드와 받은 자료를 계속 볼 수 있습니다.');
	await expectNoAxeViolations(page, '수업 종료 확인 창');

	// 취소하면 그대로다
	await dialog.getByRole('button', { name: '취소' }).click();
	await expect(dialog).toHaveCount(0);
	await expect(page).toHaveURL(new RegExp(`/courses/${room.id}/live$`));
	await expect(page.getByRole('button', { name: '수업 종료' })).toBeFocused(); // 초점이 돌아온다

	await page.getByRole('button', { name: '수업 종료' }).click();
	await page.getByRole('alertdialog').getByRole('button', { name: '수업 종료' }).click();
	await expect(page).toHaveURL(new RegExp(`/courses/${room.id}/admin$`));
	await expect(page.getByRole('button', { name: /^회차 선택: 3주차 1회차 종료/ })).toBeVisible();
	await expect(page.getByRole('button', { name: '이어서 수업하기' })).toBeVisible();
	const state = await (await room.api.get(`/api/class/${room.id}/sessions/${room.sessionId}/live`)).json();
	expect(state.session.status).toBe('ended');
});
