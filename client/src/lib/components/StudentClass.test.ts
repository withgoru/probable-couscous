// @vitest-environment jsdom
import { act, cleanup, render, screen, waitFor, within } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ClassSnapshot, LiveState } from '#lib/classLive.js';
import type { DeckSnapshot } from '#lib/deckBridge.js';

const live = vi.hoisted(() => ({ listener: null as ((s: unknown) => void) | null, stop: vi.fn(), setMode: vi.fn(), options: null as unknown, id: 0 }));
vi.mock('#lib/classLive.js', () => ({
	connectClass: (id: number, options: unknown) => {
		live.id = id;
		live.options = options;
		return {
			subscribe: (fn: (s: unknown) => void) => {
				live.listener = fn;
				return () => {};
			},
			goto: vi.fn(),
			setMode: live.setMode,
			reload: vi.fn(),
			stop: live.stop
		};
	}
}));
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
const api = vi.hoisted(() => ({ fetchClassSessions: vi.fn(), fetchDeckNotes: vi.fn(), fetchClassLive: vi.fn() }));
vi.mock('#lib/api.js', async (original) => ({
	...(await original<object>()),
	fetchClassSessions: api.fetchClassSessions,
	fetchDeckNotes: api.fetchDeckNotes,
	fetchClassLive: api.fetchClassLive
}));

import StudentClass from './StudentClass.svelte';

const STATE: LiveState = {
	session: { id: 5, title: '3주차 1회차', status: 'live', version: 3 },
	deck: { id: 9, slide_count: 4, available: true },
	current: { slide: 2, click: 1 },
	furthest: { slide: 3, click: 0 },
	limit: { slide: 3, click: 0 },
	items: [
		{ id: 1, body: '첫 자료', url: null, created_at: '2026-03-04T05:01:00+00:00' },
		{ id: 2, body: null, url: 'https://example.com/b', created_at: '2026-03-04T05:02:00+00:00' }
	]
};
const snapshot = (over: Partial<ClassSnapshot> = {}): ClassSnapshot => ({
	status: 'live',
	liveSessionId: 5,
	state: STATE,
	presence: null,
	goodbye: null,
	loadError: null,
	loaded: true,
	...over
});
const PAST = [
	{ id: 4, title: '2주차 2회차', status: 'ended', started_at: 'a', ended_at: '2026-02-26T06:00:00+00:00', deck: null },
	{ id: 3, title: '2주차 1회차', status: 'ended', started_at: 'a', ended_at: '2026-02-24T06:00:00+00:00', deck: null }
];

async function server(s: ClassSnapshot) {
	await act(() => live.listener?.(s));
}
function mount() {
	render(StudentClass, { classroomId: 7, title: '웹 프로그래밍 · 월수반', nickname: '느긋한 고래' });
}
const deck = () => decks.all[0];
const WAITING = '지금 진행 중인 수업이 없습니다. 수업이 시작되면 이 화면이 바뀝니다.';

beforeEach(() => {
	decks.all = [];
	live.listener = null;
	live.stop.mockReset();
	live.setMode.mockReset();
	api.fetchClassSessions.mockReset();
	api.fetchClassSessions.mockResolvedValue({ items: PAST, live_session_id: null });
	api.fetchDeckNotes.mockReset();
	api.fetchClassLive.mockReset();
	api.fetchClassLive.mockImplementation(async (_c: number, sid: number) => ({
		...STATE,
		session: { ...STATE.session, id: sid, title: sid === 5 ? '3주차 1회차' : '2주차 2회차', status: 'ended' }
	}));
});
afterEach(cleanup);

