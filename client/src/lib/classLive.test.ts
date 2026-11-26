import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { classSocketUrl, connectClass, RETRY_DELAYS, type ClassSnapshot, type LiveState } from './classLive';

/** 브라우저 WebSocket을 흉내 낸다. 테스트가 서버 쪽 동작(메시지, 닫힘)을 직접 일으킨다. */
class FakeSocket {
	static all: FakeSocket[] = [];
	static readonly OPEN = 1;
	readyState = 1;
	onmessage: ((e: { data: string }) => void) | null = null;
	onclose: ((e: { code: number }) => void) | null = null;
	sent: unknown[] = [];
	constructor(public url: string) {
		FakeSocket.all.push(this);
	}
	send(data: string) {
		this.sent.push(JSON.parse(data));
	}
	close() {
		this.readyState = 3;
		this.onclose?.({ code: 1000 });
	}
	// 테스트용: 서버가 보낸 것처럼
	push(data: unknown) {
		this.onmessage?.({ data: JSON.stringify(data) });
	}
	drop(code = 1006) {
		this.readyState = 3;
		this.onclose?.({ code });
	}
}
const last = () => FakeSocket.all[FakeSocket.all.length - 1];

const LIVE: LiveState = {
	session: { id: 5, title: '1회차', status: 'live', version: 3 },
	deck: { id: 9, slide_count: 4, available: true, public: true },
	current: { slide: 2, click: 0 },
	limit: { slide: 4, click: null }, // 서버는 보내지 않는다. 이 모듈이 채운다(공개 묶음은 끝까지)
	items: [{ id: 1, body: '첫 자료', url: null, created_at: '2026-03-01T09:00:00+00:00' }]
};

type Server = { sessions: { live_session_id: number | null }; live: LiveState; fail?: number };

function fakeFetch(server: Server) {
	return vi.fn(async (url: string) => {
		if (server.fail) {
			server.fail -= 1;
			return new Response(JSON.stringify({ detail: '잠시 뒤 다시' }), { status: 503 });
		}
		if (url === '/api/class/7/sessions') return Response.json({ items: [], ...server.sessions });
		if (url.startsWith('/api/class/7/sessions/')) return Response.json(structuredClone(server.live));
		return new Response('{}', { status: 404 });
	});
}

class FakeDocument extends EventTarget {
	visibilityState: 'visible' | 'hidden' = 'visible';
	show() {
		this.visibilityState = 'visible';
		this.dispatchEvent(new Event('visibilitychange'));
	}
}

function setup(options: { role?: 'professor' | 'projector' | 'student'; sessionId?: number | null; server?: Partial<Server> } = {}) {
	const server: Server = { sessions: { live_session_id: 5 }, live: structuredClone(LIVE), ...options.server };
	const fetchFn = fakeFetch(server);
	const doc = new FakeDocument();
	const snapshots: ClassSnapshot[] = [];
	const live = connectClass(7, {
		role: options.role ?? 'student',
		sessionId: options.sessionId,
		fetchFn: fetchFn as unknown as typeof fetch,
		location: { protocol: 'http:', host: 'localhost:8000' },
		Socket: FakeSocket as unknown as typeof WebSocket,
		document: doc
	});
	const unsubscribe = live.subscribe((s) => snapshots.push(s));
	const now = () => snapshots[snapshots.length - 1];
	return { server, fetchFn, doc, live, now, snapshots, unsubscribe };
}

/** 연결이 열리고 `ready`를 받은 뒤 상태를 다 받을 때까지. */
async function ready(socket = last()) {
	socket.push({ type: 'ready', role: 'student' });
	await vi.runAllTimersAsync();
}

beforeEach(() => {
	FakeSocket.all = [];
	vi.useFakeTimers();
});
afterEach(() => vi.useRealTimers());

describe('주소', () => {
	it('같은 출처의 /ws/class/{강좌}로 연결하고 프로젝터는 role을 붙인다', () => {
		const where = { protocol: 'http:', host: 'localhost:8000' };
		expect(classSocketUrl(7, 'professor', where)).toBe('ws://localhost:8000/ws/class/7');
		expect(classSocketUrl(7, 'student', where)).toBe('ws://localhost:8000/ws/class/7');
		expect(classSocketUrl(7, 'projector', { protocol: 'https:', host: 'class.example.kr' })).toBe(
			'wss://class.example.kr/ws/class/7?role=projector'
		);
	});
});

