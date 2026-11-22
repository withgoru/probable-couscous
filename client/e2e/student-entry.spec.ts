import { expect, test } from '@playwright/test';
import { classroomWith, lastCode, newCode, reopen, requestCode, student, typeCode } from './helpers';

// T033: 학생 입장 전체(AC24~AC28)와 기기 묶음(AC33), 로그인 유지 켬/끔(AC35, AC36)을 실제 브라우저로 확인한다.
// 서버와 메일함을 모든 테스트가 같이 쓰므로, 테스트마다 이메일이 다른 학생을 만든다(이전 테스트의 코드를 읽지 않게)
let KIM = student('kim');
test.beforeEach(() => {
	KIM = student('kim');
});

test('초대 링크에서 입장 완료까지: 이메일 → 코드 → 채팅 이용 안내 → 입장 (AC24~AC28)', async ({ page }) => {
	const room = await classroomWith([KIM]);
	await page.goto(`/join/${room.token}`);

	// AC24: 안내 문구, 이메일 칸, '인증 코드 받기'. 형식 오류 안내
	await expect(page.getByText('수강생 명단에 있는 이메일로 입장합니다. 가입은 필요 없습니다.')).toBeVisible();
	await page.getByLabel('이메일').fill('kim@');
	await page.getByRole('button', { name: '인증 코드 받기' }).click();
	await expect(page.getByText('이메일 형식을 확인해 주세요.')).toBeVisible();

	// AC25: 명단 이메일이면 코드 단계, 이 기기에서 입력하라는 안내
	await page.getByLabel('이메일').fill(KIM.email);
	await page.getByRole('button', { name: '인증 코드 받기' }).click();
	await expect(page.getByRole('heading', { level: 1, name: '인증 코드를 입력하세요' })).toBeVisible();
	await expect(page.getByText('코드는 지금 이 화면을 연 기기에서 입력해야 합니다.')).toBeVisible();

	// AC26: 6자리 칸, 로그인 유지(처음부터 켜짐), '확인하고 계속'
	await expect(page.getByLabel('이 기기에서 로그인 유지')).toBeChecked();
	await typeCode(page, await lastCode(KIM.email));

	// AC27: 닉네임 카드와 안내 3줄, '익명' 없음
	const notice = page.getByRole('region', { name: '채팅 이용 안내' });
	await expect(notice).toBeVisible();
	await expect(notice.getByText('다른 학생에게는 닉네임으로만 보입니다.')).toBeVisible();
	await expect(page.locator('body')).not.toContainText('익명');
	const nickname = (await page.getByText('이 수업에서 쓰는 닉네임').locator('xpath=following-sibling::*[1]').textContent())?.trim();
	expect(nickname).toBeTruthy();

	// AC28: '확인하고 입장' → 강좌 이름과 닉네임
	await page.getByRole('button', { name: '확인하고 입장' }).click();
	await expect(page.getByText('입장했습니다')).toBeVisible();
	await expect(page.getByRole('heading', { level: 1, name: room.name })).toBeVisible();
	await expect(page.getByText(nickname!)).toBeVisible();
});

test('기기 묶음: A에서 받은 코드를 B에 넣으면 같은 오류이고, A의 코드와 남은 횟수는 그대로다 (AC33)', async ({ browser }) => {
	const room = await classroomWith([KIM]);
	const a = await (await browser.newContext()).newPage();
	const b = await (await browser.newContext()).newPage(); // 다른 브라우저(쿠키가 따로)

	await requestCode(a, room.token, KIM.email);
	const code = await lastCode(KIM.email);

	// B는 링크를 열고 이메일을 넣지만 코드를 새로 받지 않고(60초 안이라 A의 코드 화면으로 온다) A의 코드를 넣는다
	await b.goto(`/join/${room.token}`);
	await b.getByLabel('이메일').fill(KIM.email);
	await b.getByLabel('이메일').press('Enter');
	await expect(b.getByLabel('인증 코드 6자리')).toBeVisible();
	await typeCode(b, code);
	await expect(b.getByText('코드가 맞지 않습니다.', { exact: true })).toBeVisible(); // 남은 횟수 없이 같은 문구

	// A: 한 번 틀리면 처음부터 센 남은 횟수(4번)가 보인다. B의 시도는 A의 횟수를 쓰지 않았다
	const wrong = code === '000000' ? '111111' : '000000';
	await typeCode(a, wrong);
	await expect(a.getByText('코드가 맞지 않습니다. 4번 더 입력할 수 있습니다.')).toBeVisible();
	await typeCode(a, code);
	await expect(a.getByRole('region', { name: '채팅 이용 안내' })).toBeVisible();
});

