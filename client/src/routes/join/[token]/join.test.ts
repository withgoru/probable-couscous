// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({ submitJoinEmail: vi.fn(), requestAccess: vi.fn() }));
vi.mock('#lib/api.js', async (original) => ({
	...(await original<object>()),
	submitJoinEmail: api.submitJoinEmail,
	requestAccess: api.requestAccess
}));

import { ApiError } from '#lib/api.js';
import JoinPage from './+page.svelte';

const INTRO = '수강생 명단에 있는 이메일로 입장합니다. 가입은 필요 없습니다.';
const NOT_IN_ROSTER =
	'수강생 명단에 없는 이메일입니다. 수강신청에 쓴 이메일인지 확인하고, 계속 안 되면 교수님께 입장을 요청해 주세요.';
const REQUESTED = '요청을 보냈습니다. 교수님이 확인하면 이 이메일로 인증 코드를 받을 수 있습니다.';
const ALREADY = '이미 요청했습니다. 교수님이 확인할 때까지 기다려 주세요.';
const REJECTED = '입장 요청이 받아들여지지 않았습니다. 교수님께 문의해 주세요.';
const ON_ROSTER = '이미 수강생 명단에 있는 이메일입니다. 이메일을 다시 입력해 인증 코드를 받아 주세요.';
const REVOKED = '이 링크는 더 이상 사용할 수 없습니다. 교수님께 새 링크를 받으세요.';
const ARCHIVED = '이 강좌는 보관되었습니다. 교수님께 문의해 주세요.';

const open = (section: string | null = '월수반') => ({
	me: null,
	token: 'tok',
	invite: { open: true as const, classroom: { name: '웹 프로그래밍', section_name: section } }
});
const closed = (message: string) => ({ me: null, token: 'tok', invite: { open: false as const, message } });

beforeEach(() => {
	api.submitJoinEmail.mockReset();
	api.requestAccess.mockReset();
});
afterEach(cleanup);

const box = (label: string) => screen.getByLabelText(label) as HTMLInputElement;
const getCode = () => screen.getByRole('button', { name: '인증 코드 받기' });
async function typeEmail(value: string) {
	await fireEvent.input(box('이메일'), { target: { value } });
}
async function submitEmail(value = 'kim@x.kr') {
	await typeEmail(value);
	await fireEvent.click(getCode());
}

// --- 이메일 단계 (AC24) ---------------------------------------------------------------------------------------------

