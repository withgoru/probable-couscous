// @vitest-environment jsdom
import { act, cleanup, render, screen, waitFor, within } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { LiveState } from '#lib/classLive.js';
import type { DeckSnapshot } from '#lib/deckBridge.js';

type FakeDeck = { listener: ((s: DeckSnapshot) => void) | null; onIntent?: (d: 'next' | 'prev') => void; goto: ReturnType<typeof vi.fn>; setMode: ReturnType<typeof vi.fn>; stop: ReturnType<typeof vi.fn> };
const decks = vi.hoisted(() => ({ all: [] as FakeDeck[] }));
vi.mock('#lib/deckBridge.js', () => ({
	connectDeck: (_frame: unknown, options: { onIntent?: (d: 'next' | 'prev') => void } = {}) => {
		const deck: FakeDeck = { listener: null, onIntent: options.onIntent, goto: vi.fn(), setMode: vi.fn(), stop: vi.fn() };
		decks.all.push(deck);
		return {
			subscribe: (fn: (s: DeckSnapshot) => void) => {
				deck.listener = fn;
				return () => {};
			},
			goto: deck.goto,
			setMode: deck.setMode,
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
		expect(deck().goto).toHaveBeenLastCalledWith({ slide: 1, click: 0 });
	});

	it('공개 묶음은 끝까지 넘기고, 마지막에서 다음이 흐려진다(범위 안내 문구는 없다)', async () => {
		mount();
		await screen.findByTitle('다시 보는 슬라이드');
		await drawn({ slide: 1, click: 0 }, 0);
		await act(() => button('다음').click());
		expect(deck().goto).toHaveBeenLastCalledWith({ slide: 2, click: 0 });
		await drawn({ slide: 2, click: 0 }, 1);
		await act(() => button('다음').click());
		await drawn({ slide: 2, click: 1 }, 1);
		await act(() => button('다음').click());
		await drawn({ slide: 3, click: 0 }, 0);
		await act(() => button('다음').click()); // 교수가 보여 준 곳(3번) 뒤로도 간다
		expect(deck().goto).toHaveBeenLastCalledWith({ slide: 4, click: 0 });
		await drawn({ slide: 4, click: 0 }, 0);
		expect(button('다음').getAttribute('aria-disabled')).toBe('true');
		expect(screen.queryByText(/보여 주지 않은/)).toBeNull();
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

	it('보던 곳이 묶음 밖이면(끝난 뒤 더 짧은 묶음으로 바꿈) 마지막 슬라이드에서 이어 본다', async () => {
		api.fetchClassLive.mockResolvedValue({ ...structuredClone(ENDED), current: { slide: 6, click: 2 } });
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
	it('슬라이드에 볼 수 있는 끝을 보내지 않는다', async () => {
		mount();
		await screen.findByTitle('다시 보는 슬라이드');
		expect(Object.keys(deck())).not.toContain('setLimit');
	});

	it('묶음의 마지막에서는 그냥 끝이다(안내 없음)', async () => {
		api.fetchClassLive.mockResolvedValue({ ...structuredClone(ENDED), current: { slide: 4, click: 0 } });
		mount({ start: 'last' });
		await screen.findByTitle('다시 보는 슬라이드');
		await drawn({ slide: 4, click: 0 }, 0);
		expect(button('다음').getAttribute('aria-disabled')).toBe('true');
		expect(screen.queryByText(/보여 주지 않은/)).toBeNull();
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

describe('보는 동안 교수가 묶음을 바꾸거나 공개 여부를 바꾸면 (AC41, T037)', () => {
	const privateEnded = () => ({ ...structuredClone(ENDED), deck: { ...ENDED.deck!, public: false } });

	it('다시 받으라는 신호(refresh)가 오면 상태를 다시 받고, 공개되면 슬라이드가 나타난다', async () => {
		api.fetchClassLive.mockResolvedValueOnce(privateEnded());
		const view = render(ReplayView, { classroomId: 7, sessionId: 4, onBack: vi.fn(), refresh: 0 });
		expect(await screen.findByText('이 회차의 슬라이드는 공개되지 않았습니다.')).toBeTruthy();
		api.fetchClassLive.mockResolvedValueOnce(structuredClone(ENDED));
		await view.rerender({ classroomId: 7, sessionId: 4, onBack: vi.fn(), refresh: 1 });
		expect(await screen.findByTitle('다시 보는 슬라이드')).toBeTruthy();
		expect(api.fetchClassLive).toHaveBeenCalledTimes(2);
		expect(deck().goto).toHaveBeenLastCalledWith({ slide: 1, click: 0 }); // 처음부터
	});

	it('비공개로 바뀌면 슬라이드를 내리고 안내와 자료를 보인다', async () => {
		const view = render(ReplayView, { classroomId: 7, sessionId: 4, onBack: vi.fn(), refresh: 0 });
		await screen.findByTitle('다시 보는 슬라이드');
		api.fetchClassLive.mockResolvedValueOnce(privateEnded());
		await view.rerender({ classroomId: 7, sessionId: 4, onBack: vi.fn(), refresh: 1 });
		expect(await screen.findByText('이 회차의 슬라이드는 공개되지 않았습니다.')).toBeTruthy();
		expect(screen.queryByTitle('다시 보는 슬라이드')).toBeNull();
		expect(screen.getByRole('list', { name: '자료' })).toBeTruthy();
	});

	it('같은 묶음이면 보던 곳을 지키고, 다른 묶음(더 짧은)으로 바뀌면 처음부터 본다', async () => {
		const view = render(ReplayView, { classroomId: 7, sessionId: 4, onBack: vi.fn(), start: 'last', refresh: 0 });
		await screen.findByTitle('다시 보는 슬라이드');
		await drawn({ slide: 2, click: 1 }, 1);
		await act(() => button('다음').click()); // (3, 0)
		api.fetchClassLive.mockResolvedValueOnce(structuredClone(ENDED));
		await view.rerender({ classroomId: 7, sessionId: 4, onBack: vi.fn(), start: 'last', refresh: 1 });
		await waitFor(() => expect(api.fetchClassLive).toHaveBeenCalledTimes(2));
		expect(deck().goto).toHaveBeenLastCalledWith({ slide: 3, click: 0 });
		api.fetchClassLive.mockResolvedValueOnce({ ...structuredClone(ENDED), deck: { id: 11, slide_count: 2, available: true, public: true } });
		await view.rerender({ classroomId: 7, sessionId: 4, onBack: vi.fn(), start: 'last', refresh: 2 });
		await waitFor(() => expect(decks.all.at(-1)!.goto).toHaveBeenLastCalledWith({ slide: 1, click: 0 }));
	});

	it('다시 받지 못하면 보던 화면을 그대로 둔다', async () => {
		const view = render(ReplayView, { classroomId: 7, sessionId: 4, onBack: vi.fn(), refresh: 0 });
		await screen.findByTitle('다시 보는 슬라이드');
		api.fetchClassLive.mockRejectedValueOnce(new TypeError('Failed to fetch'));
		await view.rerender({ classroomId: 7, sessionId: 4, onBack: vi.fn(), refresh: 1 });
		await act(() => Promise.resolve());
		expect(screen.getByTitle('다시 보는 슬라이드')).toBeTruthy();
		expect(screen.queryByRole('alert')).toBeNull();
	});

	it('늦게 온 예전 응답이 새 응답을 덮지 않는다', async () => {
		const view = render(ReplayView, { classroomId: 7, sessionId: 4, onBack: vi.fn(), refresh: 0 });
		await screen.findByTitle('다시 보는 슬라이드');
		let late: (s: LiveState) => void = () => {};
		api.fetchClassLive.mockReturnValueOnce(new Promise((r) => (late = r)));
		await view.rerender({ classroomId: 7, sessionId: 4, onBack: vi.fn(), refresh: 1 });
		api.fetchClassLive.mockResolvedValueOnce(privateEnded());
		await view.rerender({ classroomId: 7, sessionId: 4, onBack: vi.fn(), refresh: 2 });
		await screen.findByText('이 회차의 슬라이드는 공개되지 않았습니다.');
		await act(async () => late(structuredClone(ENDED)));
		expect(screen.getByText('이 회차의 슬라이드는 공개되지 않았습니다.')).toBeTruthy();
	});

	it('다시 받아도 초점을 옮기지 않는다', async () => {
		const view = render(ReplayView, { classroomId: 7, sessionId: 4, onBack: vi.fn(), refresh: 0, takeFocus: false });
		await screen.findByTitle('다시 보는 슬라이드');
		api.fetchClassLive.mockResolvedValueOnce(structuredClone(ENDED));
		await view.rerender({ classroomId: 7, sessionId: 4, onBack: vi.fn(), refresh: 1, takeFocus: true });
		await act(() => Promise.resolve());
		expect(document.activeElement).toBe(document.body);
	});
});

describe('다시 받기: 검증 뒤 추가', () => {
	const privateEnded = () => ({ ...structuredClone(ENDED), deck: { ...ENDED.deck!, public: false } });
	const pending = () => {
		let answer: (s: LiveState) => void = () => {};
		let fail: (e: unknown) => void = () => {};
		api.fetchClassLive.mockReturnValueOnce(new Promise<LiveState>((r, j) => ((answer = r), (fail = j))));
		return { answer: (s: LiveState) => answer(s), fail: (e: unknown) => fail(e) };
	};

	it('처음 응답보다 다시 받기가 먼저 오면 그것으로 처음처럼 정하고, 늦은 처음 응답은 버린다', async () => {
		const first = pending();
		const view = render(ReplayView, { classroomId: 7, sessionId: 4, onBack: vi.fn(), start: 'last', ended: true, refresh: 0, takeFocus: true });
		api.fetchClassLive.mockResolvedValueOnce({ ...structuredClone(ENDED), current: { slide: 3, click: 0 } });
		await view.rerender({ classroomId: 7, sessionId: 4, onBack: vi.fn(), start: 'last', ended: true, refresh: 1, takeFocus: true });
		const heading = await screen.findByRole('heading', { level: 1 });
		await screen.findByTitle('다시 보는 슬라이드');
		expect(deck().goto).toHaveBeenLastCalledWith({ slide: 3, click: 0 }); // 보던 곳(교수의 마지막 위치)에서
		await waitFor(() => expect(document.activeElement).toBe(heading)); // 처음 열 때처럼 초점
		await act(async () => first.answer(privateEnded()));
		expect(screen.getByTitle('다시 보는 슬라이드')).toBeTruthy(); // 늦게 온 처음 응답이 덮지 않는다
	});

	it('처음 응답 전에 다시 받기가 실패해도 불러오는 중에 머물지 않고 이유와 할 일을 보인다', async () => {
		const first = pending();
		const view = render(ReplayView, { classroomId: 7, sessionId: 4, onBack: vi.fn(), refresh: 0 });
		api.fetchClassLive.mockRejectedValueOnce(new TypeError('Failed to fetch'));
		await view.rerender({ classroomId: 7, sessionId: 4, onBack: vi.fn(), refresh: 1 });
		await act(async () => first.answer(structuredClone(ENDED))); // 버려진다
		const alert = await screen.findByRole('alert');
		expect(alert.textContent).toContain('회차를 불러오지 못했습니다.');
		expect(screen.queryByText('회차를 불러오는 중…')).toBeNull();
	});

	it('마지막 슬라이드의 단계에서 같은 묶음으로 다시 받으면 단계를 지킨다', async () => {
		api.fetchClassLive.mockResolvedValueOnce({ ...structuredClone(ENDED), current: { slide: 4, click: 1 } });
		const view = render(ReplayView, { classroomId: 7, sessionId: 4, onBack: vi.fn(), start: 'last', refresh: 0 });
		await screen.findByTitle('다시 보는 슬라이드');
		api.fetchClassLive.mockResolvedValueOnce({ ...structuredClone(ENDED), current: { slide: 4, click: 1 } });
		await view.rerender({ classroomId: 7, sessionId: 4, onBack: vi.fn(), start: 'last', refresh: 1 });
		await waitFor(() => expect(api.fetchClassLive).toHaveBeenCalledTimes(2));
		expect(deck().goto).toHaveBeenLastCalledWith({ slide: 4, click: 1 });
	});

	it('다른 묶음으로 바뀌면 처음부터 보고, 예전 묶음의 단계 수를 버린다', async () => {
		const view = render(ReplayView, { classroomId: 7, sessionId: 4, onBack: vi.fn(), start: 'last', refresh: 0 });
		await screen.findByTitle('다시 보는 슬라이드');
		await drawn({ slide: 2, click: 1 }, 1);
		await act(() => button('다음').click());
		await drawn({ slide: 3, click: 0 }, 0); // 2번 슬라이드의 단계 수(1)를 기억한다
		api.fetchClassLive.mockResolvedValueOnce({ ...structuredClone(ENDED), deck: { id: 12, slide_count: 4, available: true, public: true } });
		await view.rerender({ classroomId: 7, sessionId: 4, onBack: vi.fn(), start: 'last', refresh: 1 });
		const fresh = () => decks.all.at(-1)!;
		await waitFor(() => expect(fresh().goto).toHaveBeenLastCalledWith({ slide: 1, click: 0 }));
		await act(() => fresh().listener?.({ ready: true, total: 4, position: { slide: 1, click: 0 }, clicksTotal: 0 }));
		await act(() => button('다음').click());
		await act(() => fresh().listener?.({ ready: true, total: 4, position: { slide: 2, click: 0 }, clicksTotal: 0 }));
		await act(() => button('다음').click());
		await act(() => fresh().listener?.({ ready: true, total: 4, position: { slide: 3, click: 0 }, clicksTotal: 0 }));
		await act(() => button('이전').click());
		expect(fresh().goto).toHaveBeenLastCalledWith({ slide: 2, click: 0 }); // 새 묶음의 2번은 단계가 없다
	});

	it('공개·비공개가 바뀌면 알리고, 비공개로 바뀌어 초점을 잃으면 제목으로 옮긴다', async () => {
		const onAnnounce = vi.fn();
		const view = render(ReplayView, { classroomId: 7, sessionId: 4, onBack: vi.fn(), refresh: 0, onAnnounce });
		await screen.findByTitle('다시 보는 슬라이드');
		button('다음').focus();
		api.fetchClassLive.mockResolvedValueOnce(privateEnded());
		await view.rerender({ classroomId: 7, sessionId: 4, onBack: vi.fn(), refresh: 1, onAnnounce });
		await screen.findByText('이 회차의 슬라이드는 공개되지 않았습니다.');
		expect(onAnnounce).toHaveBeenLastCalledWith('이 회차의 슬라이드는 공개되지 않았습니다.');
		await waitFor(() => expect(document.activeElement?.tagName).toBe('H1'));
		api.fetchClassLive.mockResolvedValueOnce(structuredClone(ENDED));
		await view.rerender({ classroomId: 7, sessionId: 4, onBack: vi.fn(), refresh: 2, onAnnounce });
		await screen.findByTitle('다시 보는 슬라이드');
		expect(onAnnounce).toHaveBeenLastCalledWith('슬라이드가 공개되었습니다.');
	});

	it('공개 여부가 그대로면 알리지 않는다', async () => {
		const onAnnounce = vi.fn();
		const view = render(ReplayView, { classroomId: 7, sessionId: 4, onBack: vi.fn(), refresh: 0, onAnnounce });
		await screen.findByTitle('다시 보는 슬라이드');
		api.fetchClassLive.mockResolvedValueOnce(structuredClone(ENDED));
		await view.rerender({ classroomId: 7, sessionId: 4, onBack: vi.fn(), refresh: 1, onAnnounce });
		await waitFor(() => expect(api.fetchClassLive).toHaveBeenCalledTimes(2));
		expect(onAnnounce).not.toHaveBeenCalled();
	});
});

describe('미리 보기 (AC49)', () => {
	const SCHEDULED = () => ({ ...structuredClone(ENDED), session: { ...ENDED.session, status: 'scheduled' as const, title: '4주차 1회차' }, items: [] });

	it('제목·슬라이드 이름·돌아가기가 미리 보기에 맞고, 처음부터 끝까지 넘긴다', async () => {
		api.fetchClassLive.mockResolvedValue(SCHEDULED());
		render(ReplayView, { classroomId: 7, sessionId: 8, onBack: vi.fn(), preview: true });
		expect(await screen.findByRole('heading', { level: 1, name: '4주차 1회차 미리 보기' })).toBeTruthy();
		expect(screen.getByTitle('미리 보는 슬라이드')).toBeTruthy();
		expect(screen.getByRole('button', { name: '회차 목록으로' })).toBeTruthy();
		expect(deck().goto).toHaveBeenLastCalledWith({ slide: 1, click: 0 });
		expect(screen.queryByRole('heading', { level: 2, name: '자료' })).toBeNull(); // 수업 전이라 받은 자료가 없다
	});

	it('보는 동안 비공개가 되거나 묶음이 지워져 볼 수 없게 되면 이유와 할 일을 보이고 알린다', async () => {
		const onAnnounce = vi.fn();
		api.fetchClassLive.mockResolvedValueOnce(SCHEDULED());
		const view = render(ReplayView, { classroomId: 7, sessionId: 8, onBack: vi.fn(), preview: true, refresh: 0, onAnnounce });
		await screen.findByTitle('미리 보는 슬라이드');
		const { ApiError } = await import('#lib/api.js');
		api.fetchClassLive.mockRejectedValueOnce(new ApiError(404, '찾을 수 없는 회차입니다.'));
		await view.rerender({ classroomId: 7, sessionId: 8, onBack: vi.fn(), preview: true, refresh: 1, onAnnounce });
		const alert = await screen.findByRole('alert');
		expect(alert.textContent).toContain('이 회차는 이제 미리 볼 수 없습니다.');
		expect(alert.textContent).toContain('목록으로 돌아가 주세요.');
		expect(screen.queryByTitle('미리 보는 슬라이드')).toBeNull();
		expect(onAnnounce).not.toHaveBeenCalled(); // 경고(role=alert)가 읽는다. 알림 자리로 두 번 읽지 않는다
	});
});

describe('미리 보기: 검증 뒤 추가', () => {
	const SCHEDULED = () => ({ ...structuredClone(ENDED), session: { ...ENDED.session, status: 'scheduled' as const, title: '4주차 1회차' }, items: [] });
	const gone = async () => (await import('#lib/api.js')).ApiError;

	it('처음 열 때 이미 볼 수 없는 회차면(지워짐 등) 맞는 안내를 보인다', async () => {
		const ApiError = await gone();
		api.fetchClassLive.mockRejectedValueOnce(new ApiError(404, '찾을 수 없는 회차입니다.'));
		render(ReplayView, { classroomId: 7, sessionId: 8, onBack: vi.fn(), preview: true });
		const alert = await screen.findByRole('alert');
		expect(alert.textContent).toContain('이 회차는 이제 미리 볼 수 없습니다.');
		expect(alert.textContent).toContain('목록으로 돌아가 주세요.');
	});

	it('다시 보기(미리 보기가 아님)는 다시 받기가 404여도 보던 화면을 둔다', async () => {
		const ApiError = await gone();
		const view = render(ReplayView, { classroomId: 7, sessionId: 4, onBack: vi.fn(), refresh: 0 });
		await screen.findByTitle('다시 보는 슬라이드');
		api.fetchClassLive.mockRejectedValueOnce(new ApiError(404, '찾을 수 없는 회차입니다.'));
		await view.rerender({ classroomId: 7, sessionId: 4, onBack: vi.fn(), refresh: 1 });
		await act(() => Promise.resolve());
		expect(screen.getByTitle('다시 보는 슬라이드')).toBeTruthy();
		expect(screen.queryByText('이 회차는 이제 미리 볼 수 없습니다.')).toBeNull();
	});

	it('미리 보는 중 다시 받기가 404가 아닌 이유로 실패하면 보던 화면을 둔다', async () => {
		const ApiError = await gone();
		api.fetchClassLive.mockResolvedValueOnce(SCHEDULED());
		const view = render(ReplayView, { classroomId: 7, sessionId: 8, onBack: vi.fn(), preview: true, refresh: 0 });
		await screen.findByTitle('미리 보는 슬라이드');
		api.fetchClassLive.mockRejectedValueOnce(new ApiError(500, '서버 오류'));
		await view.rerender({ classroomId: 7, sessionId: 8, onBack: vi.fn(), preview: true, refresh: 1 });
		await act(() => Promise.resolve());
		expect(screen.getByTitle('미리 보는 슬라이드')).toBeTruthy();
		expect(screen.queryByRole('alert')).toBeNull();
	});

	it('볼 수 없게 되어 초점을 잃었으면 목록으로 버튼에, 다른 곳에 있었으면 그대로 둔다', async () => {
		const ApiError = await gone();
		api.fetchClassLive.mockResolvedValueOnce(SCHEDULED());
		const view = render(ReplayView, { classroomId: 7, sessionId: 8, onBack: vi.fn(), preview: true, refresh: 0 });
		await screen.findByTitle('미리 보는 슬라이드');
		button('다음').focus();
		api.fetchClassLive.mockRejectedValueOnce(new ApiError(404, 'x'));
		await view.rerender({ classroomId: 7, sessionId: 8, onBack: vi.fn(), preview: true, refresh: 1 });
		await screen.findByRole('alert');
		await waitFor(() => expect(document.activeElement).toBe(button('회차 목록으로')));
		cleanup();
		decks.all = [];
		const other = document.createElement('input');
		document.body.append(other);
		api.fetchClassLive.mockResolvedValueOnce(SCHEDULED());
		const again = render(ReplayView, { classroomId: 7, sessionId: 8, onBack: vi.fn(), preview: true, refresh: 0 });
		await screen.findByTitle('미리 보는 슬라이드');
		other.focus();
		api.fetchClassLive.mockRejectedValueOnce(new ApiError(404, 'x'));
		await again.rerender({ classroomId: 7, sessionId: 8, onBack: vi.fn(), preview: true, refresh: 1 });
		await screen.findByRole('alert');
		await act(() => Promise.resolve());
		expect(document.activeElement).toBe(other);
		other.remove();
	});

	it('볼 수 없게 된 뒤에는 다시 받아도 그 안내를 지킨다(목록으로 돌아가 다시 연다)', async () => {
		const ApiError = await gone();
		api.fetchClassLive.mockResolvedValueOnce(SCHEDULED());
		const view = render(ReplayView, { classroomId: 7, sessionId: 8, onBack: vi.fn(), preview: true, refresh: 0, takeFocus: true });
		await screen.findByTitle('미리 보는 슬라이드');
		api.fetchClassLive.mockRejectedValueOnce(new ApiError(404, 'x'));
		await view.rerender({ classroomId: 7, sessionId: 8, onBack: vi.fn(), preview: true, refresh: 1, takeFocus: true });
		await screen.findByRole('alert');
		api.fetchClassLive.mockResolvedValueOnce(SCHEDULED()); // 교수가 다시 공개했다
		await view.rerender({ classroomId: 7, sessionId: 8, onBack: vi.fn(), preview: true, refresh: 2, takeFocus: true });
		await act(() => Promise.resolve());
		expect(screen.getByText('이 회차는 이제 미리 볼 수 없습니다.')).toBeTruthy();
	});

	it('미리 보기의 묶음 파일이 없으면 자료 안내 없이 목록으로 돌아가라고 한다', async () => {
		api.fetchClassLive.mockResolvedValue({ ...SCHEDULED(), deck: { id: 8, slide_count: 4, available: false, public: true } });
		render(ReplayView, { classroomId: 7, sessionId: 8, onBack: vi.fn(), preview: true });
		expect(await screen.findByText('슬라이드를 열 수 없습니다. 목록으로 돌아가 주세요.')).toBeTruthy();
		expect(screen.queryByText(/자료는 계속/)).toBeNull();
	});
});