describe('연결 → 구독 → 상태 통째로 받기 (C13)', () => {
	it('ready를 받은 뒤에 회차 목록과 진행 중 회차의 상태를 받는다', async () => {
		const { fetchFn, now } = setup();
		expect(now().status).toBe('connecting');
		expect(fetchFn).not.toHaveBeenCalled(); // 구독이 걸리기 전에는 불러오지 않는다
		await ready();
		expect(fetchFn.mock.calls.map((c) => c[0])).toEqual(['/api/class/7/sessions', '/api/class/7/sessions/5/live']);
		expect(now()).toMatchObject({ status: 'live', liveSessionId: 5, state: LIVE });
	});

	it('처음 불러오기를 마쳤는지 알린다(불러오는 중과 수업 없음을 가르려고)', async () => {
		const { now } = setup({ server: { sessions: { live_session_id: null }, fail: 1 } });
		expect(now().loaded).toBe(false);
		last().push({ type: 'ready', role: 'student' });
		await vi.advanceTimersByTimeAsync(0);
		expect(now()).toMatchObject({ status: 'live', loaded: false, loadError: '잠시 뒤 다시' });
		await vi.advanceTimersByTimeAsync(RETRY_DELAYS[0]);
		expect(now()).toMatchObject({ loaded: true, state: null, loadError: null });
	});

	it('정한 회차가 있으면(다시 보기) 그 회차를 받는다', async () => {
		const { fetchFn, now } = setup({ sessionId: 3 });
		await ready();
		expect(fetchFn.mock.calls.map((c) => c[0])).toContain('/api/class/7/sessions/3/live');
		expect(now().state?.session.id).toBe(5); // 가짜 서버는 같은 상태를 돌려준다
	});

	it('진행 중인 회차가 없으면 상태 없이 기다린다 (AC23)', async () => {
		const { fetchFn, now } = setup({ server: { sessions: { live_session_id: null } } });
		await ready();
		expect(fetchFn).toHaveBeenCalledTimes(1);
		expect(now()).toMatchObject({ status: 'live', liveSessionId: null, state: null });
	});

	it('불러오기에 실패하면 잠시 뒤 다시 불러온다', async () => {
		const { fetchFn, now } = setup({ server: { fail: 1 } });
		last().push({ type: 'ready', role: 'student' });
		await vi.advanceTimersByTimeAsync(0);
		expect(now().state).toBeNull();
		expect(now().loadError).toBe('잠시 뒤 다시');
		await vi.advanceTimersByTimeAsync(RETRY_DELAYS[0]);
		expect(fetchFn.mock.calls.length).toBe(3);
		expect(now().state).toEqual(LIVE);
		expect(now().loadError).toBeNull();
	});
});

