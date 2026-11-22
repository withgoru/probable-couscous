import { expect, test, type Page } from '@playwright/test';
import { checkFocused, expectNoAxeViolations, expectNoHorizontalScroll, noTransitions, tabTo, unique, type FocusIssue } from './a11y-helpers';
import { classroomWith, lastCode, student } from './helpers';

// T034(AC50, AC51, C14): 키보드만으로 끝까지 가는지, 지나가는 모든 요소의 포커스 링과 44px, 390px 가로 스크롤,
// 그리고 axe로 화면마다 WCAG 2.2 AA 자동 점검.
const DESKTOP = { width: 1280, height: 800 };
const PHONE = { width: 390, height: 844 };

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