describe('이메일 단계 (AC24)', () => {
	it('강좌 이름, 안내 문구, 이름표가 있는 이메일 칸, 인증 코드 받기 버튼이 보인다', () => {
		render(JoinPage, { params: { token: 'tok' }, data: open() });
		expect(screen.getByRole('heading', { level: 1 }).textContent).toContain('웹 프로그래밍 · 월수반');
		expect(screen.getByText(INTRO)).toBeTruthy();
		const email = box('이메일');
		expect(email.type).toBe('email');
		expect(email.getAttribute('autocomplete')).toBe('email');
		expect(email.getAttribute('inputmode')).toBe('email');
		expect(getCode()).toBeTruthy();
		expect(document.title).toContain('웹 프로그래밍');
	});

	it('분반이 없으면 강좌 이름만 보인다', () => {
		render(JoinPage, { params: { token: 'tok' }, data: open(null) });
		const h1 = screen.getByRole('heading', { level: 1 }).textContent ?? '';
		expect(h1).toContain('웹 프로그래밍');
		expect(h1).not.toContain('·');
	});

	it('교수 메뉴나 로그인 안내 없이 학생 화면만 보인다', () => {
		render(JoinPage, { params: { token: 'tok' }, data: open() });
		expect(screen.queryByText(/GitHub/)).toBeNull();
	});

	it('형식이 틀리면 서버를 부르지 않고 칸 옆에 "이메일 형식을 확인해 주세요."가 보인다', async () => {
		render(JoinPage, { params: { token: 'tok' }, data: open() });
		await submitEmail('kim@');
		const email = box('이메일');
		expect(api.submitJoinEmail).not.toHaveBeenCalled();
		expect(email.getAttribute('aria-invalid')).toBe('true');
		const error = document.getElementById(email.getAttribute('aria-describedby') ?? '');
		expect(error?.textContent).toContain('이메일 형식을 확인해 주세요.');
		expect(document.activeElement).toBe(email);
	});

	it('비어 있으면 "이메일을 입력해 주세요."가 보인다', async () => {
		render(JoinPage, { params: { token: 'tok' }, data: open() });
		await submitEmail('   ');
		expect(api.submitJoinEmail).not.toHaveBeenCalled();
		expect(screen.getByText('이메일을 입력해 주세요.')).toBeTruthy();
	});

	it('고쳐 쓰면 오류 표시가 사라진다', async () => {
		render(JoinPage, { params: { token: 'tok' }, data: open() });
		await submitEmail('kim@');
		await typeEmail('kim@x.kr');
		expect(box('이메일').getAttribute('aria-invalid')).toBeNull();
		expect(screen.queryByText('이메일 형식을 확인해 주세요.')).toBeNull();
	});

	it('앞뒤 공백은 빼고 이 링크로 보낸다', async () => {
		api.submitJoinEmail.mockResolvedValue({ next: 'code', wait_seconds: 60 });
		render(JoinPage, { params: { token: 'tok' }, data: open() });
		await submitEmail('  kim@x.kr ');
		expect(api.submitJoinEmail).toHaveBeenCalledWith('tok', 'kim@x.kr');
	});

	it('보내는 동안에는 다시 누를 수 없다', async () => {
		let finish: (v: unknown) => void = () => {};
		api.submitJoinEmail.mockReturnValue(new Promise((r) => (finish = r)));
		render(JoinPage, { params: { token: 'tok' }, data: open() });
		await submitEmail();
		const busy = screen.getByRole('button', { name: '보내는 중…' }) as HTMLButtonElement;
		expect(busy.disabled).toBe(true);
		await fireEvent.submit(busy.closest('form') as HTMLFormElement);
		expect(api.submitJoinEmail).toHaveBeenCalledTimes(1);
		finish({ next: 'code', wait_seconds: 60 });
	});

	it('서버의 칸 오류는 이메일 칸 옆에 보인다', async () => {
		api.submitJoinEmail.mockRejectedValue(new ApiError(422, '이메일 형식을 확인해 주세요.', 'email'));
		render(JoinPage, { params: { token: 'tok' }, data: open() });
		await submitEmail('a@b.c');
		await waitFor(() => expect(box('이메일').getAttribute('aria-invalid')).toBe('true'));
	});

	it('너무 빨리 다시 요청하면 서버의 안내(남은 시간)가 보인다', async () => {
		api.submitJoinEmail.mockRejectedValue(new ApiError(429, '40초 뒤에 다시 받을 수 있습니다.', null));
		render(JoinPage, { params: { token: 'tok' }, data: open() });
		await submitEmail();
		expect((await screen.findByRole('alert')).textContent).toContain('40초 뒤에 다시 받을 수 있습니다.');
		expect(box('이메일').value).toBe('kim@x.kr');
	});

	it('연결이 안 되면 입력한 이메일을 그대로 두고 무엇을 하면 되는지 알려 준다', async () => {
		api.submitJoinEmail.mockRejectedValue(new TypeError('Failed to fetch'));
		render(JoinPage, { params: { token: 'tok' }, data: open() });
		await submitEmail();
		const alert = await screen.findByRole('alert');
		expect(alert.textContent).toContain('인증 코드를 요청하지 못했습니다.');
		expect(alert.textContent).toContain('네트워크 연결을 확인하고 다시 시도해 주세요.');
		expect(box('이메일').value).toBe('kim@x.kr');
	});
});

// --- 코드 단계로 (AC25의 화면 전환. 입력 칸은 T027) ---------------------------------------------------------------