describe('수업이 없을 때 (AC23)', () => {
	it('입장했다는 것과 대기 문구, 지난 회차 목록이 보인다', async () => {
		mount();
		await server(snapshot({ state: null, liveSessionId: null }));
		expect(screen.getByText('입장했습니다')).toBeTruthy();
		expect(screen.getByRole('heading', { level: 1, name: '웹 프로그래밍 · 월수반' })).toBeTruthy();
		expect(screen.getByText('느긋한 고래')).toBeTruthy();
		expect(screen.getByText(WAITING)).toBeTruthy();
		const list = await screen.findByRole('list', { name: '지난 회차' });
		expect(within(list).getAllByRole('listitem').map((li) => li.textContent?.trim().replace(/\s+/g, ' '))).toEqual([
			expect.stringContaining('2주차 2회차'),
			expect.stringContaining('2주차 1회차')
		]);
		expect(api.fetchClassSessions).toHaveBeenCalledWith(7);
	});

	it('지난 회차가 없으면 그렇게 알린다', async () => {
		api.fetchClassSessions.mockResolvedValue({ items: [], live_session_id: null });
		mount();
		await server(snapshot({ state: null, liveSessionId: null }));
		expect(await screen.findByText('아직 끝난 회차가 없습니다.')).toBeTruthy();
	});

	it('수업이 시작되면 새로 고치지 않고 수업 화면으로 바뀌고 화면 낭독기에도 알린다', async () => {
		mount();
		await server(snapshot({ state: null, liveSessionId: null }));
		const status = document.querySelector('[data-class-status]') as HTMLElement;
		expect(status.getAttribute('role')).toBe('status');
		await server(snapshot());
		expect(screen.queryByText(WAITING)).toBeNull();
		expect(screen.getByTitle('수업 슬라이드')).toBeTruthy();
		expect(document.querySelector('[data-class-status]')).toBe(status); // 같은 알림 자리
		expect(status.textContent).toContain('수업이 시작되었습니다.');
	});

	it('진행 중이 아닌 회차 상태(끝남)를 받으면 대기 화면이다', async () => {
		mount();
		await server(snapshot({ state: { ...STATE, session: { ...STATE.session, status: 'ended' } }, liveSessionId: null }));
		expect(screen.getByText(WAITING)).toBeTruthy();
		expect(screen.queryByTitle('수업 슬라이드')).toBeNull();
	});

	it('지난 회차에는 끝난 회차만 보인다', async () => {
		api.fetchClassSessions.mockResolvedValue({
			items: [{ id: 6, title: '진행 중인 회차', status: 'live', started_at: 'a', ended_at: null, deck: null }, ...PAST],
			live_session_id: 6
		});
		mount();
		await server(snapshot({ state: null, liveSessionId: null }));
		const list = await screen.findByRole('list', { name: '지난 회차' });
		expect(list.textContent).not.toContain('진행 중인 회차');
	});

	it('지난 회차를 불러오지 못하면 없다고 하지 않고 그렇게 알린다', async () => {
		api.fetchClassSessions.mockRejectedValue(new Error('500'));
		mount();
		await server(snapshot({ state: null, liveSessionId: null }));
		expect(await screen.findByText('지난 회차를 불러오지 못했습니다. 잠시 뒤 다시 열어 주세요.')).toBeTruthy();
		expect(screen.queryByText('아직 끝난 회차가 없습니다.')).toBeNull();
	});

	it('늦게 온 예전 목록이 새 목록을 덮지 않는다', async () => {
		let oldAnswer: (v: unknown) => void = () => {};
		api.fetchClassSessions
			.mockReturnValueOnce(new Promise((r) => (oldAnswer = r)))
			.mockResolvedValueOnce({ items: PAST, live_session_id: null });
		mount();
		await server(snapshot({ state: null, liveSessionId: null }));
		await server(snapshot());
		await server(snapshot({ state: null, liveSessionId: null }));
		await act(async () => (await screen.findByRole('button', { name: '지난 회차 목록으로' })).click()); // 끝난 회차 다시 보기에서 나온다
		await screen.findByText('2주차 2회차');
		await act(() => oldAnswer({ items: [], live_session_id: null }));
		expect(screen.getByText('2주차 2회차')).toBeTruthy();
	});

	it('불러오는 동안과 불러오기 실패를 알린다', async () => {
		mount();
		await server(snapshot({ state: null, liveSessionId: null, loaded: false, status: 'connecting' }));
		expect(screen.getByText('수업을 불러오는 중…')).toBeTruthy();
		await server(snapshot({ state: null, liveSessionId: null, loaded: false, loadError: '불러오지 못했습니다 (500)' }));
		const alert = screen.getByRole('alert');
		expect(alert.textContent).toContain('불러오지 못했습니다 (500)');
		expect(alert.textContent).toContain('잠시 뒤 자동으로 다시 불러옵니다.');
	});
});

