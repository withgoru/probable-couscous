// @vitest-environment jsdom
import { act, cleanup, render, screen, waitFor, within } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { LiveState } from '#lib/classLive.js';
import type { DeckSnapshot } from '#lib/deckBridge.js';

type FakeDeck = { listener: ((s: DeckSnapshot) => void) | null; onIntent?: (d: 'next' | 'prev') => void; goto: ReturnType<typeof vi.fn>; setMode: ReturnType<typeof vi.fn>; setLimit: ReturnType<typeof vi.fn>; stop: ReturnType<typeof vi.fn> };
const decks = vi.hoisted(() => ({ all: [] as FakeDeck[] }));
vi.mock('#lib/deckBridge.js', () => ({
	connectDeck: (_frame: unknown, options: { onIntent?: (d: 'next' | 'prev') => void } = {}) => {
		const deck: FakeDeck = { listener: null, onIntent: options.onIntent, goto: vi.fn(), setMode: vi.fn(), setLimit: vi.fn(), stop: vi.fn() };
		decks.all.push(deck);
		return {
			subscribe: (fn: (s: DeckSnapshot) => void) => {
				deck.listener = fn;
				return () => {};
			},
			goto: deck.goto,
			setMode: deck.setMode,
			setLimit: deck.setLimit,
			stop: deck.stop
		};
	}
}));
const api = vi.hoisted(() => ({ fetchClassLive: vi.fn() }));
vi.mock('#lib/api.js', async (original) => ({ ...(await original<object>()), fetchClassLive: api.fetchClassLive }));

import ReplayView from './ReplayView.svelte';

const ENDED: LiveState = {
	session: { id: 4, title: '2주차 2회차', status: 'ended', version: 9 },
	deck: { id: 8, slide_count: 4, available: true, public: true },
	current: { slide: 2, click: 1 },
	limit: { slide: 3, click: 0 },
	items: [
		{ id: 1, body: '첫 자료', url: null, created_at: '2026-02-26T05:01:00+00:00' },
		{ id: 2, body: null, url: 'https://example.com/b', created_at: '2026-02-26T05:02:00+00:00' }
	]
};

function mount(props: { start?: 'first' | 'last'; ended?: boolean } = {}) {
	const onBack = vi.fn();
	render(ReplayView, { classroomId: 7, sessionId: 4, onBack, ...props });
	return { onBack };
}
const deck = () => decks.all[0];
async function drawn(position: { slide: number; click: number }, clicksTotal: number) {
	await act(() => deck().listener?.({ ready: true, total: 4, position: { ...position }, clicksTotal }));
}
const button = (name: string) => screen.getByRole('button', { name }) as HTMLButtonElement;

beforeEach(() => {
	decks.all = [];
	api.fetchClassLive.mockReset();
	api.fetchClassLive.mockResolvedValue(structuredClone(ENDED));
	vi.stubGlobal('IntersectionObserver', undefined);
});
afterEach(() => {
	cleanup();
	vi.unstubAllGlobals();
});