describe('명단에 있는 이메일 (AC25)', () => {
	it('코드 단계로 바뀌고 보낸 주소와 이 기기에서 입력해야 한다는 안내가 보인다', async () => {
		api.submitJoinEmail.mockResolvedValue({ next: 'code', wait_seconds: 60 });
		render(JoinPage, { params: { token: 'tok' }, data: open() });
		await submitEmail();
		const h1 = await screen.findByRole('heading', { level: 1, name: '인증 코드를 입력하세요' });
		expect(screen.getByRole('main').textContent).toContain('6자리 코드를 보냈습니다: kim@x.kr');
		expect(screen.getByText('코드는 지금 이 화면을 연 기기에서 입력해야 합니다.')).toBeTruthy();
		await waitFor(() => expect(document.activeElement).toBe(h1)); // 화면이 바뀐 것을 읽어 주는 도구에도 알린다
	});

	it('"이메일 다시 입력"으로 돌아가면 입력했던 이메일이 남아 있다', async () => {
		api.submitJoinEmail.mockResolvedValue({ next: 'code', wait_seconds: 60 });
		render(JoinPage, { params: { token: 'tok' }, data: open() });
		await submitEmail();
		await fireEvent.click(await screen.findByRole('button', { name: '이메일 다시 입력' }));
		expect(box('이메일').value).toBe('kim@x.kr');
	});
});

// --- 명단에 없는 이메일과 입장 요청 (AC38, AC39, AC42, AC43) ---------------------------------------------------------

describe('명단에 없는 이메일 (AC38)', () => {
	beforeEach(() => api.submitJoinEmail.mockResolvedValue({ next: 'request_access', message: NOT_IN_ROSTER }));

	it('안내 문구와 "입장 요청 보내기" 버튼이 보이고, 이메일을 고칠 수 있게 칸은 그대로다', async () => {
		render(JoinPage, { params: { token: 'tok' }, data: open() });
		await submitEmail('new@x.kr');
		expect((await screen.findByRole('status')).textContent).toContain(NOT_IN_ROSTER);
		expect(screen.getByRole('button', { name: '입장 요청 보내기' })).toBeTruthy();
		expect(box('이메일').value).toBe('new@x.kr');
	});

	it('이메일을 고쳐 쓰면 이전 이메일에 대한 안내는 사라진다', async () => {
		render(JoinPage, { params: { token: 'tok' }, data: open() });
		await submitEmail('new@x.kr');
		await screen.findByRole('status');
		await typeEmail('kim@x.kr');
		expect(screen.queryByRole('status')).toBeNull();
		expect(screen.queryByRole('button', { name: '입장 요청 보내기' })).toBeNull();
	});
});

