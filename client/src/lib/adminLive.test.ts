import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { adminSocketUrl, connectAdmin, RETRY_DELAYS } from './adminLive';

/** 브라우저 WebSocket을 흉내 낸다. 테스트가 서버 쪽 동작(열림, 메시지, 닫힘)을 직접 일으킨다. */
class FakeSocket {
	static all: FakeSocket[] = [];
	onopen: (() => void) | null = null;
	onmessage: ((e: { data: string }) => void) | null = null;
	onclose: (() => void) | null = null;
	onerror: (() => void) | null = null;
	closed = false;
	constructor(public url: string) {
		FakeSocket.all.push(this);
	}
	close() {
		this.closed = true;
		this.onclose?.();
	}
	// 테스트용
	send(data: unknown) {
		this.onmessage?.({ data: JSON.stringify(data) });
	}
	drop() {
		this.onclose?.();
	}
}
const last = () => FakeSocket.all[FakeSocket.all.length - 1];

function setup() {
	const handlers = { onReady: vi.fn(), onEvent: vi.fn(), onStatus: vi.fn() };
	const stop = connectAdmin(7, handlers, {
		location: { protocol: 'http:', host: 'localhost:8000' },
		Socket: FakeSocket as unknown as typeof WebSocket
	});
	return { handlers, stop };
}

beforeEach(() => {
	FakeSocket.all = [];
	vi.useFakeTimers();
});
afterEach(() => vi.useRealTimers());

describe('주소', () => {
	it('같은 출처의 /ws/admin/{강좌}로 연결한다(http면 ws, https면 wss)', () => {
		expect(adminSocketUrl(7, { protocol: 'http:', host: 'localhost:8000' })).toBe('ws://localhost:8000/ws/admin/7');
		expect(adminSocketUrl(7, { protocol: 'https:', host: 'class.example.kr' })).toBe('wss://class.example.kr/ws/admin/7');
	});
});

describe('이벤트 전달 (AC40, AC45)', () => {
	it('ready를 받으면 목록을 불러오라고 알리고 연결됨 상태가 된다', () => {
		const { handlers } = setup();
		expect(last().url).toBe('ws://localhost:8000/ws/admin/7');
		last().send({ type: 'ready' });
		expect(handlers.onReady).toHaveBeenCalledTimes(1);
		expect(handlers.onStatus).toHaveBeenLastCalledWith('live');
	});

	it('그 밖의 이벤트는 종류 그대로 넘긴다', () => {
		const { handlers } = setup();
		last().send({ type: 'ready' });
		last().send({ type: 'join_request.created', id: 3 });
		last().send({ type: 'resync' });
		expect(handlers.onEvent.mock.calls.map((c) => c[0].type)).toEqual(['join_request.created', 'resync']);
	});

	it('알 수 없는 형식의 메시지는 무시한다', () => {
		const { handlers } = setup();
		last().onmessage?.({ data: 'not json' });
		last().send({ nope: 1 });
		expect(handlers.onEvent).not.toHaveBeenCalled();
		expect(handlers.onReady).not.toHaveBeenCalled();
	});
});

describe('끊기면 다시 연결한다 (C13)', () => {
	it('끊기면 다시 연결 중 상태가 되고 정해진 간격 뒤에 새로 연결한다', () => {
		const { handlers } = setup();
		last().send({ type: 'ready' });
		last().drop();
		expect(handlers.onStatus).toHaveBeenLastCalledWith('reconnecting');
		expect(FakeSocket.all).toHaveLength(1);
		vi.advanceTimersByTime(RETRY_DELAYS[0]);
		expect(FakeSocket.all).toHaveLength(2);
	});

	it('다시 연결한 뒤 ready를 받으면 목록을 다시 불러온다(끊긴 사이의 변화를 놓치지 않는다)', () => {
		const { handlers } = setup();
		last().send({ type: 'ready' });
		last().drop();
		vi.advanceTimersByTime(RETRY_DELAYS[0]);
		last().send({ type: 'ready' });
		expect(handlers.onReady).toHaveBeenCalledTimes(2);
		expect(handlers.onStatus).toHaveBeenLastCalledWith('live');
	});

	it('계속 실패하면 간격을 늘리되 상한을 넘지 않는다', () => {
		setup();
		for (let i = 0; i < RETRY_DELAYS.length + 3; i++) {
			last().drop();
			const wait = RETRY_DELAYS[Math.min(i, RETRY_DELAYS.length - 1)];
			vi.advanceTimersByTime(wait - 1);
			expect(FakeSocket.all).toHaveLength(i + 1);
			vi.advanceTimersByTime(1);
			expect(FakeSocket.all).toHaveLength(i + 2);
		}
	});

	it('ready까지 받은 뒤 끊기면 간격을 처음부터 다시 센다', () => {
		setup();
		last().drop();
		vi.advanceTimersByTime(RETRY_DELAYS[0]);
		last().drop();
		vi.advanceTimersByTime(RETRY_DELAYS[1]);
		last().send({ type: 'ready' });
		last().drop();
		vi.advanceTimersByTime(RETRY_DELAYS[0]);
		expect(FakeSocket.all).toHaveLength(4);
	});

	it('한 번도 연결되지 못하면 그 사실도 알린다(화면이 HTTP로 한 번 불러오게)', () => {
		const { handlers } = setup();
		last().drop();
		expect(handlers.onStatus).toHaveBeenLastCalledWith('reconnecting');
		expect(handlers.onStatus).toHaveBeenCalledWith('never-connected');
	});

	it('멈추면 연결을 닫고 다시 연결하지 않는다(화면을 떠날 때)', () => {
		const { stop } = setup();
		last().send({ type: 'ready' });
		const socket = last();
		stop();
		expect(socket.closed).toBe(true);
		vi.advanceTimersByTime(60_000);
		expect(FakeSocket.all).toHaveLength(1);
	});

	it('다시 연결을 기다리는 중에 멈춰도 새로 연결하지 않는다', () => {
		const { stop } = setup();
		last().drop();
		stop();
		vi.advanceTimersByTime(60_000);
		expect(FakeSocket.all).toHaveLength(1);
	});
});
