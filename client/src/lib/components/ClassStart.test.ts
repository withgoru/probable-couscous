// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const nav = vi.hoisted(() => ({ goto: vi.fn(() => Promise.resolve()) }));
const api = vi.hoisted(() => ({ startSession: vi.fn(), resumeSession: vi.fn() }));
vi.mock('$app/navigation', () => nav);
vi.mock('#lib/api.js', async (original) => ({
	...(await original<object>()),
	startSession: api.startSession,
	resumeSession: api.resumeSession
}));

import { ApiError, type ClassSession } from '#lib/api.js';
import ClassStart from './ClassStart.svelte';

const DECK = { id: 9, original_name: 'a.zip', slide_count: 4, size_bytes: 1, uploaded_at: 'x', available: true };
const session = (id: number, title: string, status: ClassSession['status'], deck: typeof DECK | null = DECK): ClassSession => ({
	id,
	title,
	status,
	sort_order: id,
	created_at: 'x',
	can_delete: status === 'scheduled',
	deck
});

function setup(selected: ClassSession, others: ClassSession[] = [], archived = false) {
	const onChanged = vi.fn(() => Promise.resolve());
	const onSelect = vi.fn();
	render(ClassStart, {
		classroomId: 7,
		archived,
		session: selected,
		sessions: [selected, ...others],
		onChanged,
		onSelect
	});
	return { onChanged, onSelect };
}

const LIVE_ELSEWHERE = '1회차 수업이 진행 중입니다. 먼저 끝내 주세요.';

beforeEach(() => {
	nav.goto.mockClear();
	api.startSession.mockReset();
	api.resumeSession.mockReset();
});
afterEach(cleanup);

describe('수업 시작 (AC9)', () => {
	it('예정 회차에 수업 시작이 보이고, 누르면 시작한 뒤 교수 수업 화면으로 간다', async () => {
		api.startSession.mockResolvedValue({ ...session(3, '3회차', 'live'), version: 1 });
		const { onChanged } = setup(session(3, '3회차', 'scheduled'));
		await fireEvent.click(screen.getByRole('button', { name: '수업 시작' }));
		await waitFor(() => expect(nav.goto).toHaveBeenCalledWith('/courses/7/live'));
		expect(api.startSession).toHaveBeenCalledWith(7, 3);
		expect(onChanged).toHaveBeenCalled();
	});

	it('슬라이드가 없으면 먼저 확인한다', async () => {
		api.startSession.mockResolvedValue({ ...session(3, '3회차', 'live', null), version: 1 });
		setup(session(3, '3회차', 'scheduled', null));
		await fireEvent.click(screen.getByRole('button', { name: '수업 시작' }));
		const dialog = await screen.findByRole('alertdialog');
		expect(dialog.textContent).toContain('슬라이드 없이 시작할까요?');
		expect(dialog.textContent).toContain('메시지·자료 보내기만 쓸 수 있습니다.');
		expect(api.startSession).not.toHaveBeenCalled();
		await fireEvent.click(within(dialog).getByRole('button', { name: '슬라이드 없이 시작' }));
		await waitFor(() => expect(nav.goto).toHaveBeenCalledWith('/courses/7/live'));
	});

	it('열 수 없는 묶음도 슬라이드가 없는 것과 같이 확인한다', async () => {
		setup(session(3, '3회차', 'scheduled', { ...DECK, available: false }));
		await fireEvent.click(screen.getByRole('button', { name: '수업 시작' }));
		expect((await screen.findByRole('alertdialog')).textContent).toContain('슬라이드 없이 시작할까요?');
	});

	it('시작하는 동안에는 다시 누를 수 없다', async () => {
		api.startSession.mockReturnValue(new Promise(() => {}));
		setup(session(3, '3회차', 'scheduled'));
		const button = screen.getByRole('button', { name: '수업 시작' }) as HTMLButtonElement;
		await fireEvent.click(button);
		await fireEvent.click(button);
		expect(api.startSession).toHaveBeenCalledTimes(1);
		expect(screen.getByRole('button', { name: '시작하는 중…' })).toBeTruthy();
	});
});

