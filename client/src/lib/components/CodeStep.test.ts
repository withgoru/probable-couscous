// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({ verifyCode: vi.fn(), resendCode: vi.fn(), notifyProfessor: vi.fn() }));
vi.mock('#lib/api.js', async (original) => ({
	...(await original<object>()),
	verifyCode: api.verifyCode,
	resendCode: api.resendCode,
	notifyProfessor: api.notifyProfessor
}));

import { ApiError } from '#lib/api.js';
import CodeStep from './CodeStep.svelte';

const NOTIFIED = '교수님께 알렸습니다. 교수님이 알려 주는 코드를 입력하세요.';
const LOST = '연결이 끊겼습니다. 다시 연결되면 이어서 진행합니다.';
const ARCHIVED = '이 강좌는 보관되었습니다. 교수님께 문의해 주세요.';
const NOT_IN_ROSTER = '수강생 명단에 없는 이메일입니다. 수강신청에 쓴 이메일인지 확인하고, 계속 안 되면 교수님께 입장을 요청해 주세요.';

const props = () => ({
	token: 'tok',
	email: 'kim@x.kr',
	waitSeconds: 60,
	onVerified: vi.fn(),
	onBack: vi.fn(),
	onClosed: vi.fn(),
	onNotOnRoster: vi.fn()
});
const codeError = (message: string, outcome: string, remaining: number | null) =>
	new ApiError(422, message, 'code', { outcome, remaining });

beforeEach(() => {
	api.verifyCode.mockReset();
	api.resendCode.mockReset();
	api.notifyProfessor.mockReset();
});
afterEach(() => {
	cleanup();
	vi.useRealTimers();
});

const codeBox = () => screen.getByLabelText('인증 코드 6자리') as HTMLInputElement;
const keep = () => screen.getByLabelText('이 기기에서 로그인 유지') as HTMLInputElement;
const confirm = () => screen.getByRole('button', { name: '확인하고 계속' });
const resend = () => screen.getByRole('button', { name: /코드 다시 받기/ }) as HTMLButtonElement;
async function typeCode(value: string) {
	await fireEvent.input(codeBox(), { target: { value } });
}

// --- 입력 (AC25, AC26) -----------------------------------------------------------------------------------------------

describe('코드 입력 (AC25, AC26)', () => {
	it('보낸 주소와 이 기기에서 입력해야 한다는 안내가 보인다', () => {
		render(CodeStep, props());
		expect(screen.getByRole('heading', { level: 1, name: '인증 코드를 입력하세요' })).toBeTruthy();
		expect(document.body.textContent).toContain('6자리 코드를 보냈습니다: kim@x.kr');
		expect(screen.getByText('코드는 지금 이 화면을 연 기기에서 입력해야 합니다.')).toBeTruthy();
	});

	it('6자리 숫자 칸은 72px 크기이고 휴대폰에서 숫자 키패드와 메일 코드 자동 채우기를 쓴다', () => {
		render(CodeStep, props());
		const box = codeBox();
		expect(box.className).toContain('h-[72px]');
		expect(box.getAttribute('inputmode')).toBe('numeric');
		expect(box.getAttribute('autocomplete')).toBe('one-time-code');
		// 브라우저의 maxlength는 공백까지 세어 "123 456"을 "12345"로 자른다. 자르기는 입력 처리가 숫자만 세어 한다
		expect(box.hasAttribute('maxlength')).toBe(false);
	});

	it("'이 기기에서 로그인 유지'는 처음부터 켜져 있고 '확인하고 계속' 버튼이 있다", () => {
		render(CodeStep, props());
		expect(keep().checked).toBe(true);
		expect(confirm().className).toContain('btn-lg');
	});

	it('7자리 이상 들어오면 앞의 6자리만 남는다', async () => {
		render(CodeStep, props());
		await typeCode('1234567');
		expect(codeBox().value).toBe('123456');
	});

	it('숫자가 아닌 글자와 공백은 칸에 남지 않는다(복사한 코드의 공백 포함)', async () => {
		render(CodeStep, props());
		await typeCode(' 12 3a4-56 ');
		expect(codeBox().value).toBe('123456');
	});

	it('6자리가 아니면 서버를 부르지 않고 칸 옆에 알려 준다', async () => {
		render(CodeStep, props());
		await typeCode('123');
		await fireEvent.click(confirm());
		expect(api.verifyCode).not.toHaveBeenCalled();
		expect(codeBox().getAttribute('aria-invalid')).toBe('true');
		expect(document.getElementById(codeBox().getAttribute('aria-describedby') ?? '')?.textContent).toContain(
			'6자리를 모두 입력해 주세요.'
		);
	});

	it('맞으면 닉네임을 넘겨주고, 로그인 유지 선택을 함께 보낸다', async () => {
		api.verifyCode.mockResolvedValue({ next: 'notice', nickname: '느긋한 고래' });
		const p = props();
		render(CodeStep, p);
		await typeCode('123456');
		await fireEvent.click(keep()); // 끈다
		await fireEvent.click(confirm());
		await waitFor(() => expect(p.onVerified).toHaveBeenCalledWith('느긋한 고래'));
		expect(api.verifyCode).toHaveBeenCalledWith('tok', { email: 'kim@x.kr', code: '123456', keep_login: false });
	});

	it('확인하는 동안에는 다시 누를 수 없다', async () => {
		let finish: (v: unknown) => void = () => {};
		api.verifyCode.mockReturnValue(new Promise((r) => (finish = r)));
		render(CodeStep, props());
		await typeCode('123456');
		await fireEvent.click(confirm());
		const busy = screen.getByRole('button', { name: '확인하는 중…' }) as HTMLButtonElement;
		expect(busy.disabled).toBe(true);
		await fireEvent.submit(busy.closest('form') as HTMLFormElement);
		expect(api.verifyCode).toHaveBeenCalledTimes(1);
		finish({ next: 'notice', nickname: 'x' });
	});
});