describe('지난 회차 다시 보기 (AC39)', () => {
	it('그 회차의 상태를 받아 이름과 슬라이드, 거두지 않은 자료를 보인다', async () => {
		mount();
		expect(await screen.findByRole('heading', { level: 1, name: '2주차 2회차 다시 보기' })).toBeTruthy();
		expect(api.fetchClassLive).toHaveBeenCalledWith(7, 4);
		expect((screen.getByTitle('다시 보는 슬라이드') as HTMLIFrameElement).getAttribute('src')).toBe('/decks/8/');
		const list = screen.getByRole('list', { name: '자료' });
		expect(within(list).getAllByRole('listitem')).toHaveLength(2);
		expect(screen.queryByText(/따라가는 중/)).toBeNull();
	});

	it('처음부터 넘겨 보며, 직접 넘겨 보기 모양이다', async () => {
		mount();
		await screen.findByTitle('다시 보는 슬라이드');
		expect(deck().setMode).toHaveBeenCalledWith('browse');
		expect(deck().setLimit).toHaveBeenLastCalledWith({ slide: 3, click: 0 });
		expect(deck().goto).toHaveBeenLastCalledWith({ slide: 1, click: 0 });
	});

	it('가장 멀리 간 위치까지만 넘기고, 끝에서 다음이 흐려지고 안내가 보인다', async () => {
		mount();
		await screen.findByTitle('다시 보는 슬라이드');
		await drawn({ slide: 1, click: 0 }, 0);
		await act(() => button('다음').click());
		expect(deck().goto).toHaveBeenLastCalledWith({ slide: 2, click: 0 });
		await drawn({ slide: 2, click: 0 }, 1);
		await act(() => button('다음').click());
		await drawn({ slide: 2, click: 1 }, 1);
		await act(() => button('다음').click());
		await drawn({ slide: 3, click: 0 }, 2);
		expect(button('다음').getAttribute('aria-disabled')).toBe('true');
		expect(screen.getByText('수업에서 보여 주지 않은 슬라이드입니다.')).toBeTruthy();
		const calls = deck().goto.mock.calls.length;
		await act(() => button('다음').click());
		await act(() => deck().onIntent?.('next'));
		expect(deck().goto.mock.calls.length).toBe(calls);
	});

	it('이전과 슬라이드 안의 넘기기, ←·→도 된다', async () => {
		mount({ start: 'last' });
		await screen.findByTitle('다시 보는 슬라이드');
		await drawn({ slide: 2, click: 1 }, 1);
		await act(() => deck().onIntent?.('prev'));
		expect(deck().goto).toHaveBeenLastCalledWith({ slide: 2, click: 0 });
		await drawn({ slide: 2, click: 0 }, 1);
		await act(() => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight' })));
		expect(deck().goto).toHaveBeenLastCalledWith({ slide: 2, click: 1 });
	});

	it('묶음을 바꾼 회차는 가장 멀리 간 슬라이드의 단계 전부까지다 (AC41)', async () => {
		api.fetchClassLive.mockResolvedValue({ ...structuredClone(ENDED), limit: { slide: 3, click: null } });
		mount();
		await screen.findByTitle('다시 보는 슬라이드');
		expect(deck().setLimit.mock.calls.at(-1)?.[0]).toMatchObject({ slide: 3 });
		expect(deck().setLimit.mock.calls.at(-1)?.[0].click).toBeGreaterThanOrEqual(999);
	});

	it('목록으로 돌아갈 수 있다', async () => {
		const { onBack } = mount();
		await screen.findByTitle('다시 보는 슬라이드');
		await act(() => button('지난 회차 목록으로').click());
		expect(onBack).toHaveBeenCalled();
	});

	it('슬라이드가 없거나 열 수 없는 회차는 자료만 보인다', async () => {
		api.fetchClassLive.mockResolvedValue({ ...structuredClone(ENDED), deck: null });
		mount();
		expect(await screen.findByText('이 회차는 슬라이드 없이 진행했습니다.')).toBeTruthy();
		expect(screen.getByRole('list', { name: '자료' })).toBeTruthy();
		cleanup();
		api.fetchClassLive.mockResolvedValue({ ...structuredClone(ENDED), deck: { id: 8, slide_count: 4, available: false, public: false } });
		mount();
		expect(await screen.findByText('슬라이드를 열 수 없습니다. 자료는 계속 볼 수 있습니다.')).toBeTruthy();
	});

	it('비공개 묶음이면 슬라이드 대신 공개되지 않았다고 알리고 자료만 보인다 (AC39, AC50)', async () => {
		// 서버가 비공개 묶음 파일을 학생에게 내주지 않으므로 iframe을 얹지 않는다. 다시 보기 전체 정리는 T037
		api.fetchClassLive.mockResolvedValue({ ...structuredClone(ENDED), deck: { id: 8, slide_count: 4, available: true, public: false } });
		mount();
		expect(await screen.findByText('이 회차의 슬라이드는 공개되지 않았습니다.')).toBeTruthy();
		expect(screen.queryByTitle('다시 보는 슬라이드')).toBeNull();
		expect(screen.queryByRole('button', { name: '다음' })).toBeNull();
		expect(screen.getByRole('list', { name: '자료' })).toBeTruthy();
	});

	it('불러오지 못하면 이유와 할 일을 보인다', async () => {
		const { ApiError } = await import('#lib/api.js');
		api.fetchClassLive.mockRejectedValue(new ApiError(404, '찾을 수 없는 회차입니다.'));
		mount();
		const alert = await screen.findByRole('alert');
		expect(alert.textContent).toContain('찾을 수 없는 회차입니다.');
		expect(button('지난 회차 목록으로')).toBeTruthy();
	});
});

describe('수업이 끝나 이어지는 다시 보기 (AC38)', () => {
	it('"수업이 끝났습니다."를 보이고 마지막으로 보던 곳에서 이어 본다', async () => {
		mount({ start: 'last', ended: true });
		expect(await screen.findByText('수업이 끝났습니다.')).toBeTruthy();
		await screen.findByTitle('다시 보는 슬라이드');
		expect(deck().goto).toHaveBeenLastCalledWith({ slide: 2, click: 1 });
	});

	it('끝났다는 글은 알림 자리 밖에 둔다(처음부터 있는 글은 읽히지 않아 학생 수업 화면이 알린다)', async () => {
		mount({ start: 'last', ended: true });
		expect((await screen.findByText('수업이 끝났습니다.')).closest('[role="status"]')).toBeNull();
		expect(document.querySelectorAll('[role="status"]:not([data-copy-status]):not([data-arrival])')).toHaveLength(0);
	});

	it('보던 곳이 볼 수 있는 끝이나 묶음 밖이면 끝에서 이어 본다', async () => {
		api.fetchClassLive.mockResolvedValue({ ...structuredClone(ENDED), current: { slide: 6, click: 2 }, limit: { slide: 4, click: null } });
		mount({ start: 'last', ended: true });
		await screen.findByTitle('다시 보는 슬라이드');
		expect(deck().goto).toHaveBeenLastCalledWith({ slide: 4, click: 0 });
		cleanup();
		decks.all = [];
		// 끝이 묶음보다 뒤로 남아 있어도 묶음의 마지막 슬라이드에서
		api.fetchClassLive.mockResolvedValue({ ...structuredClone(ENDED), current: { slide: 5, click: 0 }, limit: { slide: 6, click: null } });
		mount({ start: 'last', ended: true });
		await screen.findByTitle('다시 보는 슬라이드');
		expect(deck().goto).toHaveBeenLastCalledWith({ slide: 4, click: 0 });
	});
});

describe('초점', () => {
	it('초점을 받으라고 하면 제목으로 초점이 간다', async () => {
		render(ReplayView, { classroomId: 7, sessionId: 4, onBack: vi.fn(), takeFocus: true });
		const heading = await screen.findByRole('heading', { level: 1 });
		await waitFor(() => expect(document.activeElement).toBe(heading));
	});

	it('불러오지 못하면 목록으로 버튼에 초점이 간다', async () => {
		const { ApiError } = await import('#lib/api.js');
		api.fetchClassLive.mockRejectedValue(new ApiError(404, '찾을 수 없는 회차입니다.'));
		render(ReplayView, { classroomId: 7, sessionId: 4, onBack: vi.fn(), takeFocus: true });
		await screen.findByRole('alert');
		await waitFor(() => expect(document.activeElement).toBe(button('지난 회차 목록으로')));
	});

	it('초점을 받으라고 하지 않으면 옮기지 않는다', async () => {
		mount({ start: 'last', ended: true });
		await screen.findByRole('heading', { level: 1 });
		await act(() => Promise.resolve());
		expect(document.activeElement).toBe(document.body);
	});
});

describe('넘기기 규칙 (변형 검사 뒤 추가)', () => {
	it('볼 수 있는 끝을 위치보다 먼저 보낸다', async () => {
		mount();
		await screen.findByTitle('다시 보는 슬라이드');
		await drawn({ slide: 1, click: 0 }, 0);
		await act(() => button('다음').click());
		const limitAt = deck().setLimit.mock.invocationCallOrder.at(-1)!;
		const gotoAt = deck().goto.mock.invocationCallOrder.at(-1)!;
		expect(limitAt).toBeLessThan(gotoAt);
	});

	it('묶음의 마지막에서는 그냥 끝이다(안내 없음)', async () => {
		api.fetchClassLive.mockResolvedValue({ ...structuredClone(ENDED), current: { slide: 4, click: 0 }, limit: { slide: 4, click: 0 } });
		mount({ start: 'last' });
		await screen.findByTitle('다시 보는 슬라이드');
		await drawn({ slide: 4, click: 0 }, 0);
		expect(button('다음').getAttribute('aria-disabled')).toBe('true');
		expect(screen.queryByText('수업에서 보여 주지 않은 슬라이드입니다.')).toBeNull();
		expect(button('다음').getAttribute('aria-describedby')).toBeNull();
	});

	it('슬라이드가 그 위치를 그리기 전에는 넘기지 않는다', async () => {
		mount();
		await screen.findByTitle('다시 보는 슬라이드');
		const calls = deck().goto.mock.calls.length;
		await act(() => button('다음').click());
		await act(() => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight' })));
		expect(deck().goto.mock.calls.length).toBe(calls);
	});

	it('처음에서는 이전이 흐려진다', async () => {
		mount();
		await screen.findByTitle('다시 보는 슬라이드');
		await drawn({ slide: 1, click: 0 }, 0);
		expect(button('이전').getAttribute('aria-disabled')).toBe('true');
	});
});
