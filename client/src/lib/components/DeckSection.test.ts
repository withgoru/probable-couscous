// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({ uploadDeck: vi.fn(), removeDeck: vi.fn(), setDeckVisibility: vi.fn() }));
vi.mock('#lib/api.js', async (original) => ({
	...(await original<object>()),
	uploadDeck: api.uploadDeck,
	removeDeck: api.removeDeck,
	setDeckVisibility: api.setDeckVisibility
}));

import { ApiError, type ClassSession, type SessionDeck } from '#lib/api.js';
import DeckSection from './DeckSection.svelte';

const DECK: SessionDeck = {
	id: 9,
	original_name: '3주차 슬라이드.zip',
	slide_count: 12,
	size_bytes: 1024,
	uploaded_at: '2026-03-04T05:05:00+00:00',
	available: true,
	public: false
};
const session = (status: ClassSession['status'], deck: SessionDeck | null = DECK): ClassSession => ({
	id: 3,
	title: '3주차 1회차',
	status,
	sort_order: 3,
	created_at: 'x',
	can_delete: status === 'scheduled',
	deck
});

function setup(s: ClassSession) {
	const onChanged = vi.fn(() => Promise.resolve());
	render(DeckSection, { classroomId: 7, session: s, onChanged });
	return { onChanged };
}

const input = () => screen.getByLabelText(/슬라이드 묶음\(zip\)/) as HTMLInputElement;
async function choose(file: File) {
	await fireEvent.change(input(), { target: { files: [file] } });
}

beforeEach(() => {
	api.uploadDeck.mockReset();
	api.removeDeck.mockReset();
	api.setDeckVisibility.mockReset();
});
afterEach(cleanup);

describe('묶음 표시 (AC5)', () => {
	it('올렸으면 업로드됨 배지와 파일 이름, 올린 시각, 슬라이드 수가 보인다', () => {
		setup(session('scheduled'));
		const section = screen.getByRole('region', { name: '이 회차의 자료' });
		expect(within(section).getByText('업로드됨')).toBeTruthy();
		expect(within(section).getByText('3주차 슬라이드.zip')).toBeTruthy();
		expect(within(section).getByText(/슬라이드 12장/)).toBeTruthy();
		expect(section.textContent).toMatch(/올린 시각 .*\d{2}:\d{2}/);
		expect(within(section).queryByText('비어 있음')).toBeNull();
	});

	it('올리지 않았으면 비어 있음 배지가 보인다', () => {
		setup(session('scheduled', null));
		expect(screen.getByText('비어 있음')).toBeTruthy();
		expect(screen.queryByText('업로드됨')).toBeNull();
		expect(screen.getByLabelText('슬라이드 묶음(zip) 올리기')).toBeTruthy();
	});

	it('파일이 사라진 묶음은 열 수 없다고 알린다', () => {
		setup(session('scheduled', { ...DECK, available: false }));
		expect(screen.getByRole('alert').textContent).toContain('슬라이드를 열 수 없습니다. 묶음을 다시 올려 주세요.');
	});
});