test('로그인 유지를 켜고 입장하면 브라우저를 닫았다 열어도 바로 입장 완료다 (AC35)', async ({ browser }) => {
	const room = await classroomWith([KIM]);
	const context = await browser.newContext();
	const page = await context.newPage();
	await requestCode(page, room.token, KIM.email);
	await typeCode(page, await lastCode(KIM.email)); // 로그인 유지는 처음부터 켜져 있다
	await page.getByRole('button', { name: '확인하고 입장' }).click();
	await expect(page.getByText('입장했습니다')).toBeVisible();

	const again = await (await reopen(browser, context)).newPage();
	await again.goto(`/join/${room.token}`);
	await expect(again.getByText('입장했습니다')).toBeVisible();
	await expect(again.getByLabel('이메일')).toHaveCount(0); // 이메일·코드 입력 없이
});

test('로그인 유지를 끄고 입장하면 브라우저를 닫았다 열 때 이메일 인증부터 다시 한다 (AC36)', async ({ browser }) => {
	const room = await classroomWith([KIM]);
	const context = await browser.newContext();
	const page = await context.newPage();
	await requestCode(page, room.token, KIM.email);
	const first = await lastCode(KIM.email);
	await page.getByLabel('이 기기에서 로그인 유지').uncheck();
	await typeCode(page, first);
	await page.getByRole('button', { name: '확인하고 입장' }).click();
	await expect(page.getByText('입장했습니다')).toBeVisible();

	// 같은 브라우저를 닫지 않고 다시 열면 아직 입장 상태다(브라우저를 닫을 때까지 유지)
	await page.goto(`/join/${room.token}`);
	await expect(page.getByText('입장했습니다')).toBeVisible();

	const again = await (await reopen(browser, context)).newPage();
	await again.goto(`/join/${room.token}`);
	await expect(again.getByLabel('이메일')).toBeVisible(); // 브라우저를 닫으면 로그인이 끝난다
	await expect(again.getByText('입장했습니다')).toHaveCount(0);
});

test('같은 기기로 다른 강좌 링크를 열면 이메일 없이 그 강좌의 안내와 새 닉네임이 나온다 (AC37)', async ({ page }) => {
	const web = await classroomWith([KIM], 'E2E 웹');
	const app = await classroomWith([KIM], 'E2E 앱');
	await requestCode(page, web.token, KIM.email);
	await typeCode(page, await lastCode(KIM.email));
	const webNick = (await page.getByText('이 수업에서 쓰는 닉네임').locator('xpath=following-sibling::*[1]').textContent())?.trim();
	await page.getByRole('button', { name: '확인하고 입장' }).click();
	await expect(page.getByText('입장했습니다')).toBeVisible();

	await page.goto(`/join/${app.token}`);
	await expect(page.getByRole('region', { name: '채팅 이용 안내' })).toBeVisible();
	await expect(page.getByLabel('이메일')).toHaveCount(0);
	await expect(page.getByText('E2E 앱')).toBeVisible();
	const appNick = (await page.getByText('이 수업에서 쓰는 닉네임').locator('xpath=following-sibling::*[1]').textContent())?.trim();
	expect(appNick).toBeTruthy();
	expect(appNick).not.toBe(webNick); // 강좌마다 따로 받는다(AC29)
});

