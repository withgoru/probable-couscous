// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({ approveJoinRequest: vi.fn(), rejectJoinRequest: vi.fn() }));
vi.mock('#lib/api.js', async (original) => ({
	...(await original<object>()),
	approveJoinRequest: api.approveJoinRequest,
	rejectJoinRequest: api.rejectJoinRequest
}));

import { ApiError } from '#lib/api.js';
import JoinRequestsSection from './JoinRequestsSection.svelte';

const REQ = (id: number, name: string, no: string, email: string, at = '2026-03-02T05:05:00+00:00') => ({
	id, name, student_no: no, email, created_at: at
});
const REQUESTS = [REQ(1, '박민수', '20249999', 'park@x.kr'), REQ(2, '최지은', '20248888', 'choi@x.kr')];
const props = (requests: ReturnType<typeof REQ>[] | null = REQUESTS) => ({ classroomId: 7, requests, onDecided: vi.fn() });

beforeEach(() => {
	api.approveJoinRequest.mockReset();
	api.rejectJoinRequest.mockReset();
});
afterEach(cleanup);

const row = (name: string) => screen.getByText(name).closest('li') as HTMLElement;

describe('입장 요청 목록 (AC40)', () => {
	it('제목과 처리 전 요청 수가 보인다', () => {
		render(JoinRequestsSection, props());
		const section = screen.getByRole('region', { name: /입장 요청/ });
		expect(within(section).getByRole('heading', { level: 2 }).textContent).toContain('입장 요청');
		expect(within(section).getByText('2건')).toBeTruthy();
	});

	it('요청마다 이름, 학번, 이메일, 요청 시각과 승인·거절 버튼이 있다', () => {
		render(JoinRequestsSection, props());
		const item = row('박민수');
		expect(item.textContent).toContain('20249999');
		expect(item.textContent).toContain('park@x.kr');
		const time = within(item).getByText(/요청/).querySelector('time') as HTMLTimeElement;
		expect(time.getAttribute('datetime')).toBe('2026-03-02T05:05:00+00:00');
		expect(within(item).getByRole('button', { name: '승인: 박민수 (20249999)' }).textContent?.trim()).toBe('승인');
		expect(within(item).getByRole('button', { name: '거절: 박민수 (20249999)' }).textContent?.trim()).toBe('거절');
	});

	it('요청이 없으면 빈 칸이 아니라 그렇다고 알려 준다', () => {
		render(JoinRequestsSection, props([]));
		expect(screen.getByText('처리할 입장 요청이 없습니다.')).toBeTruthy();
		expect(screen.getByText('0건')).toBeTruthy();
	});

	it('불러오기 전에는 불러오는 중이라고 보인다', () => {
		render(JoinRequestsSection, props(null));
		expect(screen.getByText('불러오는 중…')).toBeTruthy();
		expect(screen.queryByRole('button')).toBeNull();
	});

	it('닉네임은 어디에도 없다 (C9)', () => {
		render(JoinRequestsSection, props());
		expect(document.body.textContent).not.toMatch(/닉네임/);
	});
});

describe('승인과 거절 (AC41, AC42)', () => {
	it('승인하면 서버에 보내고, 명단에 추가됐으며 학생은 이메일 인증부터 한다고 알리고, 목록을 다시 불러오게 한다', async () => {
		api.approveJoinRequest.mockResolvedValue({ id: 1, status: 'approved' });
		const p = props();
		render(JoinRequestsSection, p);
		await fireEvent.click(screen.getByRole('button', { name: '승인: 박민수 (20249999)' }));
		const status = await screen.findByRole('status');
		expect(status.textContent).toContain('박민수 학생을 수강생 명단에 추가했습니다.');
		expect(status.textContent).toContain('이메일 인증');
		expect(api.approveJoinRequest).toHaveBeenCalledWith(7, 1);
		expect(p.onDecided).toHaveBeenCalledWith('approved');
	});

	it('거절하면 서버에 보내고 결과를 알리고 목록을 다시 불러오게 한다', async () => {
		api.rejectJoinRequest.mockResolvedValue({ id: 2, status: 'rejected' });
		const p = props();
		render(JoinRequestsSection, p);
		await fireEvent.click(screen.getByRole('button', { name: '거절: 최지은 (20248888)' }));
		expect((await screen.findByRole('status')).textContent).toContain('최지은 학생의 요청을 거절했습니다.');
		expect(api.rejectJoinRequest).toHaveBeenCalledWith(7, 2);
		expect(p.onDecided).toHaveBeenCalledWith('rejected');
	});

	it('처리하는 동안에는 그 요청의 두 버튼을 다시 누를 수 없다', async () => {
		let finish: (v: unknown) => void = () => {};
		api.approveJoinRequest.mockReturnValue(new Promise((r) => (finish = r)));
		render(JoinRequestsSection, props());
		await fireEvent.click(screen.getByRole('button', { name: '승인: 박민수 (20249999)' }));
		const item = row('박민수');
		for (const b of within(item).getAllByRole('button')) expect((b as HTMLButtonElement).disabled).toBe(true);
		await fireEvent.click(within(item).getAllByRole('button')[1]);
		expect(api.rejectJoinRequest).not.toHaveBeenCalled();
		// 다른 요청은 그대로 처리할 수 있다
		expect((screen.getByRole('button', { name: '승인: 최지은 (20248888)' }) as HTMLButtonElement).disabled).toBe(false);
		finish({ id: 1, status: 'approved' });
	});

	it('명단 규칙에 걸리면(학번 중복, 200명) 서버의 이유를 보이고 요청은 그대로 둔다', async () => {
		api.approveJoinRequest.mockRejectedValue(new ApiError(409, '이미 명단에 있는 학번입니다. 학번을 확인해 주세요.', null));
		const p = props();
		render(JoinRequestsSection, p);
		await fireEvent.click(screen.getByRole('button', { name: '승인: 박민수 (20249999)' }));
		const alert = await screen.findByRole('alert');
		expect(alert.textContent).toContain('박민수');
		expect(alert.textContent).toContain('이미 명단에 있는 학번입니다. 학번을 확인해 주세요.');
		expect(p.onDecided).not.toHaveBeenCalled();
	});

	it('이미 처리된 요청이면(다른 창에서 처리) 이유를 보이고 목록을 다시 불러오게 한다', async () => {
		api.rejectJoinRequest.mockRejectedValue(new ApiError(409, '이미 처리한 요청입니다.', null));
		const p = props();
		render(JoinRequestsSection, p);
		await fireEvent.click(screen.getByRole('button', { name: '거절: 박민수 (20249999)' }));
		expect((await screen.findByRole('alert')).textContent).toContain('이미 처리한 요청입니다.');
		await waitFor(() => expect(p.onDecided).toHaveBeenCalled());
	});

	it('연결이 안 되면 무엇을 하면 되는지 알려 준다', async () => {
		api.approveJoinRequest.mockRejectedValue(new TypeError('Failed to fetch'));
		render(JoinRequestsSection, props());
		await fireEvent.click(screen.getByRole('button', { name: '승인: 박민수 (20249999)' }));
		const alert = await screen.findByRole('alert');
		expect(alert.textContent).toContain('처리하지 못했습니다.');
		expect(alert.textContent).toContain('네트워크 연결을 확인하고 다시 시도해 주세요.');
	});
});