describe('올리기와 바꾸기 (AC5, AC6)', () => {
	it('zip을 고르면 올리고 목록을 다시 불러온다', async () => {
		api.uploadDeck.mockResolvedValue(DECK);
		const { onChanged } = setup(session('scheduled', null));
		const file = new File(['zip'], 'a.zip', { type: 'application/zip' });
		expect(input().getAttribute('accept')).toBe('.zip,application/zip');
		await choose(file);
		await waitFor(() => expect(onChanged).toHaveBeenCalled());
		expect(api.uploadDeck).toHaveBeenCalledWith(7, 3, file);
		expect((await screen.findByRole('status')).textContent).toContain('올렸습니다: a.zip');
	});

	it('올리는 동안에는 다시 고를 수 없고 진행 중임을 알린다', async () => {
		let finish: (d: SessionDeck) => void = () => {};
		api.uploadDeck.mockReturnValue(new Promise((r) => (finish = r)));
		setup(session('scheduled', null));
		await choose(new File(['zip'], 'a.zip'));
		expect(input().disabled).toBe(true);
		expect(screen.getByText('올리는 중…')).toBeTruthy();
		finish(DECK);
		await waitFor(() => expect(input().disabled).toBe(false));
	});

	it('올린 묶음이 있으면 바꾸기다', () => {
		setup(session('ended'));
		expect(screen.getByLabelText('슬라이드 묶음(zip) 바꾸기')).toBeTruthy();
	});

	it('서버가 거절하면 그 안내를 그대로 보이고 아무것도 바꾸지 않는다', async () => {
		const BAD = '슬라이드 묶음을 읽을 수 없습니다. Slidev로 빌드한 폴더(dist)를 zip으로 묶어 올려 주세요.';
		api.uploadDeck.mockRejectedValue(new ApiError(422, BAD));
		const { onChanged } = setup(session('scheduled', null));
		await choose(new File(['x'], 'b.zip'));
		expect((await screen.findByRole('alert')).textContent).toContain(BAD);
		expect(onChanged).not.toHaveBeenCalled();
		expect(screen.getByText('비어 있음')).toBeTruthy();
	});

	it('너무 크면 서버의 크기 안내를 그대로 보인다', async () => {
		api.uploadDeck.mockRejectedValue(new ApiError(413, '파일이 너무 큽니다. 100MB 이하로 올려 주세요.'));
		setup(session('scheduled', null));
		await choose(new File(['x'], 'big.zip'));
		expect((await screen.findByRole('alert')).textContent).toContain('파일이 너무 큽니다. 100MB 이하로 올려 주세요.');
	});

	it('연결이 끊기면 다시 올리라고 알린다', async () => {
		api.uploadDeck.mockRejectedValue(new TypeError('Failed to fetch'));
		setup(session('scheduled', null));
		await choose(new File(['x'], 'b.zip'));
		expect((await screen.findByRole('alert')).textContent).toContain('네트워크 연결을 확인하고 다시 올려 주세요.');
	});

	it('같은 파일을 다시 골라도 다시 올린다', async () => {
		api.uploadDeck.mockRejectedValueOnce(new TypeError('x')).mockResolvedValueOnce(DECK);
		setup(session('scheduled', null));
		const file = new File(['x'], 'b.zip');
		// jsdom의 파일 칸은 늘 빈 값이라, 화면이 값을 비우는지는 값 넣기를 엿봐서 확인한다
		const cleared: string[] = [];
		Object.defineProperty(input(), 'value', { configurable: true, get: () => '', set: (v: string) => cleared.push(v) });
		await choose(file);
		await screen.findByRole('alert');
		expect(cleared).toContain('');
		await choose(file);
		await waitFor(() => expect(api.uploadDeck).toHaveBeenCalledTimes(2));
	});
});

describe('지우기 (AC7)', () => {
	it('확인한 뒤 지우고 목록을 다시 불러온다', async () => {
		api.removeDeck.mockResolvedValue(undefined);
		const { onChanged } = setup(session('scheduled'));
		await fireEvent.click(screen.getByRole('button', { name: '슬라이드 지우기' }));
		const dialog = await screen.findByRole('alertdialog');
		expect(dialog.textContent).toContain('슬라이드 묶음을 지울까요?');
		expect(dialog.textContent).toContain('3주차 슬라이드.zip');
		await fireEvent.click(within(dialog).getByRole('button', { name: '지우기' }));
		await waitFor(() => expect(onChanged).toHaveBeenCalled());
		expect(api.removeDeck).toHaveBeenCalledWith(7, 3);
	});

	it('올린 묶음이 없으면 지우기가 없다', () => {
		setup(session('scheduled', null));
		expect(screen.queryByRole('button', { name: '슬라이드 지우기' })).toBeNull();
	});
});

describe('진행 중인 회차 (AC7)', () => {
	it('바꾸기와 지우기가 흐려지고 이유가 보인다', () => {
		setup(session('live'));
		expect(input().disabled).toBe(true);
		expect((screen.getByRole('button', { name: '슬라이드 지우기' }) as HTMLButtonElement).disabled).toBe(true);
		const reason = screen.getByText('수업 중에는 슬라이드를 바꿀 수 없습니다.');
		expect(input().getAttribute('aria-describedby')).toContain(reason.id);
	});
});