describe('받은 version보다 큰 발행만 적용한다', () => {
	it('바로 다음 version의 위치를 적용한다 (AC25)', async () => {
		const { now } = setup();
		await ready();
		last().push({ type: 'position', session_id: 5, current: { slide: 3, click: 0 }, version: 4 });
		expect(now().state).toMatchObject({
			current: { slide: 3, click: 0 },
			limit: { slide: 4, click: null }, // 볼 수 있는 끝은 늘 묶음의 끝이다
			session: { version: 4 }
		});
	});

	it('서버가 보내지 않는 볼 수 있는 끝을 묶음의 끝으로 채운다(묶음이 없으면 첫 슬라이드)', async () => {
		const { limit: _, ...fromServer } = structuredClone(LIVE);
		const { now, live } = setup({ server: { live: fromServer as LiveState } });
		await ready();
		expect(now().state?.limit).toEqual({ slide: 4, click: null });
		live.stop();
		const { now: again } = setup({ server: { live: { ...(fromServer as LiveState), deck: null } } });
		await ready();
		expect(again().state?.limit).toEqual({ slide: 1, click: null });
	});

	it('비공개 묶음의 볼 수 있는 끝은 교수의 지금 위치이고, 교수가 넘기면 따라온다(T035까지의 임시 처리)', async () => {
		const { now } = setup({ server: { live: { ...structuredClone(LIVE), deck: { ...LIVE.deck!, public: false } } } });
		await ready();
		expect(now().state?.limit).toEqual({ slide: 2, click: 0 });
		last().push({ type: 'position', session_id: 5, current: { slide: 3, click: 1 }, version: 4 });
		expect(now().state?.limit).toEqual({ slide: 3, click: 1 });
	});

	it('공개·비공개가 바뀌면 묶음과 볼 수 있는 끝을 바꾸고 위치는 둔다 (AC48)', async () => {
		const { now } = setup();
		await ready();
		last().push({ type: 'deck.updated', session_id: 5, deck: { id: 9, slide_count: 4, available: true, public: false }, version: 4 });
		expect(now().state).toMatchObject({
			deck: { id: 9, public: false },
			current: { slide: 2, click: 0 },
			limit: { slide: 2, click: 0 },
			session: { version: 4 }
		});
		last().push({ type: 'deck.updated', session_id: 5, deck: { id: 9, slide_count: 4, available: true, public: true }, version: 5 });
		expect(now().state?.limit).toEqual({ slide: 4, click: null });
	});

	it('교수 화면도 공개·비공개 바뀜을 그대로 적용한다', async () => {
		const { now, fetchFn } = setup({ role: 'professor' });
		await ready();
		const calls = fetchFn.mock.calls.length;
		last().push({ type: 'deck.updated', session_id: 5, deck: { id: 9, slide_count: 4, available: true, public: true }, version: 4 });
		expect(now().state?.deck?.public).toBe(true);
		expect(fetchFn.mock.calls.length).toBe(calls);
	});

	it('형식이 맞지 않는 묶음 알림이면 통째로 다시 받는다', async () => {
		const { fetchFn } = setup();
		await ready();
		const calls = fetchFn.mock.calls.length;
		last().push({ type: 'deck.updated', session_id: 5, deck: { id: 9 }, version: 4 });
		await vi.runAllTimersAsync();
		expect(fetchFn.mock.calls.length).toBeGreaterThan(calls);
	});

	it('이미 받은 version이나 더 오래된 발행은 무시한다', async () => {
		const { now } = setup();
		await ready();
		last().push({ type: 'position', session_id: 5, current: { slide: 1, click: 0 }, version: 3 });
		last().push({ type: 'position', session_id: 5, current: { slide: 1, click: 0 }, version: 2 });
		expect(now().state?.current).toEqual({ slide: 2, click: 0 });
	});

	it('다른 회차의 발행은 무시한다', async () => {
		const { now } = setup();
		await ready();
		last().push({ type: 'position', session_id: 6, current: { slide: 4, click: 0 }, version: 4 });
		expect(now().state?.current).toEqual({ slide: 2, click: 0 });
	});

	it('건너뛴 version이 있으면 놓친 것이 있으니 통째로 다시 받는다', async () => {
		const { fetchFn, server, now } = setup();
		await ready();
		server.live = { ...structuredClone(LIVE), current: { slide: 4, click: 0 }, session: { ...LIVE.session, version: 6 } };
		last().push({ type: 'position', session_id: 5, current: { slide: 4, click: 0 }, version: 6 });
		await vi.runAllTimersAsync();
		expect(fetchFn).toHaveBeenCalledTimes(4);
		expect(now().state?.session.version).toBe(6);
	});

	it('학생에게는 보낸 항목을 맨 뒤에 붙이고, 거둔 항목은 뺀다 (AC33, AC35)', async () => {
		const { now } = setup();
		await ready();
		const item = { id: 2, body: null, url: 'https://example.com', created_at: '2026-03-01T09:05:00+00:00' };
		last().push({ type: 'item.created', session_id: 5, item, version: 4 });
		expect(now().state?.items.map((i) => i.id)).toEqual([1, 2]);
		last().push({ type: 'item.retracted', session_id: 5, item_id: 1, version: 5 });
		expect(now().state?.items.map((i) => i.id)).toEqual([2]);
		expect(now().state?.session.version).toBe(5);
	});

	it('교수에게는 항목이 바뀌면 거둔 시각까지 다시 받는다', async () => {
		const { fetchFn } = setup({ role: 'professor' });
		await ready();
		last().push({ type: 'item.retracted', session_id: 5, item_id: 1, version: 4 });
		await vi.runAllTimersAsync();
		expect(fetchFn).toHaveBeenCalledTimes(4);
	});

	it('회차 상태가 바뀌면 다시 받는다(수업 시작·종료, AC23, AC38)', async () => {
		const { fetchFn, server, now } = setup({ server: { sessions: { live_session_id: null } } });
		await ready();
		server.sessions = { live_session_id: 5 };
		last().push({ type: 'session.updated', session_id: 5, status: 'live', version: 1 });
		await vi.runAllTimersAsync();
		expect(fetchFn).toHaveBeenCalledTimes(3);
		expect(now().state?.session.status).toBe('live');
	});

	it('불러오는 동안 온 발행은 받은 뒤에 차례로 적용한다', async () => {
		const { now } = setup();
		last().push({ type: 'ready', role: 'student' });
		last().push({ type: 'position', session_id: 5, current: { slide: 3, click: 0 }, version: 4 });
		await vi.runAllTimersAsync();
		expect(now().state?.current).toEqual({ slide: 3, click: 0 });
	});

	it('교수에게는 현황 숫자를 둔다 (AC15)', async () => {
		const { now } = setup({ role: 'professor' });
		await ready();
		last().push({ type: 'presence', follow: 3, browse: 1 });
		expect(now().presence).toEqual({ follow: 3, browse: 1 });
	});
});

