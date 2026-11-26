// @vitest-environment jsdom
import { act, cleanup, render, screen, waitFor, within } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ClassSnapshot, LiveState } from '#lib/classLive.js';
import type { DeckSnapshot } from '#lib/deckBridge.js';

const live = vi.hoisted(() => ({ listener: null as ((s: unknown) => void) | null, stop: vi.fn(), options: null as unknown, id: 0 }));
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
			setMode: vi.fn(),
			reload: vi.fn(),
			stop: live.stop
		};
	}
}));
type FakeDeck = { listener: ((s: DeckSnapshot) => void) | null; goto: ReturnType<typeof vi.fn>; setMode: ReturnType<typeof vi.fn>; setLimit: ReturnType<typeof vi.fn>; stop: ReturnType<typeof vi.fn> };
const decks = vi.hoisted(() => ({ all: [] as FakeDeck[] }));
vi.mock('#lib/deckBridge.js', () => ({
	connectDeck: () => {
		const deck: FakeDeck = { listener: null, goto: vi.fn(), setMode: vi.fn(), setLimit: vi.fn(), stop: vi.fn() };
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
const api = vi.hoisted(() => ({ fetchClassSessions: vi.fn(), fetchDeckNotes: vi.fn() }));
vi.mock('#lib/api.js', async (original) => ({
	...(await original<object>()),
	fetchClassSessions: api.fetchClassSessions,
	fetchDeckNotes: api.fetchDeckNotes
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
	api.fetchClassSessions.mockReset();
	api.fetchClassSessions.mockResolvedValue({ items: PAST, live_session_id: null });
	api.fetchDeckNotes.mockReset();
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