describe('학생에게 공개 (AC47)', () => {
	const PUBLIC = '공개 · 학생이 언제든 처음부터 끝까지 볼 수 있습니다.';
	const PRIVATE = '비공개 · 학생은 수업 중 교수 화면을 따라갈 때만 봅니다.';
	const toggle = () => screen.getByRole('switch', { name: '학생에게 공개' }) as HTMLButtonElement;

	it('묶음이 있을 때만 스위치가 있고, 새 묶음은 꺼져 있으며 지금 상태를 글로 보인다', () => {
		setup(session('scheduled'));
		expect(toggle().getAttribute('aria-checked')).toBe('false');
		const state = screen.getByText(PRIVATE);
		expect(toggle().getAttribute('aria-describedby')).toContain(state.id);
		cleanup();
		setup(session('scheduled', null));
		expect(screen.queryByRole('switch')).toBeNull();
	});

	it('켜져 있으면 공개 상태 글을 보인다', () => {
		setup(session('ended', { ...DECK, public: true }));
		expect(toggle().getAttribute('aria-checked')).toBe('true');
		expect(screen.getByText(PUBLIC)).toBeTruthy();
	});

	it.each(['scheduled', 'live', 'ended'] as const)('%s 회차에서도 바꿀 수 있다', async (status) => {
		api.setDeckVisibility.mockResolvedValue({ ...DECK, public: true });
		const { onChanged } = setup(session(status));
		expect(toggle().disabled).toBe(false);
		await fireEvent.click(toggle());
		expect(api.setDeckVisibility).toHaveBeenCalledWith(7, 3, true);
		await waitFor(() => expect(onChanged).toHaveBeenCalled());
	});

	it('누르는 즉시 바뀐 상태를 보이고, 저장하는 동안 다시 눌러도 한 번만 보낸다', async () => {
		let answer: (d: SessionDeck) => void = () => {};
		api.setDeckVisibility.mockReturnValue(new Promise((r) => (answer = r)));
		setup(session('scheduled'));
		await fireEvent.click(toggle());
		expect(toggle().getAttribute('aria-checked')).toBe('true');
		expect(screen.getByText(PUBLIC)).toBeTruthy();
		await fireEvent.click(toggle());
		expect(api.setDeckVisibility).toHaveBeenCalledTimes(1);
		answer({ ...DECK, public: true });
	});

	it('켜진 것을 끄면 비공개로 보낸다', async () => {
		api.setDeckVisibility.mockResolvedValue({ ...DECK, public: false });
		setup(session('ended', { ...DECK, public: true }));
		await fireEvent.click(toggle());
		expect(api.setDeckVisibility).toHaveBeenCalledWith(7, 3, false);
	});

	it('바꾸지 못하면 스위치를 되돌리고 이유와 할 일을 보인다', async () => {
		api.setDeckVisibility.mockRejectedValue(new TypeError('Failed to fetch'));
		const { onChanged } = setup(session('scheduled'));
		await fireEvent.click(toggle());
		const alert = await screen.findByRole('alert');
		expect(alert.textContent).toContain('공개 여부를 바꾸지 못했습니다.');
		expect(alert.textContent).toContain('네트워크 연결을 확인하고 다시 눌러 주세요.');
		expect(toggle().getAttribute('aria-checked')).toBe('false');
		expect(screen.getByText(PRIVATE)).toBeTruthy();
		expect(onChanged).not.toHaveBeenCalled();
	});

	it('서버가 거절하면 그 안내를 보인다', async () => {
		api.setDeckVisibility.mockRejectedValue(new ApiError(404, '이 회차에 올린 슬라이드가 없습니다.'));
		setup(session('scheduled'));
		await fireEvent.click(toggle());
		expect((await screen.findByRole('alert')).textContent).toContain('이 회차에 올린 슬라이드가 없습니다.');
		expect(toggle().getAttribute('aria-checked')).toBe('false');
	});

	it('다시 누르면 앞의 오류 안내가 사라진다', async () => {
		api.setDeckVisibility.mockRejectedValueOnce(new TypeError('x')).mockResolvedValueOnce({ ...DECK, public: true });
		setup(session('scheduled'));
		await fireEvent.click(toggle());
		await screen.findByRole('alert');
		await fireEvent.click(toggle());
		await waitFor(() => expect(screen.queryByText('공개 여부를 바꾸지 못했습니다.')).toBeNull());
	});

	it('글자를 눌러도 바뀌고, 누를 수 있는 높이가 44px 이상이다 (AC45)', async () => {
		api.setDeckVisibility.mockResolvedValue({ ...DECK, public: true });
		setup(session('scheduled'));
		const row = toggle().closest('label') as HTMLElement;
		expect(row.className).toMatch(/min-h-11/);
		await fireEvent.click(within(row).getByText('학생에게 공개'));
		expect(api.setDeckVisibility).toHaveBeenCalledWith(7, 3, true);
	});

	it('다른 묶음으로 바뀌면 그 묶음의 상태를 따른다', async () => {
		const view = render(DeckSection, { classroomId: 7, session: session('ended', { ...DECK, public: true }), onChanged: vi.fn() });
		expect(toggle().getAttribute('aria-checked')).toBe('true');
		await view.rerender({ classroomId: 7, session: session('ended', { ...DECK, id: 10, public: false }), onChanged: vi.fn() });
		expect(toggle().getAttribute('aria-checked')).toBe('false');
	});
});