describe('입장 요청 보내기 (AC39)', () => {
	beforeEach(() => api.submitJoinEmail.mockResolvedValue({ next: 'request_access', message: NOT_IN_ROSTER }));

	async function openForm(email = 'new@x.kr') {
		render(JoinPage, { params: { token: 'tok' }, data: open() });
		await submitEmail(email);
		await fireEvent.click(await screen.findByRole('button', { name: '입장 요청 보내기' }));
		return screen.findByRole('heading', { level: 1, name: '입장 요청 보내기' });
	}
	async function fill(name = '박민수', no = '20249999') {
		await fireEvent.input(box('이름'), { target: { value: name } });
		await fireEvent.input(box('학번'), { target: { value: no } });
	}
	const send = () => fireEvent.click(screen.getByRole('button', { name: '요청 보내기' }));

	it('요청할 이메일이 보이고, 이름과 학번 칸에 이름표가 있으며, 제목으로 포커스가 간다', async () => {
		const h1 = await openForm();
		expect(screen.getByText('new@x.kr')).toBeTruthy();
		expect(box('이름')).toBeTruthy();
		expect(box('학번')).toBeTruthy();
		await waitFor(() => expect(document.activeElement).toBe(h1));
	});

	it('이름과 학번을 써서 보내면 "요청을 보냈습니다…"가 보인다', async () => {
		api.requestAccess.mockResolvedValue({ next: 'requested', message: REQUESTED });
		await openForm();
		await fill();
		await send();
		expect((await screen.findByRole('status')).textContent).toContain(REQUESTED);
		expect(api.requestAccess).toHaveBeenCalledWith('tok', { email: 'new@x.kr', name: '박민수', student_no: '20249999' });
		expect(screen.queryByRole('button', { name: '요청 보내기' })).toBeNull(); // 다시 보낼 일이 없다
	});

	it('이미 요청했으면 그 안내가 보인다 (AC43)', async () => {
		api.requestAccess.mockResolvedValue({ next: 'already_requested', message: ALREADY });
		await openForm();
		await fill();
		await send();
		expect((await screen.findByRole('status')).textContent).toContain(ALREADY);
	});

	it('그사이 거절됐으면 거절 안내가 보인다 (AC42)', async () => {
		api.requestAccess.mockResolvedValue({ next: 'rejected', message: REJECTED });
		await openForm();
		await fill();
		await send();
		expect((await screen.findByRole('status')).textContent).toContain(REJECTED);
	});

	it('그사이 명단에 추가됐으면 안내와 함께 이메일 단계로 돌아갈 수 있다', async () => {
		api.requestAccess.mockResolvedValue({ next: 'already_on_roster', message: ON_ROSTER });
		await openForm();
		await fill();
		await send();
		expect((await screen.findByRole('status')).textContent).toContain(ON_ROSTER);
		await fireEvent.click(screen.getByRole('button', { name: '이메일 다시 입력' }));
		expect(box('이메일').value).toBe('new@x.kr');
	});

	it('서버의 칸 오류는 그 칸 옆에 보이고 입력은 그대로다', async () => {
		api.requestAccess.mockRejectedValue(new ApiError(422, '학번은 50자 이하로 입력해 주세요.', 'student_no'));
		await openForm();
		await fill('박민수', 'x'.repeat(51));
		await send();
		await waitFor(() => expect(box('학번').getAttribute('aria-invalid')).toBe('true'));
		expect(screen.getByText('학번은 50자 이하로 입력해 주세요.')).toBeTruthy();
		expect(document.activeElement).toBe(box('학번'));
		expect(box('이름').value).toBe('박민수');
	});

	it('비어 있는 칸은 서버의 안내로 알려 준다(검사 규칙을 한곳에 둔다)', async () => {
		api.requestAccess.mockRejectedValue(new ApiError(422, '이름을 입력해 주세요.', 'name'));
		await openForm();
		await send();
		expect(await screen.findByText('이름을 입력해 주세요.')).toBeTruthy();
		expect(box('이름').getAttribute('aria-invalid')).toBe('true');
	});

	it('보내는 동안에는 다시 누를 수 없다', async () => {
		let finish: (v: unknown) => void = () => {};
		api.requestAccess.mockReturnValue(new Promise((r) => (finish = r)));
		await openForm();
		await fill();
		await send();
		const busy = screen.getByRole('button', { name: '보내는 중…' }) as HTMLButtonElement;
		expect(busy.disabled).toBe(true);
		await fireEvent.submit(busy.closest('form') as HTMLFormElement);
		expect(api.requestAccess).toHaveBeenCalledTimes(1);
		finish({ next: 'requested', message: REQUESTED });
	});

	it('연결이 안 되면 입력을 그대로 두고 무엇을 하면 되는지 알려 준다', async () => {
		api.requestAccess.mockRejectedValue(new TypeError('Failed to fetch'));
		await openForm();
		await fill();
		await send();
		const alert = await screen.findByRole('alert');
		expect(alert.textContent).toContain('요청을 보내지 못했습니다.');
		expect(alert.textContent).toContain('네트워크 연결을 확인하고 다시 시도해 주세요.');
		expect(box('학번').value).toBe('20249999');
	});

	it('"이메일 다시 입력"으로 돌아가 다른 이메일을 쓸 수 있다', async () => {
		await openForm();
		await fireEvent.click(screen.getByRole('button', { name: '이메일 다시 입력' }));
		expect(box('이메일').value).toBe('new@x.kr');
	});
});