// --- 오류 (AC30, AC31, AC33, AC47) -----------------------------------------------------------------------------------

describe('코드 오류 (AC30, AC31, AC33)', () => {
	it.each([
		['코드가 맞지 않습니다. 4번 더 입력할 수 있습니다.', 'wrong', 4],
		['코드가 맞지 않습니다.', 'wrong', null], // 다른 기기(AC33): 남은 횟수 없이 같은 문구
		['코드를 다시 받아 주세요.', 'locked', 0],
		['코드가 만료되었습니다. 코드를 다시 받아 주세요.', 'expired', null],
		['이미 사용된 코드입니다. 코드를 다시 받아 주세요.', 'used', null]
	])('서버의 안내 "%s"를 칸 옆에 그대로 보인다', async (message, outcome, remaining) => {
		api.verifyCode.mockRejectedValue(codeError(message, outcome, remaining));
		render(CodeStep, props());
		await typeCode('123456');
		await fireEvent.click(confirm());
		await waitFor(() => expect(codeBox().getAttribute('aria-invalid')).toBe('true'));
		expect(screen.getByText(message)).toBeTruthy();
		expect(document.activeElement).toBe(codeBox());
	});

	it('틀린 코드는 다시 쓰기 쉽게 지우고 칸으로 포커스를 돌린다', async () => {
		api.verifyCode.mockRejectedValue(codeError('코드가 맞지 않습니다. 4번 더 입력할 수 있습니다.', 'wrong', 4));
		render(CodeStep, props());
		await typeCode('123456');
		await fireEvent.click(confirm());
		await waitFor(() => expect(codeBox().value).toBe(''));
	});

	it('다시 쓰기 시작하면 오류 표시가 사라진다', async () => {
		api.verifyCode.mockRejectedValue(codeError('코드가 맞지 않습니다.', 'wrong', null));
		render(CodeStep, props());
		await typeCode('123456');
		await fireEvent.click(confirm());
		await screen.findByText('코드가 맞지 않습니다.');
		await typeCode('1');
		expect(screen.queryByText('코드가 맞지 않습니다.')).toBeNull();
	});

	it('코드를 받은 뒤 명단에서 빠졌으면 명단 밖 안내로 넘긴다', async () => {
		api.verifyCode.mockResolvedValue({ next: 'request_access', message: NOT_IN_ROSTER });
		const p = props();
		render(CodeStep, p);
		await typeCode('123456');
		await fireEvent.click(confirm());
		await waitFor(() => expect(p.onNotOnRoster).toHaveBeenCalledWith(NOT_IN_ROSTER));
	});

	it.each([404, 403])('그사이 링크가 닫혔으면(%i) 닫힌 화면으로 넘긴다', async (status) => {
		api.verifyCode.mockRejectedValue(new ApiError(status, ARCHIVED));
		const p = props();
		render(CodeStep, p);
		await typeCode('123456');
		await fireEvent.click(confirm());
		await waitFor(() => expect(p.onClosed).toHaveBeenCalledWith(ARCHIVED));
	});
});