describe('학생에게 공개: 리뷰 뒤 추가', () => {
	const toggle = () => screen.getByRole('switch', { name: '학생에게 공개' }) as HTMLButtonElement;

	it('저장하는 동안 묶음이 바뀌면 새 묶음의 상태를 보인다', async () => {
		api.setDeckVisibility.mockReturnValue(new Promise(() => {}));
		const view = render(DeckSection, { classroomId: 7, session: session('scheduled'), onChanged: vi.fn() });
		await fireEvent.click(toggle());
		expect(toggle().getAttribute('aria-checked')).toBe('true');
		await view.rerender({ classroomId: 7, session: session('scheduled', { ...DECK, id: 10 }), onChanged: vi.fn() });
		expect(toggle().getAttribute('aria-checked')).toBe('false');
	});

	it('묶음을 올리는 동안에는 바꿀 수 없다(새 묶음은 비공개로 시작한다)', async () => {
		api.uploadDeck.mockReturnValue(new Promise(() => {}));
		setup(session('scheduled'));
		await choose(new File(['x'], 'b.zip', { type: 'application/zip' }));
		expect(toggle().disabled).toBe(true);
		await fireEvent.click(toggle());
		expect(api.setDeckVisibility).not.toHaveBeenCalled();
	});

	it('묶음이 이미 지워졌으면 안내하고 구역을 다시 불러온다', async () => {
		api.setDeckVisibility.mockRejectedValue(new ApiError(404, '이 회차에 올린 슬라이드가 없습니다.'));
		const { onChanged } = setup(session('scheduled'));
		await fireEvent.click(toggle());
		expect((await screen.findByRole('alert')).textContent).toContain('이 회차에 올린 슬라이드가 없습니다.');
		await waitFor(() => expect(onChanged).toHaveBeenCalled());
	});

	it('바꾼 뒤 다시 불러오기가 실패해도 바꾸지 못했다고 하지 않는다', async () => {
		api.setDeckVisibility.mockResolvedValue({ ...DECK, public: true });
		const onChanged = vi.fn(() => Promise.reject(new Error('reload failed')));
		render(DeckSection, { classroomId: 7, session: session('scheduled'), onChanged });
		await fireEvent.click(toggle());
		await waitFor(() => expect(onChanged).toHaveBeenCalled());
		await Promise.resolve();
		expect(screen.queryByText('공개 여부를 바꾸지 못했습니다.')).toBeNull();
	});
});