describe('이미 요청했거나 거절된 이메일 (AC42, AC43)', () => {
	it('이메일 단계에서 이미 요청한 이메일이면 기다리라는 안내만 보이고 요청 버튼은 없다', async () => {
		api.submitJoinEmail.mockResolvedValue({ next: 'already_requested', message: ALREADY });
		render(JoinPage, { params: { token: 'tok' }, data: open() });
		await submitEmail('new@x.kr');
		expect((await screen.findByRole('status')).textContent).toContain(ALREADY);
		expect(screen.queryByRole('button', { name: '입장 요청 보내기' })).toBeNull();
	});

	it('거절된 이메일이면 거절 안내가 보이고 요청 버튼은 없다', async () => {
		api.submitJoinEmail.mockResolvedValue({ next: 'rejected', message: REJECTED });
		render(JoinPage, { params: { token: 'tok' }, data: open() });
		await submitEmail('new@x.kr');
		const status = await screen.findByRole('status');
		expect(status.textContent).toContain(REJECTED);
		expect(screen.queryByRole('button', { name: '입장 요청 보내기' })).toBeNull();
	});
});

// --- 링크가 닫혔을 때 (AC10, AC22) -----------------------------------------------------------------------------------

describe('폐기된 링크와 보관된 강좌 (AC10, AC22)', () => {
	it.each([REVOKED, ARCHIVED])('열자마자 "%s"가 보이고 이메일 칸은 없다', (message) => {
		render(JoinPage, { params: { token: 'tok' }, data: closed(message) });
		expect(screen.getByRole('heading', { level: 1, name: '입장할 수 없습니다' })).toBeTruthy();
		expect(screen.getByText(message)).toBeTruthy();
		expect(screen.queryByLabelText('이메일')).toBeNull();
	});

	it.each([
		[404, REVOKED],
		[403, ARCHIVED]
	])('이메일을 보내는 사이 닫혔으면(%i) 닫힌 화면으로 바뀐다', async (status, message) => {
		api.submitJoinEmail.mockRejectedValue(new ApiError(status, message));
		render(JoinPage, { params: { token: 'tok' }, data: open() });
		await submitEmail();
		expect(await screen.findByRole('heading', { level: 1, name: '입장할 수 없습니다' })).toBeTruthy();
		expect(screen.getByText(message)).toBeTruthy();
	});

	it('입장 요청을 보내는 사이 보관됐어도 닫힌 화면으로 바뀐다', async () => {
		api.submitJoinEmail.mockResolvedValue({ next: 'request_access', message: NOT_IN_ROSTER });
		api.requestAccess.mockRejectedValue(new ApiError(403, ARCHIVED));
		render(JoinPage, { params: { token: 'tok' }, data: open() });
		await submitEmail('new@x.kr');
		await fireEvent.click(await screen.findByRole('button', { name: '입장 요청 보내기' }));
		await fireEvent.input(box('이름'), { target: { value: '박' } });
		await fireEvent.input(box('학번'), { target: { value: '1' } });
		await fireEvent.click(screen.getByRole('button', { name: '요청 보내기' }));
		const main = await screen.findByRole('main');
		expect(within(main).getByText(ARCHIVED)).toBeTruthy();
	});
});

// --- 화면 (C14, AC50) ------------------------------------------------------------------------------------------------

describe('모바일 화면 (C14)', () => {
	it('버튼은 큰 크기(48px)이고 화면 폭을 채운다', () => {
		render(JoinPage, { params: { token: 'tok' }, data: open() });
		expect(getCode().className).toContain('btn-lg');
		expect(getCode().className).toContain('w-full');
		expect(box('이메일').className).toContain('input-lg');
	});

	it('브라우저 기본 말풍선 대신 칸 옆의 한국어 안내를 쓴다', () => {
		render(JoinPage, { params: { token: 'tok' }, data: open() });
		expect((getCode().closest('form') as HTMLFormElement).noValidate).toBe(true);
	});
});
