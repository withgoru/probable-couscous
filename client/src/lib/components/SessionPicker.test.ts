// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({ createSession: vi.fn(), renameSession: vi.fn(), deleteSession: vi.fn() }));
vi.mock('#lib/api.js', async (original) => ({
	...(await original<object>()),
	createSession: api.createSession,
	renameSession: api.renameSession,
	deleteSession: api.deleteSession
}));

import { ApiError, type ClassSession } from '#lib/api.js';
import SessionPicker from './SessionPicker.svelte';

const session = (id: number, title: string, status: ClassSession['status'], can_delete = status === 'scheduled'): ClassSession => ({
	id,
	title,
	status,
	sort_order: id,
	created_at: '2026-03-01T09:00:00+00:00',
	can_delete,
	deck: null
});
const LIST = [session(1, '1주차 1회차', 'ended', false), session(2, '1주차 2회차', 'live', false), session(3, '2주차 1회차', 'scheduled')];

function setup(sessions: ClassSession[] = LIST, selectedId: number | null = 2) {
	const onChanged = vi.fn(() => Promise.resolve());
	const onSelect = vi.fn();
	const view = render(SessionPicker, { classroomId: 7, sessions, selectedId, onChanged, onSelect });
	return { onChanged, onSelect, view };
}

async function openMenu() {
	const trigger = screen.getByRole('button', { name: /회차 선택/ });
	await fireEvent.keyDown(trigger, { key: 'Enter' });
	return screen.findByRole('menu');
}

beforeEach(() => {
	api.createSession.mockReset();
	api.renameSession.mockReset();
	api.deleteSession.mockReset();
});
afterEach(cleanup);

describe('회차가 없을 때 (AC1)', () => {
	it('안내와 회차 만들기가 보이고 선택 버튼은 없다', () => {
		setup([], null);
		expect(screen.getByText('아직 회차가 없습니다. 회차를 만들어 수업을 준비하세요.')).toBeTruthy();
		expect(screen.getByRole('button', { name: '회차 만들기' })).toBeTruthy();
		expect(screen.queryByRole('button', { name: /회차 선택/ })).toBeNull();
	});
});

describe('회차 선택 (AC3)', () => {
	it('선택한 회차의 이름과 상태가 버튼에 글로 보인다', () => {
		setup();
		const trigger = screen.getByRole('button', { name: /회차 선택/ });
		expect(trigger.textContent).toContain('1주차 2회차');
		expect(trigger.textContent).toContain('진행 중');
	});

	it('목록에 모든 회차의 이름과 상태가 글로 보이고, 진행 중은 아이콘과 글로 구분된다', async () => {
		setup();
		const menu = await openMenu();
		const items = within(menu).getAllByRole('menuitemradio');
		expect(items.map((i) => i.textContent?.replace(/\s+/g, ' ').trim())).toEqual([
			'1주차 1회차 종료',
			'1주차 2회차 진행 중',
			'2주차 1회차 예정'
		]);
		expect(items[1].querySelector('svg')).toBeTruthy(); // 색만으로 구분하지 않는다
		expect(items[0].querySelector('svg')).toBeNull();
		expect(items[1].getAttribute('aria-checked')).toBe('true');
	});

	it('진행 중 아이콘은 고른 회차의 표시와 따로다', async () => {
		setup(LIST, 3); // 진행 중인 회차를 고르지 않았다
		const items = within(await openMenu()).getAllByRole('menuitemradio');
		expect(items[1].getAttribute('aria-checked')).toBe('false');
		expect(items[1].querySelectorAll('svg')).toHaveLength(1); // 진행 중 아이콘
		expect(items[2].querySelectorAll('svg')).toHaveLength(1); // 고른 표시
		expect(items[0].querySelectorAll('svg')).toHaveLength(0);
	});

	it('다른 회차를 고르면 그 회차를 알린다', async () => {
		const { onSelect } = setup();
		const menu = await openMenu();
		await fireEvent.click(within(menu).getByRole('menuitemradio', { name: /2주차 1회차/ }));
		expect(onSelect).toHaveBeenCalledWith(3);
	});
});