test('명단에 없는 이메일은 입장 요청을 보내고, 교수가 승인하면 같은 이메일로 입장한다 (AC38~AC41)', async ({ page }) => {
	const room = await classroomWith([KIM]);
	const park = student('park', '박민수', '20249999');
	await page.goto(`/join/${room.token}`);
	await page.getByLabel('이메일').fill(park.email);
	await page.getByLabel('이메일').press('Enter');
	await expect(page.getByText(/수강생 명단에 없는 이메일입니다/)).toBeVisible();
	await page.getByRole('button', { name: '입장 요청 보내기' }).click();
	await page.getByLabel('이름').fill(park.name);
	await page.getByLabel('학번').fill(park.no);
	await page.getByRole('button', { name: '요청 보내기' }).click();
	await expect(page.getByText('요청을 보냈습니다. 교수님이 확인하면 이 이메일로 인증 코드를 받을 수 있습니다.')).toBeVisible();

	const requests = (await (await room.api.get(`/api/classrooms/${room.id}/join-requests`)).json()).requests;
	expect(requests.map((r: { name: string }) => r.name)).toEqual([park.name]);
	expect((await room.api.post(`/api/classrooms/${room.id}/join-requests/${requests[0].id}/approve`)).ok()).toBeTruthy();

	await requestCode(page, room.token, park.email);
	await typeCode(page, await lastCode(park.email));
	await expect(page.getByRole('region', { name: '채팅 이용 안내' })).toBeVisible();
});

test('메일이 오지 않으면 교수님께 알리고, 교수가 알려 준 코드로 입장한다 (AC44~AC47)', async ({ page }) => {
	const room = await classroomWith([KIM]);
	await requestCode(page, room.token, KIM.email);
	await page.getByRole('button', { name: '교수님께 알리기' }).click();
	await expect(page.getByText('교수님께 알렸습니다. 교수님이 알려 주는 코드를 입력하세요.')).toBeVisible();

	const items = (await (await room.api.get(`/api/classrooms/${room.id}/pending-auth`)).json()).items;
	expect(items).toHaveLength(1);
	await typeCode(page, items[0].code);
	await expect(page.getByRole('region', { name: '채팅 이용 안내' })).toBeVisible();
	const after = (await (await room.api.get(`/api/classrooms/${room.id}/pending-auth`)).json()).items;
	expect(after[0].status).toBe('used');
});

test('학생 화면은 390px 폭에서 가로 스크롤이 없다 (AC51)', async ({ page }) => {
	const room = await classroomWith([KIM]);
	for (const step of ['email', 'code'] as const) {
		if (step === 'email') await page.goto(`/join/${room.token}`);
		else await requestCode(page, room.token, KIM.email);
		const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
		expect(overflow, step).toBeLessThanOrEqual(0);
	}
});

test.describe('이어서 쓰는 코드', () => {
	test('다시 받은 코드는 쓸 수 있고 이전 코드는 쓸 수 없다 (AC32)', async ({ page }) => {
		test.slow(); // 60초 간격을 실제로 기다린다
		const room = await classroomWith([KIM]);
		await requestCode(page, room.token, KIM.email);
		const old = await lastCode(KIM.email);
		await expect(page.getByRole('button', { name: '코드 다시 받기' })).toBeEnabled({ timeout: 70_000 });
		await page.getByRole('button', { name: '코드 다시 받기' }).click();
		await expect(page.getByText('새 코드를 보냈습니다. 이전 코드는 쓸 수 없습니다.')).toBeVisible();
		const fresh = await newCode(KIM.email, old);
		await typeCode(page, old);
		await expect(page.getByLabel('인증 코드 6자리')).toHaveAttribute('aria-invalid', 'true');
		await typeCode(page, fresh);
		await expect(page.getByRole('region', { name: '채팅 이용 안내' })).toBeVisible();
	});
});