describe('다시 받는 때', () => {
	it('resync를 받으면 통째로 다시 받는다', async () => {
		const { fetchFn } = setup();
		await ready();
		last().push({ type: 'resync' });
		await vi.runAllTimersAsync();
		expect(fetchFn).toHaveBeenCalledTimes(4);
	});

	it('화면이 다시 보이면 통째로 다시 받는다(휴대폰 화면을 껐다 켬)', async () => {
		const { fetchFn, doc } = setup();
		await ready();
		doc.show();
		await vi.runAllTimersAsync();
		expect(fetchFn).toHaveBeenCalledTimes(4);
	});

	it('끊긴 상태에서 화면이 다시 보이면 기다리지 않고 바로 다시 붙는다', async () => {
		const { doc } = setup();
		await ready();
		last().drop();
		expect(FakeSocket.all).toHaveLength(1);
		doc.show();
		expect(FakeSocket.all).toHaveLength(2);
	});
});

describe('끊기면 1·2·5·10초 간격으로 다시 붙는다 (C12)', () => {
	it('간격을 늘려 가며 다시 붙고, 다시 붙으면 통째로 다시 받는다', async () => {
		const { fetchFn, now } = setup();
		await ready();
		for (const wait of [1_000, 2_000, 5_000, 10_000, 10_000]) {
			last().drop();
			expect(now().status).toBe('reconnecting');
			const count = FakeSocket.all.length;
			await vi.advanceTimersByTimeAsync(wait - 1);
			expect(FakeSocket.all).toHaveLength(count);
			await vi.advanceTimersByTimeAsync(1);
			expect(FakeSocket.all).toHaveLength(count + 1);
		}
		expect(RETRY_DELAYS).toEqual([1_000, 2_000, 5_000, 10_000]);
		await ready();
		expect(now().status).toBe('live');
		expect(fetchFn).toHaveBeenCalledTimes(4);
	});

	it('끊겨도 마지막 상태는 그대로 둔다', async () => {
		const { now } = setup();
		await ready();
		last().drop();
		expect(now().state).toEqual(LIVE);
	});

	it('다시 붙으면 학생의 직접 넘겨 보기 상태를 다시 알린다', async () => {
		const { live } = setup();
		await ready();
		live.setMode('browse');
		expect(last().sent).toEqual([{ type: 'mode', mode: 'browse' }]);
		last().drop();
		await vi.advanceTimersByTimeAsync(RETRY_DELAYS[0]);
		await ready();
		expect(last().sent).toEqual([{ type: 'mode', mode: 'browse' }]);
	});

	it('처음 상태(따라가는 중)는 따로 알리지 않는다(서버가 그렇게 센다)', async () => {
		setup();
		await ready();
		expect(last().sent).toEqual([]);
	});
});