// --- 도움 카드 (AC32, AC44) ------------------------------------------------------------------------------------------

describe('도움 카드 (AC44)', () => {
	it("'메일이 오지 않나요?'와 세 버튼이 있다", () => {
		render(CodeStep, props());
		expect(screen.getByText('메일이 오지 않나요?')).toBeTruthy();
		expect(resend()).toBeTruthy();
		expect(screen.getByRole('button', { name: '이메일 다시 입력' })).toBeTruthy();
		expect(screen.getByRole('button', { name: '교수님께 알리기' })).toBeTruthy();
	});

	it("'이메일 다시 입력'은 이메일 단계로 돌려보낸다", async () => {
		const p = props();
		render(CodeStep, p);
		await fireEvent.click(screen.getByRole('button', { name: '이메일 다시 입력' }));
		expect(p.onBack).toHaveBeenCalled();
	});

	it("'교수님께 알리기'를 누르면 알렸다는 문구가 보이고 버튼은 사라진다", async () => {
		api.notifyProfessor.mockResolvedValue({ next: 'notified', message: NOTIFIED });
		render(CodeStep, props());
		await fireEvent.click(screen.getByRole('button', { name: '교수님께 알리기' }));
		expect((await screen.findByRole('status')).textContent).toContain(NOTIFIED);
		expect(api.notifyProfessor).toHaveBeenCalledWith('tok', 'kim@x.kr');
		expect(screen.queryByRole('button', { name: '교수님께 알리기' })).toBeNull();
		expect(codeBox()).toBeTruthy(); // 교수님이 알려 주는 코드를 같은 칸에 입력한다
	});

	it('알릴 수 없으면(코드가 만료됨 등) 서버의 안내를 보인다', async () => {
		api.notifyProfessor.mockRejectedValue(new ApiError(422, '코드가 만료되었습니다. 코드를 다시 받아 주세요.', null));
		render(CodeStep, props());
		await fireEvent.click(screen.getByRole('button', { name: '교수님께 알리기' }));
		expect((await screen.findByRole('alert')).textContent).toContain('코드가 만료되었습니다. 코드를 다시 받아 주세요.');
		expect(screen.getByRole('button', { name: '교수님께 알리기' })).toBeTruthy();
	});
});

describe('코드 다시 받기 (AC32)', () => {
	it('처음 60초 동안은 누를 수 없고 남은 초가 글로 보이며 1초마다 줄어든다', async () => {
		vi.useFakeTimers({ shouldAdvanceTime: true });
		render(CodeStep, props());
		expect(resend().disabled).toBe(true);
		expect(screen.getByText('60초 뒤에 다시 받을 수 있습니다.')).toBeTruthy();
		await vi.advanceTimersByTimeAsync(18_000);
		expect(screen.getByText('42초 뒤에 다시 받을 수 있습니다.')).toBeTruthy();
		await vi.advanceTimersByTimeAsync(42_000);
		expect(resend().disabled).toBe(false);
		expect(screen.queryByText(/초 뒤에 다시 받을 수 있습니다/)).toBeNull();
	});

	it('서버가 알려 준 남은 시간으로 시작한다(새로고침 없이 이어 온 경우)', () => {
		render(CodeStep, { ...props(), waitSeconds: 25 });
		expect(screen.getByText('25초 뒤에 다시 받을 수 있습니다.')).toBeTruthy();
	});

	it('60초 뒤에 누르면 새 코드를 받고, 이전 코드는 쓸 수 없다고 알리고, 다시 60초를 센다', async () => {
		vi.useFakeTimers({ shouldAdvanceTime: true });
		api.resendCode.mockResolvedValue({ next: 'code', wait_seconds: 60 });
		render(CodeStep, props());
		await vi.advanceTimersByTimeAsync(60_000);
		await fireEvent.click(resend());
		expect((await screen.findByRole('status')).textContent).toContain('새 코드를 보냈습니다. 이전 코드는 쓸 수 없습니다.');
		expect(api.resendCode).toHaveBeenCalledWith('tok', 'kim@x.kr');
		expect(resend().disabled).toBe(true);
		expect(screen.getByText('60초 뒤에 다시 받을 수 있습니다.')).toBeTruthy();
	});

	it('새 코드를 받으면 교수님께 다시 알릴 수 있다(이전 알림은 이전 코드의 것)', async () => {
		vi.useFakeTimers({ shouldAdvanceTime: true });
		api.notifyProfessor.mockResolvedValue({ next: 'notified', message: NOTIFIED });
		api.resendCode.mockResolvedValue({ next: 'code', wait_seconds: 60 });
		render(CodeStep, props());
		await fireEvent.click(screen.getByRole('button', { name: '교수님께 알리기' }));
		await screen.findByText(NOTIFIED);
		await vi.advanceTimersByTimeAsync(60_000);
		await fireEvent.click(resend());
		expect(await screen.findByRole('button', { name: '교수님께 알리기' })).toBeTruthy();
	});

	it('너무 빨리 눌렀다고 서버가 답하면 그 남은 시간으로 다시 센다', async () => {
		vi.useFakeTimers({ shouldAdvanceTime: true });
		api.resendCode.mockRejectedValue(new ApiError(429, '코드는 7초 뒤에 다시 받을 수 있습니다.', null, { wait_seconds: 7 }));
		render(CodeStep, { ...props(), waitSeconds: 0 });
		await fireEvent.click(resend());
		expect(await screen.findByText('7초 뒤에 다시 받을 수 있습니다.')).toBeTruthy();
		expect(resend().disabled).toBe(true);
	});

	it('다시 받는 사이 명단에서 빠졌으면 명단 밖 안내로 넘긴다', async () => {
		api.resendCode.mockResolvedValue({ next: 'request_access', message: NOT_IN_ROSTER });
		const p = { ...props(), waitSeconds: 0 };
		render(CodeStep, p);
		await fireEvent.click(resend());
		await waitFor(() => expect(p.onNotOnRoster).toHaveBeenCalledWith(NOT_IN_ROSTER));
	});
});

