// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({ uploadDeck: vi.fn(), removeDeck: vi.fn() }));
vi.mock('#lib/api.js', async (original) => ({
	...(await original<object>()),
	uploadDeck: api.uploadDeck,
	removeDeck: api.removeDeck
}));

import { ApiError, type ClassSession, type SessionDeck } from '#lib/api.js';
import DeckSection from './DeckSection.svelte';

const DECK: SessionDeck = {
	id: 9,
	original_name: '3주차 슬라이드.zip',
	slide_count: 12,
	size_bytes: 1024,
	uploaded_at: '2026-03-04T05:05:00+00:00',
	available: true
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