describe('회차 만들기 (AC2)', () => {
	async function openCreate() {
		const menu = await openMenu();
		await fireEvent.click(within(menu).getByRole('menuitem', { name: '새 회차 만들기' }));
		return screen.findByRole('textbox', { name: '회차 이름' });
	}

	it('이름이 비면 만들기가 흐려지고 이유가 글로 보인다', async () => {
		setup();
		const input = await openCreate();
		const button = screen.getByRole('button', { name: '만들기' }) as HTMLButtonElement;
		expect(button.disabled).toBe(true);
		expect(screen.getByText('회차 이름을 입력해 주세요.')).toBeTruthy();
		await fireEvent.input(input, { target: { value: '   ' } });
		expect(button.disabled).toBe(true);
		await fireEvent.input(input, { target: { value: '3주차 1회차' } });
		expect(button.disabled).toBe(false);
		expect(input.getAttribute('maxlength')).toBe('40');
	});

	it('만들면 목록을 다시 불러오고 새 회차를 고른다', async () => {
		api.createSession.mockResolvedValue(session(4, '3주차 1회차', 'scheduled'));
		const { onChanged, onSelect } = setup();
		const input = await openCreate();
		await fireEvent.input(input, { target: { value: '  3주차 1회차 ' } });
		await fireEvent.click(screen.getByRole('button', { name: '만들기' }));
		await waitFor(() => expect(onSelect).toHaveBeenCalledWith(4));
		expect(api.createSession).toHaveBeenCalledWith(7, '3주차 1회차');
		expect(onChanged).toHaveBeenCalled();
		expect(screen.queryByRole('textbox', { name: '회차 이름' })).toBeNull();
	});

	it('회차가 없을 때의 회차 만들기도 같은 폼을 연다', async () => {
		setup([], null);
		await fireEvent.click(screen.getByRole('button', { name: '회차 만들기' }));
		expect(await screen.findByRole('textbox', { name: '회차 이름' })).toBeTruthy();
	});

	it('서버가 거절하면 그 안내를 보이고 입력한 값을 그대로 둔다', async () => {
		api.createSession.mockRejectedValue(new ApiError(422, '회차 이름은 40자 이하로 입력해 주세요.'));
		setup();
		const input = (await openCreate()) as HTMLInputElement;
		await fireEvent.input(input, { target: { value: '긴 이름' } });
		await fireEvent.click(screen.getByRole('button', { name: '만들기' }));
		expect((await screen.findByRole('alert')).textContent).toContain('회차 이름은 40자 이하로 입력해 주세요.');
		expect(input.value).toBe('긴 이름');
	});

	it('연결이 안 되면 무엇을 하면 되는지 알려 준다', async () => {
		api.createSession.mockRejectedValue(new TypeError('Failed to fetch'));
		setup();
		const input = await openCreate();
		await fireEvent.input(input, { target: { value: '이름' } });
		await fireEvent.click(screen.getByRole('button', { name: '만들기' }));
		expect((await screen.findByRole('alert')).textContent).toContain('네트워크 연결을 확인하고 다시 시도해 주세요.');
	});

	it('취소하면 폼을 닫고 서버를 부르지 않는다', async () => {
		setup();
		await openCreate();
		await fireEvent.click(screen.getByRole('button', { name: '취소' }));
		expect(screen.queryByRole('textbox', { name: '회차 이름' })).toBeNull();
		expect(api.createSession).not.toHaveBeenCalled();
	});
});

describe('이름 바꾸기 (AC4)', () => {
	it('어느 상태의 회차든 이름을 바꿀 수 있다', async () => {
		api.renameSession.mockResolvedValue(session(2, '새 이름', 'live', false));
		const { onChanged } = setup();
		await fireEvent.click(screen.getByRole('button', { name: '이름 바꾸기' }));
		const input = (await screen.findByRole('textbox', { name: '회차 이름' })) as HTMLInputElement;
		expect(input.value).toBe('1주차 2회차');
		await fireEvent.input(input, { target: { value: '새 이름' } });
		await fireEvent.click(screen.getByRole('button', { name: '저장' }));
		await waitFor(() => expect(onChanged).toHaveBeenCalled());
		expect(api.renameSession).toHaveBeenCalledWith(7, 2, '새 이름');
		expect(screen.queryByRole('textbox', { name: '회차 이름' })).toBeNull();
	});
});

describe('삭제 (AC4)', () => {
	it('한 번도 시작하지 않은 예정 회차에만 삭제가 보인다', () => {
		setup(LIST, 2);
		expect(screen.queryByRole('button', { name: '삭제' })).toBeNull();
		cleanup();
		setup(LIST, 1);
		expect(screen.queryByRole('button', { name: '삭제' })).toBeNull();
		cleanup();
		setup(LIST, 3);
		expect(screen.getByRole('button', { name: '삭제' })).toBeTruthy();
	});

	it('확인 문구 뒤에 지우고 목록을 다시 불러온다', async () => {
		api.deleteSession.mockResolvedValue(undefined);
		const { onChanged, onSelect } = setup(LIST, 3);
		await fireEvent.click(screen.getByRole('button', { name: '삭제' }));
		const dialog = await screen.findByRole('alertdialog');
		expect(dialog.textContent).toContain('2주차 1회차 회차를 삭제할까요?');
		expect(dialog.textContent).toContain('올린 슬라이드도 함께 지워집니다.');
		expect(api.deleteSession).not.toHaveBeenCalled();
		await fireEvent.click(within(dialog).getByRole('button', { name: '삭제' }));
		await waitFor(() => expect(onChanged).toHaveBeenCalled());
		expect(api.deleteSession).toHaveBeenCalledWith(7, 3);
		expect(onSelect).toHaveBeenCalledWith(null); // 지운 회차는 더 고를 수 없다
	});

	it('서버가 거절하면 확인 창 안에 이유를 보인다', async () => {
		api.deleteSession.mockRejectedValue(new ApiError(409, '한 번이라도 시작한 회차는 삭제할 수 없습니다.'));
		setup(LIST, 3);
		await fireEvent.click(screen.getByRole('button', { name: '삭제' }));
		const dialog = await screen.findByRole('alertdialog');
		await fireEvent.click(within(dialog).getByRole('button', { name: '삭제' }));
		expect((await within(dialog).findByRole('alert')).textContent).toContain('한 번이라도 시작한 회차는 삭제할 수 없습니다.');
	});
});