// --- 연결 끊김 (스펙 '입력 중 연결 끊김', C12) -----------------------------------------------------------------------

describe('연결이 끊겼을 때', () => {
	it('확인 중 연결이 안 되면 입력한 코드를 그대로 두고 이어서 진행한다고 알린다', async () => {
		api.verifyCode.mockRejectedValue(new TypeError('Failed to fetch'));
		render(CodeStep, props());
		await typeCode('123456');
		await fireEvent.click(confirm());
		expect((await screen.findByRole('status')).textContent).toContain(LOST);
		expect(codeBox().value).toBe('123456');
		expect(document.body.textContent).toContain('kim@x.kr'); // 입력한 이메일도 유지된다
	});

	it('브라우저가 오프라인이 되면 바로 알리고, 다시 연결되면 안내를 거둔다', async () => {
		render(CodeStep, props());
		await typeCode('12');
		window.dispatchEvent(new Event('offline'));
		expect((await screen.findByRole('status')).textContent).toContain(LOST);
		window.dispatchEvent(new Event('online'));
		await waitFor(() => expect(screen.queryByText(LOST)).toBeNull());
		expect(codeBox().value).toBe('12'); // 같은 단계에서 계속한다
	});

	it('다시 받기나 알리기에서 연결이 안 돼도 같은 안내를 보인다', async () => {
		api.notifyProfessor.mockRejectedValue(new TypeError('Failed to fetch'));
		render(CodeStep, props());
		await fireEvent.click(screen.getByRole('button', { name: '교수님께 알리기' }));
		expect((await screen.findByRole('status')).textContent).toContain(LOST);
	});

	it('다시 연결된 뒤 확인하면 그대로 진행된다', async () => {
		api.verifyCode.mockRejectedValueOnce(new TypeError('Failed to fetch')).mockResolvedValueOnce({ next: 'notice', nickname: 'x' });
		const p = props();
		render(CodeStep, p);
		await typeCode('123456');
		await fireEvent.click(confirm());
		await screen.findByText(LOST);
		window.dispatchEvent(new Event('online'));
		await fireEvent.click(confirm());
		await waitFor(() => expect(p.onVerified).toHaveBeenCalledWith('x'));
	});
});

// --- 화면 (C14) ------------------------------------------------------------------------------------------------------

describe('모바일 화면 (C14)', () => {
	it('체크 상자는 손가락으로 누르기 쉬운 줄 높이(44px)를 가진다', () => {
		render(CodeStep, props());
		expect((keep().closest('label') as HTMLElement).className).toContain('min-h-11');
	});

	it('도움 카드의 버튼도 44px 이상이다(btn 기본 높이)', () => {
		render(CodeStep, props());
		for (const b of [resend(), screen.getByRole('button', { name: '이메일 다시 입력' })]) {
			expect(b.className).toContain('btn');
			expect(b.className).not.toContain('btn-sm');
		}
	});
});