describe('내보내기 (AC44)', () => {
	it('goodbye를 받으면 안내를 두고 다시 붙지 않는다', async () => {
		const { now } = setup();
		await ready();
		last().push({ type: 'goodbye', reason: 'removed', message: '명단에서 빠졌습니다.' });
		last().drop(4403);
		await vi.advanceTimersByTimeAsync(60_000);
		expect(FakeSocket.all).toHaveLength(1);
		expect(now()).toMatchObject({ status: 'gone', goodbye: { reason: 'removed', message: '명단에서 빠졌습니다.' } });
	});

	it('goodbye 없이 4403으로 닫혀도 다시 붙지 않는다', async () => {
		const { now } = setup();
		await ready();
		last().drop(4403);
		await vi.advanceTimersByTimeAsync(60_000);
		expect(FakeSocket.all).toHaveLength(1);
		expect(now().status).toBe('gone');
	});
});

describe('교수 넘기기 (AC13)', () => {
	it('goto를 보내고 ack를 받으면 그 version으로 끝난다', async () => {
		const { live } = setup({ role: 'professor' });
		await ready();
		const done = live.goto({ slide: 3, click: 1 });
		const sent = last().sent[0] as { req: string };
		expect(sent).toMatchObject({ type: 'goto', session_id: 5, slide: 3, click: 1 });
		last().push({ type: 'ack', req: sent.req, version: 4 });
		await expect(done).resolves.toBe(4);
	});

	it('서버가 거절하면 그 안내로 실패한다', async () => {
		const { live } = setup({ role: 'professor' });
		await ready();
		const done = live.goto({ slide: 9, click: 0 });
		const sent = last().sent[0] as { req: string };
		last().push({ type: 'error', req: sent.req, reason: 'out_of_range', message: '그 위치로 넘길 수 없습니다.' });
		await expect(done).rejects.toMatchObject({ reason: 'out_of_range', message: '그 위치로 넘길 수 없습니다.' });
	});

	it('요청마다 다른 req를 붙이고 제 응답만 받는다', async () => {
		const { live } = setup({ role: 'professor' });
		await ready();
		const a = live.goto({ slide: 2, click: 1 });
		const b = live.goto({ slide: 3, click: 0 });
		const [ra, rb] = last().sent as { req: string }[];
		expect(ra.req).not.toBe(rb.req);
		last().push({ type: 'ack', req: rb.req, version: 5 });
		last().push({ type: 'ack', req: ra.req, version: 4 });
		await expect(a).resolves.toBe(4);
		await expect(b).resolves.toBe(5);
	});

	it('연결이 없거나 끊기면 기다리지 않고 실패한다', async () => {
		const { live } = setup({ role: 'professor' });
		await expect(live.goto({ slide: 2, click: 0 })).rejects.toMatchObject({ reason: 'offline' });
		await ready();
		const pending = live.goto({ slide: 2, click: 0 });
		last().drop();
		await expect(pending).rejects.toMatchObject({ reason: 'offline', message: '연결이 끊겼습니다. 다시 연결되면 넘겨 주세요.' });
	});
});

describe('정리', () => {
	it('멈추면 닫고 다시 붙지 않으며 화면 보임 신호도 듣지 않는다', async () => {
		const { live, doc, fetchFn } = setup();
		await ready();
		live.stop();
		expect(last().readyState).toBe(3);
		await vi.advanceTimersByTimeAsync(60_000);
		doc.show();
		await vi.runAllTimersAsync();
		expect(FakeSocket.all).toHaveLength(1);
		expect(fetchFn).toHaveBeenCalledTimes(2);
	});

	it('구독을 풀면 더 알리지 않는다', async () => {
		const { snapshots, unsubscribe } = setup();
		unsubscribe();
		const count = snapshots.length;
		await ready();
		expect(snapshots).toHaveLength(count);
	});

	it('알 수 없는 형식의 메시지는 무시한다', async () => {
		const { now } = setup();
		await ready();
		last().onmessage?.({ data: 'not json' });
		last().push({ nope: 1 });
		last().push({ type: 'position', session_id: 5, version: 4 }); // 위치가 없다
		expect(now().state).toEqual(LIVE);
	});
});