describe('수업 화면 (AC24, AC25, AC29, AC30)', () => {
	it('학생으로 이 강좌의 수업에 연결한다', async () => {
		mount();
		expect(live.id).toBe(7);
		expect(live.options).toMatchObject({ role: 'student' });
	});

	it('슬라이드, 수업 정보 줄(강좌·회차, 닉네임), 따라가기 줄, 자료 순서다', async () => {
		mount();
		await server(snapshot());
		const slide = screen.getByTitle('수업 슬라이드');
		const info = screen.getByRole('heading', { level: 1, name: '웹 프로그래밍 · 월수반' });
		const sessionTitle = screen.getByText('3주차 1회차');
		const nickname = screen.getByText('느긋한 고래');
		const follow = screen.getByText('교수 화면 따라가는 중');
		const materials = screen.getByRole('heading', { level: 2, name: '자료' });
		const order = [slide, info, sessionTitle, nickname, follow, materials];
		for (let i = 0; i < order.length - 1; i += 1) {
			expect(order[i].compareDocumentPosition(order[i + 1]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
		}
		expect((slide.parentElement as HTMLElement).className).toContain('aspect-video');
	});

	it('처음에는 교수 화면을 따라가는 중이고 교수 위치에서 시작한다(수업 중에 들어와도)', async () => {
		mount();
		await server(snapshot());
		expect(deck().setMode).toHaveBeenCalledWith('follow');
		expect(deck().goto).toHaveBeenLastCalledWith({ slide: 2, click: 1 });
		expect(deck().setLimit).toHaveBeenLastCalledWith({ slide: 3, click: 0 });
	});

	it('교수가 넘기면 같은 위치로 따라간다', async () => {
		mount();
		await server(snapshot());
		await server(snapshot({ state: { ...STATE, current: { slide: 3, click: 0 }, furthest: { slide: 3, click: 0 } } }));
		expect(deck().goto).toHaveBeenLastCalledWith({ slide: 3, click: 0 });
		expect(decks.all).toHaveLength(1);
	});

	it('교수가 새 슬라이드로 넘기면 볼 수 있는 끝을 먼저 넓히고 그다음 옮긴다(애드온이 범위로 막지 않게)', async () => {
		mount();
		await server(snapshot({ state: { ...STATE, current: { slide: 1, click: 0 }, furthest: { slide: 1, click: 0 }, limit: { slide: 1, click: 0 } } }));
		await server(snapshot({ state: { ...STATE, current: { slide: 2, click: 0 }, furthest: { slide: 2, click: 0 }, limit: { slide: 2, click: 0 } } }));
		const limitAt = deck().setLimit.mock.invocationCallOrder.at(-1)!;
		const gotoAt = deck().goto.mock.invocationCallOrder.at(-1)!;
		expect(deck().setLimit).toHaveBeenLastCalledWith({ slide: 2, click: 0 });
		expect(deck().goto).toHaveBeenLastCalledWith({ slide: 2, click: 0 });
		expect(limitAt).toBeLessThan(gotoAt);
	});

	it('볼 수 있는 끝의 단계를 모르면(묶음을 바꿈) 그 슬라이드의 단계 전부까지다', async () => {
		mount();
		await server(snapshot({ state: { ...STATE, limit: { slide: 3, click: null } } }));
		const limit = deck().setLimit.mock.calls.at(-1)?.[0];
		expect(limit.slide).toBe(3);
		expect(limit.click).toBeGreaterThanOrEqual(999);
	});

	it('이번 회차에 이미 보낸 항목이 자료에 최근 것부터 보인다', async () => {
		mount();
		await server(snapshot());
		const list = screen.getByRole('list', { name: '자료' });
		const rows = within(list).getAllByRole('listitem');
		expect(rows[0].textContent).toContain('https://example.com/b');
		expect(rows[1].textContent).toContain('첫 자료');
	});

	it('다른 회차의 수업이 시작되면 그 회차의 자료를 새로 받은 것으로 세지 않는다', async () => {
		mount();
		await server(snapshot());
		await server(snapshot({ state: { ...STATE, session: { ...STATE.session, id: 6 }, items: [{ id: 9, body: '6회차 자료', url: null, created_at: '2026-03-11T05:00:00+00:00' }] } }));
		expect(screen.getByText('6회차 자료')).toBeTruthy();
		expect((document.querySelector('[data-arrival]') as HTMLElement).textContent?.trim()).toBe('');
	});

	it('자료가 없으면 그렇게 알린다', async () => {
		mount();
		await server(snapshot({ state: { ...STATE, items: [] } }));
		expect(screen.getByText('아직 받은 자료가 없습니다.')).toBeTruthy();
	});

	it('발표자 노트는 화면 어디에도 없다(슬라이드 안은 E2E가 본다)', async () => {
		mount();
		await server(snapshot());
		expect(screen.queryByText(/노트/)).toBeNull();
	});

	it('자료 링크는 새 탭으로 안전하게 연다', async () => {
		mount();
		await server(snapshot());
		const link = within(screen.getByRole('list', { name: '자료' })).getByRole('link');
		expect(link.getAttribute('target')).toBe('_blank');
		expect(link.getAttribute('rel')).toContain('noopener');
	});

	it('내 닉네임은 무엇인지 글로 보인다', async () => {
		mount();
		await server(snapshot());
		expect(screen.getByText('내 닉네임').parentElement?.textContent).toContain('느긋한 고래');
	});

	it('슬라이드는 화면 폭 전체를 쓴다(옆 여백을 넘어선다)', async () => {
		mount();
		await server(snapshot());
		expect((screen.getByTitle('수업 슬라이드').parentElement as HTMLElement).className).toContain('-mx-6');
	});

	it('다른 상태(자료가 오는 등)가 바뀌어도 위치가 같으면 슬라이드에 다시 보내지 않는다', async () => {
		mount();
		await server(snapshot());
		const sent = deck().goto.mock.calls.length;
		await server(snapshot({ state: { ...STATE, items: [...STATE.items, { id: 3, body: '새 자료', url: null, created_at: '2026-03-04T05:03:00+00:00' }] } }));
		expect(deck().goto.mock.calls.length).toBe(sent);
		expect(deck().setLimit.mock.calls.length).toBe(1);
	});

	it('슬라이드가 없는 수업은 그렇게 알리고 자료는 그대로 보인다', async () => {
		mount();
		await server(snapshot({ state: { ...STATE, deck: null } }));
		expect(screen.getByText('이번 수업은 슬라이드 없이 진행합니다. 자료를 확인하세요.')).toBeTruthy();
		expect(screen.queryByTitle('수업 슬라이드')).toBeNull();
		expect(screen.getByRole('list', { name: '자료' })).toBeTruthy();
	});

	it('슬라이드를 열 수 없으면 그렇게 알린다', async () => {
		mount();
		await server(snapshot({ state: { ...STATE, deck: { id: 9, slide_count: 4, available: false } } }));
		expect(screen.getByText('슬라이드를 열 수 없습니다. 자료는 계속 볼 수 있습니다.')).toBeTruthy();
	});

	it('화면을 떠나면 연결을 닫는다', async () => {
		mount();
		cleanup();
		expect(live.stop).toHaveBeenCalled();
	});
});

describe('지난 회차 목록을 다시 받는 때', () => {
	it('수업이 끝나 대기로 돌아오면 목록을 다시 받는다', async () => {
		mount();
		await server(snapshot());
		await server(snapshot({ state: null, liveSessionId: null }));
		await waitFor(() => expect(api.fetchClassSessions).toHaveBeenCalledTimes(1));
		await server(snapshot());
		await server(snapshot({ state: null, liveSessionId: null }));
		await waitFor(() => expect(api.fetchClassSessions).toHaveBeenCalledTimes(2));
	});
});

// --- T024: 넘기면 따라가기 풀기와 다시 따라가기(AC26~AC28) ------------------------------------------

/** 수업 화면을 열고 슬라이드가 그 위치를 그렸다고 알린다(단계 수 3개인 2번 슬라이드). */
async function classAt(over: Partial<LiveState> = {}, clicksTotal = 3) {
	mount();
	const state = { ...STATE, ...over };
	await server(snapshot({ state }));
	await drawn(state.current, clicksTotal);
	return state;
}
async function drawn(position: { slide: number; click: number }, clicksTotal: number) {
	await act(() => deck().listener?.({ ready: true, total: 4, position: { ...position }, clicksTotal }));
}
const button = (name: string) => screen.getByRole('button', { name }) as HTMLButtonElement;
const FOLLOWING = '교수 화면 따라가는 중';

describe('넘기면 따라가기가 풀린다 (AC26)', () => {
	it('따라가는 중에 다음을 누르면 풀리고 한 단계 움직인다', async () => {
		await classAt();
		expect(screen.getByText(FOLLOWING)).toBeTruthy();
		await act(() => button('다음').click());
		expect(deck().goto).toHaveBeenLastCalledWith({ slide: 2, click: 2 });
		expect(screen.queryByText(FOLLOWING)).toBeNull();
		expect(screen.getByText('직접 넘겨 보는 중 · 교수 화면은 2번 슬라이드입니다.')).toBeTruthy();
		expect(button('교수 화면으로')).toBeTruthy();
		expect(deck().setMode).toHaveBeenLastCalledWith('browse');
		expect(live.setMode).toHaveBeenLastCalledWith('browse'); // 서버 현황(AC15)
	});

	it('이전을 눌러도 풀리고 앞 단계로 간다', async () => {
		await classAt();
		await act(() => button('이전').click());
		expect(deck().goto).toHaveBeenLastCalledWith({ slide: 2, click: 0 });
		expect(screen.getByText(/직접 넘겨 보는 중/)).toBeTruthy();
	});

	it('슬라이드를 밀거나 ←·→를 눌러 넘기려 하면(deck:intent) 같다', async () => {
		await classAt();
		await act(() => deck().onIntent?.('prev'));
		expect(deck().goto).toHaveBeenLastCalledWith({ slide: 2, click: 0 });
		expect(screen.getByText(/직접 넘겨 보는 중/)).toBeTruthy();
	});

	it('화면의 ←·→ 키도 같다(글 입력 칸에서는 아니다)', async () => {
		await classAt();
		const input = document.createElement('input');
		document.body.append(input);
		await act(() => input.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true })));
		expect(screen.getByText(FOLLOWING)).toBeTruthy();
		await act(() => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight' })));
		expect(deck().goto).toHaveBeenLastCalledWith({ slide: 2, click: 2 });
		expect(screen.getByText(/직접 넘겨 보는 중/)).toBeTruthy();
		input.remove();
	});

	it('풀린 뒤에는 교수가 넘겨도 학생 슬라이드는 그대로이고 교수 위치 번호만 바뀐다', async () => {
		await classAt();
		await act(() => button('다음').click());
		const calls = deck().goto.mock.calls.length;
		await server(snapshot({ state: { ...STATE, current: { slide: 3, click: 0 }, furthest: { slide: 3, click: 0 }, limit: { slide: 3, click: 0 } } }));
		expect(deck().goto.mock.calls.slice(calls).every((c) => c[0].slide === 2 && c[0].click === 2)).toBe(true);
		expect(screen.getByText('직접 넘겨 보는 중 · 교수 화면은 3번 슬라이드입니다.')).toBeTruthy();
		expect(deck().setLimit).toHaveBeenLastCalledWith({ slide: 3, click: 0 }); // 볼 수 있는 끝은 넓어진다
	});

	it('범위 밖으로 넘기려 하면 움직이지 않고 따라가기도 그대로다', async () => {
		await classAt({ current: { slide: 3, click: 0 }, furthest: { slide: 3, click: 0 }, limit: { slide: 3, click: 0 } }, 0);
		const calls = deck().goto.mock.calls.length;
		await act(() => deck().onIntent?.('next'));
		await act(() => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight' })));
		expect(deck().goto.mock.calls.length).toBe(calls);
		expect(screen.getByText(FOLLOWING)).toBeTruthy();
		expect(live.setMode).not.toHaveBeenCalled();
	});

	it('←도 같고, 다른 요소가 이미 처리한 키는 넘기지 않는다', async () => {
		await classAt();
		const handled = new KeyboardEvent('keydown', { key: 'ArrowRight', cancelable: true });
		handled.preventDefault();
		await act(() => window.dispatchEvent(handled));
		expect(screen.getByText(FOLLOWING)).toBeTruthy();
		await act(() => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft' })));
		expect(deck().goto).toHaveBeenLastCalledWith({ slide: 2, click: 0 });
		expect(screen.getByText(/직접 넘겨 보는 중/)).toBeTruthy();
	});

	it('슬라이드가 아직 그리지 않았거나 열 수 없으면 넘기려 해도 아무 일도 없다', async () => {
		await classAt();
		// 교수가 (2,0)으로 돌아갔고 슬라이드는 아직 (2,1)이다: 단계 수를 모른 채 넘기면 단계를 건너뛴다
		await server(snapshot({ state: { ...STATE, current: { slide: 2, click: 0 } } }));
		await act(() => button('다음').click());
		await act(() => deck().onIntent?.('next'));
		expect(screen.getByText(FOLLOWING)).toBeTruthy();
		cleanup();
		decks.all = [];
		mount();
		await server(snapshot({ state: { ...STATE, deck: { id: 9, slide_count: 4, available: false } } }));
		await act(() => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft' })));
		expect(screen.getByText(FOLLOWING)).toBeTruthy();
		expect(live.setMode).not.toHaveBeenCalled();
	});

	it('직접 넘겨 보던 곳이 볼 수 있는 끝 밖이 되면 끝으로 당겨져 계속 넘길 수 있다', async () => {
		await classAt({ current: { slide: 2, click: 1 }, furthest: { slide: 2, click: 1 }, limit: { slide: 2, click: null } });
		await act(() => button('다음').click()); // (2,2)
		await drawn({ slide: 2, click: 2 }, 3);
		// 교수가 넘겨 끝이 가장 멀리 간 위치(2,1)로 바뀌었다
		await server(snapshot({ state: { ...STATE, current: { slide: 2, click: 1 }, furthest: { slide: 2, click: 1 }, limit: { slide: 2, click: 1 } } }));
		expect(deck().goto).toHaveBeenLastCalledWith({ slide: 2, click: 1 });
		await drawn({ slide: 2, click: 1 }, 3);
		expect(button('이전').getAttribute('aria-disabled')).toBe('false');
	});

	it('묶음이 바뀌면 예전 묶음의 단계 수를 버린다', async () => {
		await classAt(); // 2번(단계 3개)
		await server(snapshot({ state: { ...STATE, deck: { id: 10, slide_count: 4, available: true }, current: { slide: 3, click: 0 }, furthest: { slide: 3, click: 0 }, limit: { slide: 3, click: 0 } } }));
		await act(() => decks.all[1].listener?.({ ready: true, total: 4, position: { slide: 3, click: 0 }, clicksTotal: 0 }));
		await act(() => button('이전').click());
		expect(decks.all[1].goto).toHaveBeenLastCalledWith({ slide: 2, click: 0 });
	});

	it('자료로 옮기거나 스크롤해도 따라가기는 그대로다(그런 동작에는 넘기기가 걸려 있지 않다)', async () => {
		await classAt();
		window.dispatchEvent(new Event('scroll'));
		expect(screen.getByText(FOLLOWING)).toBeTruthy();
	});

	it('슬라이드가 따라오는 중에는 단계를 건너뛰지 않게 넘기지 않는다', async () => {
		await classAt();
		await server(snapshot({ state: { ...STATE, current: { slide: 3, click: 0 }, furthest: { slide: 3, click: 0 }, limit: { slide: 3, click: 0 } } }));
		expect(button('다음').getAttribute('aria-disabled')).toBe('true');
		await act(() => button('다음').click());
		expect(screen.getByText(FOLLOWING)).toBeTruthy();
	});
});

describe('가장 멀리 간 위치까지만 (AC27)', () => {
	it('끝에 이르면 다음이 흐려지고 안내 문구가 다음과 이어진다', async () => {
		await classAt({ current: { slide: 3, click: 0 }, furthest: { slide: 3, click: 0 }, limit: { slide: 3, click: 0 } }, 0);
		const reason = screen.getByText('교수님이 아직 보여 주지 않은 슬라이드입니다.');
		expect(button('다음').getAttribute('aria-disabled')).toBe('true'); // 초점을 잃지 않게 흐리게만 한다
		expect(button('다음').disabled).toBe(false);
		expect(button('다음').getAttribute('aria-describedby')).toContain(reason.id);
		const calls = deck().goto.mock.calls.length;
		await act(() => button('다음').click());
		expect(deck().goto.mock.calls.length).toBe(calls);
	});

	it('직접 넘기다 끝에 닿아도 그렇다', async () => {
		await classAt({ current: { slide: 2, click: 3 }, furthest: { slide: 3, click: 0 }, limit: { slide: 3, click: 0 } });
		await act(() => button('다음').click());
		expect(deck().goto).toHaveBeenLastCalledWith({ slide: 3, click: 0 });
		await drawn({ slide: 3, click: 0 }, 2);
		expect(button('다음').getAttribute('aria-disabled')).toBe('true');
		expect(screen.getByText('교수님이 아직 보여 주지 않은 슬라이드입니다.')).toBeTruthy();
	});

	it('묶음의 마지막이면 다음이 흐려지지만 "아직 보여 주지 않은"이라고는 하지 않는다', async () => {
		await classAt({ current: { slide: 4, click: 1 }, furthest: { slide: 4, click: 1 }, limit: { slide: 4, click: 1 } }, 1);
		expect(button('다음').getAttribute('aria-disabled')).toBe('true');
		expect(screen.queryByText('교수님이 아직 보여 주지 않은 슬라이드입니다.')).toBeNull();
	});

	it('처음이면 이전이 흐려진다', async () => {
		await classAt({ current: { slide: 1, click: 0 }, furthest: { slide: 3, click: 0 }, limit: { slide: 3, click: 0 } }, 0);
		expect(button('이전').getAttribute('aria-disabled')).toBe('true');
	});

	it('끝의 단계를 모르면(묶음을 바꿈) 그 슬라이드의 단계는 모두 넘길 수 있다', async () => {
		await classAt({ current: { slide: 2, click: 1 }, furthest: { slide: 2, click: 1 }, limit: { slide: 2, click: null } });
		await act(() => button('다음').click()); // 가장 멀리 간 단계(1)를 넘어 2로
		expect(deck().goto).toHaveBeenLastCalledWith({ slide: 2, click: 2 });
		await drawn({ slide: 2, click: 2 }, 3);
		await act(() => button('다음').click());
		await drawn({ slide: 2, click: 3 }, 3);
		expect(button('다음').getAttribute('aria-disabled')).toBe('true'); // 3번 슬라이드는 끝 밖
	});
});

describe('교수 화면으로 다시 따라간다 (AC28)', () => {
	it('누르면 교수의 현재 위치로 가고 다시 따라가는 중이 된다', async () => {
		await classAt();
		await act(() => button('이전').click());
		await server(snapshot({ state: { ...STATE, current: { slide: 3, click: 0 }, furthest: { slide: 3, click: 0 }, limit: { slide: 3, click: 0 } } }));
		await act(() => button('교수 화면으로').click());
		expect(deck().goto).toHaveBeenLastCalledWith({ slide: 3, click: 0 });
		expect(screen.getByText(FOLLOWING)).toBeTruthy();
		expect(screen.queryByRole('button', { name: '교수 화면으로' })).toBeNull();
		expect(deck().setMode).toHaveBeenLastCalledWith('follow');
		expect(live.setMode).toHaveBeenLastCalledWith('follow');
		// 다시 따라가므로 교수가 넘기면 따라간다
		await server(snapshot({ state: { ...STATE, current: { slide: 4, click: 0 }, furthest: { slide: 4, click: 0 }, limit: { slide: 4, click: 0 } } }));
		expect(deck().goto).toHaveBeenLastCalledWith({ slide: 4, click: 0 });
	});

	it('교수 화면으로를 누르면 초점이 넘기기 버튼으로 옮겨 간다(사라진 버튼에 남지 않게)', async () => {
		await classAt();
		await act(() => button('이전').click());
		await drawn({ slide: 2, click: 0 }, 3);
		button('교수 화면으로').focus();
		await act(() => button('교수 화면으로').click());
		await waitFor(() => expect(document.activeElement).toBe(button('다음')));
	});

	it('직접 넘기다 교수와 같은 위치에 닿아도 저절로 다시 따라가지 않는다', async () => {
		await classAt();
		await act(() => button('이전').click()); // (2,0)
		await drawn({ slide: 2, click: 0 }, 3);
		await act(() => button('다음').click()); // (2,1) = 교수 위치
		await drawn({ slide: 2, click: 1 }, 3);
		expect(screen.getByText(/직접 넘겨 보는 중/)).toBeTruthy();
		expect(button('교수 화면으로')).toBeTruthy();
	});

	it('다른 회차의 수업이 시작되면 다시 따라가는 중에서 시작한다', async () => {
		await classAt();
		await act(() => button('다음').click());
		await server(snapshot({ state: { ...STATE, session: { ...STATE.session, id: 6 }, current: { slide: 1, click: 0 } } }));
		expect(screen.getByText(FOLLOWING)).toBeTruthy();
		expect(deck().goto).toHaveBeenLastCalledWith({ slide: 1, click: 0 });
		expect(live.setMode).toHaveBeenLastCalledWith('follow');
		expect(deck().setMode).toHaveBeenLastCalledWith('follow');
	});

	it('새 회차에서는 예전 회차에서 본 단계 수로 돌아가지 않는다', async () => {
		await classAt(); // 2번 슬라이드(단계 3개)를 그렸다
		await server(snapshot({ state: { ...STATE, session: { ...STATE.session, id: 6 }, current: { slide: 3, click: 0 }, furthest: { slide: 3, click: 0 }, limit: { slide: 3, click: 0 } } }));
		await drawn({ slide: 3, click: 0 }, 0);
		await act(() => button('이전').click());
		expect(deck().goto).toHaveBeenLastCalledWith({ slide: 2, click: 0 });
	});

	it('따라가기 줄은 바뀔 때 화면 낭독기에도 읽힌다', async () => {
		await classAt();
		const line = screen.getByText(FOLLOWING).closest('[role="status"]') as HTMLElement;
		expect(line).toBeTruthy();
		await act(() => button('다음').click());
		expect(line.textContent).toContain('직접 넘겨 보는 중');
	});
});

// --- T026: 수업 끝남과 지난 회차 다시 보기(AC38, AC39) --------------------------------------------

describe('수업이 끝나면 (AC38)', () => {
	it('새로 고치지 않고 "수업이 끝났습니다."와 같은 회차의 다시 보기로 바뀐다', async () => {
		mount();
		await server(snapshot());
		await server(snapshot({ state: null, liveSessionId: null })); // 교수가 끝냈다
		expect(await screen.findByText('수업이 끝났습니다.', { selector: ':not([data-class-status])' })).toBeTruthy();
		expect(await screen.findByRole('heading', { level: 1, name: '3주차 1회차 다시 보기' })).toBeTruthy();
		expect(api.fetchClassLive).toHaveBeenCalledWith(7, 5);
		expect(screen.queryByText(WAITING)).toBeNull();
	});

	it('다시 보기에서 목록으로 가면 대기 화면과 지난 회차가 보인다', async () => {
		mount();
		await server(snapshot());
		await server(snapshot({ state: null, liveSessionId: null }));
		await act(async () => (await screen.findByRole('button', { name: '지난 회차 목록으로' })).click());
		expect(screen.getByText(WAITING)).toBeTruthy();
	});

	it('다시 보는 중에 새 수업이 시작되면 수업 화면으로 간다', async () => {
		mount();
		await server(snapshot());
		await server(snapshot({ state: null, liveSessionId: null }));
		await screen.findByText('수업이 끝났습니다.', { selector: ':not([data-class-status])' });
		await server(snapshot({ state: { ...STATE, session: { ...STATE.session, id: 6, title: '3주차 2회차' } }, liveSessionId: 6 }));
		expect(screen.getByTitle('수업 슬라이드')).toBeTruthy();
		expect(screen.queryByText('수업이 끝났습니다.')).toBeNull();
	});
});

describe('지난 회차 (AC39)', () => {
	it('끝난 회차마다 다시 보기가 있고, 누르면 그 회차를 처음부터 다시 본다', async () => {
		mount();
		await server(snapshot({ state: null, liveSessionId: null }));
		const list = await screen.findByRole('list', { name: '지난 회차' });
		await act(() => within(list).getByRole('button', { name: '2주차 2회차 다시 보기' }).click());
		expect(await screen.findByRole('heading', { level: 1, name: '2주차 2회차 다시 보기' })).toBeTruthy();
		expect(api.fetchClassLive).toHaveBeenCalledWith(7, 4);
		expect(screen.queryByText('수업이 끝났습니다.')).toBeNull(); // 일부러 연 것이라 끝났다는 안내는 없다
	});
});

describe('다시 보기의 초점', () => {
	it('목록으로 돌아가면 대기 화면 제목으로 초점이 간다', async () => {
		mount();
		await server(snapshot());
		await server(snapshot({ state: null, liveSessionId: null }));
		await act(async () => (await screen.findByRole('button', { name: '지난 회차 목록으로' })).click());
		await waitFor(() => expect(document.activeElement?.tagName).toBe('H1'));
		expect(document.activeElement?.textContent).not.toContain('다시 보기');
	});
});

describe('끝남과 시작을 화면 낭독기에 알린다', () => {
	const status = () => document.querySelector('[data-class-status]') as HTMLElement;
	it('끝나면 늘 있는 알림 자리가 알리고, 다음 수업이 시작되면 다시 알린다', async () => {
		mount();
		await server(snapshot({ state: null, liveSessionId: null }));
		await server(snapshot());
		expect(status().textContent).toBe('수업이 시작되었습니다.');
		await server(snapshot({ state: null, liveSessionId: null }));
		expect(status().textContent).toBe('수업이 끝났습니다.');
		await server(snapshot({ state: { ...STATE, session: { ...STATE.session, id: 6 } }, liveSessionId: 6 }));
		expect(status().textContent).toBe('수업이 시작되었습니다.');
	});
});

describe('수업이 끝날 때의 초점', () => {
	it('초점이 수업 화면 안에 있었으면 다시 보기 제목으로 옮긴다', async () => {
		mount();
		await server(snapshot());
		screen.getByRole('button', { name: '다음' }).focus();
		await server(snapshot({ state: null, liveSessionId: null }));
		const heading = await screen.findByRole('heading', { level: 1, name: '3주차 1회차 다시 보기' });
		await waitFor(() => expect(document.activeElement).toBe(heading));
	});

	it('학생이 초점을 수업 화면 밖으로 옮긴 뒤에 끝나면 옮기지 않는다', async () => {
		mount();
		await server(snapshot());
		const next = screen.getByRole('button', { name: '다음' });
		next.focus();
		await act(() => next.blur());
		await server(snapshot({ state: null, liveSessionId: null }));
		await screen.findByRole('heading', { level: 1, name: '3주차 1회차 다시 보기' });
		await act(() => Promise.resolve());
		expect(document.activeElement).toBe(document.body);
	});

	it('수업 화면 밖에 있었으면 옮기지 않는다', async () => {
		mount();
		await server(snapshot());
		await server(snapshot({ state: null, liveSessionId: null }));
		await screen.findByRole('heading', { level: 1, name: '3주차 1회차 다시 보기' });
		await act(() => Promise.resolve());
		expect(document.activeElement).toBe(document.body);
	});
});

describe('다시 보기의 시작 위치', () => {
	const replayDeck = () => decks.all.at(-1)!;
	it('끝나서 이어 보면 교수의 마지막 위치에서, 목록에서 열면 처음부터다', async () => {
		mount();
		await server(snapshot());
		await server(snapshot({ state: null, liveSessionId: null }));
		await screen.findByTitle('다시 보는 슬라이드');
		expect(replayDeck().goto).toHaveBeenLastCalledWith({ slide: 2, click: 1 });
		await act(async () => (await screen.findByRole('button', { name: '지난 회차 목록으로' })).click());
		const list = await screen.findByRole('list', { name: '지난 회차' });
		await act(() => within(list).getByRole('button', { name: '2주차 2회차 다시 보기' }).click());
		await screen.findByTitle('다시 보는 슬라이드');
		expect(replayDeck().goto).toHaveBeenLastCalledWith({ slide: 1, click: 0 });
	});
});
