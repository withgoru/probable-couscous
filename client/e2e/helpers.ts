import { expect, request, type Browser, type BrowserContext, type Page } from '@playwright/test';

const BASE = 'http://127.0.0.1:8799';
let seq = 0;

/** 교수 쪽 준비는 API로 한다(이 E2E는 학생 입장을 본다). 가짜 GitHub라 로그인 시작만 하면 kim으로 로그인된다. */
export async function professor() {
	const api = await request.newContext({ baseURL: BASE, extraHTTPHeaders: { Origin: BASE } });
	const done = await api.get('/api/auth/github/login'); // 리디렉트를 따라가 콜백까지 간다
	expect(done.ok()).toBeTruthy();
	return api;
}

export type Student = { no: string; name: string; email: string };

let people = 0;
/** 이 실행에서 처음 쓰는 이메일의 학생. 메일함을 테스트끼리 같이 쓰므로 이메일이 겹치지 않게 한다. */
export function student(prefix: string, name = '김철수', no = '20240001'): Student {
	people += 1;
	return { no, name, email: `${prefix}${people}-${Date.now()}@e2e.kr` };
}

/** 강좌를 만들고 명단을 넣은 뒤 초대 링크 토큰을 돌려준다. 테스트마다 이름이 다른 새 강좌다. */
export async function classroomWith(students: Student[], name = `E2E 강좌 ${++seq}`) {
	const api = await professor();
	const classroom = await (await api.post('/api/classrooms', { data: { name } })).json();
	for (const s of students) {
		const r = await api.post(`/api/classrooms/${classroom.id}/roster`, { data: { student_no: s.no, name: s.name, email: s.email } });
		expect(r.status(), await r.text()).toBe(201);
	}
	const invite = await (await api.get(`/api/classrooms/${classroom.id}/invite`)).json();
	return { id: classroom.id as number, name, token: invite.token as string, api };
}

/** 그 주소로 마지막에 보낸 인증 코드(메일 작업이 보낼 때까지 기다린다). */
export async function lastCode(email: string): Promise<string> {
	const api = await request.newContext({ baseURL: BASE });
	let code = '';
	await expect
		.poll(async () => {
			const r = await api.get(`/api/test/last-code?to=${encodeURIComponent(email)}`);
			code = r.ok() ? (await r.json()).code : '';
			return code;
		}, { timeout: 10_000 })
		.toMatch(/^\d{6}$/);
	return code;
}

/** 지금까지 받은 코드와 다른 새 코드가 올 때까지 기다린다. */
export async function newCode(email: string, previous: string): Promise<string> {
	let code = previous;
	await expect.poll(async () => (code = await lastCode(email)), { timeout: 10_000 }).not.toBe(previous);
	return code;
}

/**
 * 브라우저를 닫았다 다시 연 것처럼 새 컨텍스트를 만든다. 만료 시각이 없는 쿠키(브라우저를 닫으면 사라지는 쿠키)는 버리고
 * 만료 시각이 있는 쿠키(기기 쿠키, '로그인 유지'를 켠 로그인 쿠키)만 남긴다.
 */
export async function reopen(browser: Browser, context: BrowserContext): Promise<BrowserContext> {
	const state = await context.storageState();
	await context.close();
	return browser.newContext({ storageState: { ...state, cookies: state.cookies.filter((c) => c.expires > 0) } });
}

/** 이메일 단계: 링크를 열고 이메일을 넣어 코드를 받는다(키보드로 제출). */
export async function requestCode(page: Page, token: string, email: string) {
	await page.goto(`/join/${token}`);
	await page.getByLabel('이메일').fill(email);
	await page.getByLabel('이메일').press('Enter');
	await expect(page.getByRole('heading', { level: 1, name: '인증 코드를 입력하세요' })).toBeVisible();
}

export async function typeCode(page: Page, code: string) {
	await page.getByLabel('인증 코드 6자리').fill(code);
	await page.getByRole('button', { name: '확인하고 계속' }).click();
}