describe('다른 회차가 진행 중 (AC10)', () => {
	it('수업 시작 대신 안내와 그 회차로 가는 버튼이 보인다', async () => {
		const { onSelect } = setup(session(3, '3회차', 'scheduled'), [session(1, '1회차', 'live')]);
		expect(screen.queryByRole('button', { name: '수업 시작' })).toBeNull();
		expect(screen.getByText(LIVE_ELSEWHERE)).toBeTruthy();
		await fireEvent.click(screen.getByRole('button', { name: '1회차로 가기' }));
		expect(onSelect).toHaveBeenCalledWith(1);
	});

	it('종료 회차의 이어서 하기도 같다 (AC40)', () => {
		setup(session(3, '3회차', 'ended'), [session(1, '1회차', 'live')]);
		expect(screen.queryByRole('button', { name: '이어서 수업하기' })).toBeNull();
		expect(screen.getByText(LIVE_ELSEWHERE)).toBeTruthy();
	});

	it('그 사이 다른 화면에서 시작해 서버가 거절하면 안내와 이동 버튼을 보이고 목록을 다시 불러온다', async () => {
		api.startSession.mockRejectedValue(new ApiError(409, LIVE_ELSEWHERE, undefined, { live_session_id: 1 }));
		const { onChanged, onSelect } = setup(session(3, '3회차', 'scheduled'));
		await fireEvent.click(screen.getByRole('button', { name: '수업 시작' }));
		expect((await screen.findByRole('alert')).textContent).toContain(LIVE_ELSEWHERE);
		expect(onChanged).toHaveBeenCalled();
		await fireEvent.click(screen.getByRole('button', { name: '진행 중인 회차로 가기' }));
		expect(onSelect).toHaveBeenCalledWith(1);
		expect(nav.goto).not.toHaveBeenCalled();
	});
});

describe('보관된 강좌 (AC11)', () => {
	it('수업 시작이 보이지 않고 안내가 보인다', () => {
		setup(session(3, '3회차', 'scheduled'), [], true);
		expect(screen.queryByRole('button', { name: '수업 시작' })).toBeNull();
		expect(screen.getByText('보관된 강좌는 수업을 시작할 수 없습니다.')).toBeTruthy();
	});

	it('종료 회차도 이어서 할 수 없다', () => {
		setup(session(3, '3회차', 'ended'), [], true);
		expect(screen.queryByRole('button', { name: '이어서 수업하기' })).toBeNull();
		expect(screen.getByText('보관된 강좌는 수업을 시작할 수 없습니다.')).toBeTruthy();
	});
});

describe('진행 중인 회차 (AC18)', () => {
	it('수업 화면으로 버튼이 교수 수업 화면을 연다', () => {
		setup(session(3, '3회차', 'live'));
		const link = screen.getByRole('link', { name: '수업 화면으로' });
		expect(link.getAttribute('href')).toBe('/courses/7/live');
		expect(link.className).toContain('btn btn-default');
		expect(screen.queryByRole('button', { name: '수업 시작' })).toBeNull();
	});
});

describe('종료 회차 (AC40)', () => {
	it('이어서 수업하기를 누르면 이어서 하고 교수 수업 화면으로 간다', async () => {
		api.resumeSession.mockResolvedValue({ ...session(3, '3회차', 'live'), version: 4 });
		const { onChanged } = setup(session(3, '3회차', 'ended'));
		expect(screen.getByText('마지막 위치에서 이어지고, 보낸 항목도 그대로입니다.')).toBeTruthy();
		await fireEvent.click(screen.getByRole('button', { name: '이어서 수업하기' }));
		await waitFor(() => expect(nav.goto).toHaveBeenCalledWith('/courses/7/live'));
		expect(api.resumeSession).toHaveBeenCalledWith(7, 3);
		expect(onChanged).toHaveBeenCalled();
	});

	it('그 밖의 거절은 이유와 할 일을 보인다', async () => {
		api.resumeSession.mockRejectedValue(new TypeError('Failed to fetch'));
		setup(session(3, '3회차', 'ended'));
		await fireEvent.click(screen.getByRole('button', { name: '이어서 수업하기' }));
		const alert = await screen.findByRole('alert');
		expect(alert.textContent).toContain('수업을 시작하지 못했습니다.');
		expect(alert.textContent).toContain('네트워크 연결을 확인하고 다시 시도해 주세요.');
	});
});
