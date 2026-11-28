import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
	connectAttendanceCode,
	DENIED_MESSAGE,
	FETCH_TIMEOUT,
	offsetFrom,
	parseServerTime,
	RETRY_DELAYS,
	SAMPLE_WINDOW,
	SLOT_MS,
	TOP_UP_DELAY,
	type AttendanceCodeSnapshot
} from './attendanceCode';

// 서버 시계는 이 기기보다 SKEW만큼 앞서 있다. 칸은 서버 시각 기준 15초(plan '출석코드')
const SLOT = 15_000;
const SKEW = 7_300;
const START = Date.UTC(2026, 2, 1, 9, 0, 3, 0); // 이 기기의 시각. 서버로는 09:00:10.3(칸 끝까지 4.7초)
const RTT = 200;

/** 서버가 주는 시각 모양(파이썬 isoformat). 칸 경계처럼 소수가 없으면 소수를 붙이지 않고, 있으면 마이크로초다 */
function iso(ms: number): string {
	const text = new Date(ms).toISOString();
	return ms % 1000 === 0 ? text.replace('.000Z', '+00:00') : text.replace('Z', '000+00:00');
}

type Server = {
	closesAt: number; // 서버 시각
	fail: number; // 이만큼 연달아 실패(503)
	offline: number; // 이만큼 연달아 연결 실패(fetch가 던진다)
	closed: boolean; // 마감(409)
	calls: number;
	paths: [number, number][]; // 다음 요청들의 (가는 길, 오는 길) ms. 비면 rtt를 반씩
	rtt: number;
	skew: number; // 서버 시각 - 이 기기 시각. 기기 시계가 바뀐 것을 흉내 낼 때만 바꾼다
	hang: number; // 이만큼 연달아 답하지 않는다(취소될 때까지)
	status: number | null; // 한 번 이 상태로 답한다(401 등)
	body: unknown; // 한 번 이 본문으로 답한다(시각을 읽지 못하는 응답 등)
};

/** 화면이 숨었다가 다시 보이는 것을 흉내 낸다 */
class FakeDocument extends EventTarget {
	visibilityState: DocumentVisibilityState = 'visible';
	show() {
		this.visibilityState = 'visible';
		this.dispatchEvent(new Event('visibilitychange'));
	}
}

const codeOf = (slot: number) => `c${slot}`;

/** 서버 흉내. 요청이 오가는 데 RTT가 걸린다(가는 길 절반, 오는 길 절반). */
function fakeFetch(server: Server) {
	return vi.fn(async (url: string, init?: RequestInit) => {
		server.calls += 1;
		if (server.hang) {
			server.hang -= 1;
			return new Promise<Response>((_, reject) =>
				init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
			);
		}
		expect(url).toBe('/api/classrooms/7/sessions/5/attendance/code');
		const [out, back] = server.paths.shift() ?? [server.rtt / 2, server.rtt / 2];
		vi.setSystemTime(Date.now() + out);
		const serverNow = Date.now() + server.skew;
		vi.setSystemTime(Date.now() + back);
		if (server.offline) {
			server.offline -= 1;
			throw new TypeError('Failed to fetch');
		}
		if (server.fail) {
			server.fail -= 1;
			return new Response(JSON.stringify({ detail: '잠시 뒤 다시' }), {
				status: 503
			});
		}
		if (server.status !== null) {
			const status = server.status;
			server.status = null;
			return Response.json({ detail: '이 강좌에 대한 권한이 없습니다.' }, { status });
		}
		if (server.closed || serverNow >= server.closesAt) {
			return Response.json({ detail: '지금은 출석을 받고 있지 않습니다.' }, { status: 409 });
		}
		const slot = Math.floor(serverNow / SLOT);
		if (server.body !== null) {
			const body = server.body;
			server.body = null;
			return Response.json(body);
		}
		return Response.json({
			current: { code: codeOf(slot), ends_at: iso((slot + 1) * SLOT) },
			next: { code: codeOf(slot + 1), ends_at: iso((slot + 2) * SLOT) },
			closes_at: iso(server.closesAt),
			server_now: iso(serverNow)
		});
	});
}

/** 서버 시각으로 지금 칸 */
const serverSlot = () => Math.floor((Date.now() + SKEW) / SLOT);

let server: Server;
let seen: AttendanceCodeSnapshot[];
let onClosed: ReturnType<typeof vi.fn<() => void>>;
let doc: FakeDocument;

function open(extra: Partial<Server> = {}) {
	server = {
		closesAt: START + SKEW + 10 * 60_000,
		fail: 0,
		offline: 0,
		closed: false,
		calls: 0,
		paths: [],
		rtt: RTT,
		skew: SKEW,
		hang: 0,
		status: null,
		body: null,
		...extra
	};
	seen = [];
	onClosed = vi.fn<() => void>();
	doc = new FakeDocument();
	const live = connectAttendanceCode(7, 5, {
		fetchFn: fakeFetch(server) as unknown as typeof fetch,
		onClosed,
		document: doc
	});
	live.subscribe((s) => seen.push(s));
	return live;
}
const latest = () => seen[seen.length - 1];

beforeEach(() => {
	vi.useFakeTimers({ now: START });
});
afterEach(() => {
	vi.useRealTimers();
});

describe('서버 시각 차이', () => {
	it('왕복의 중간값으로 구한다', () => {
		// 보낸 때 1000, 받은 때 1400, 서버 시각 5200 → 중간(1200)에 서버가 5200이었다
		expect(offsetFrom(1_000, 5_200, 1_400)).toBe(4_000);
	});

	it('받은 코드 응답으로 서버 시각을 맞춘다', async () => {
		const live = open();
		await vi.advanceTimersByTimeAsync(0);
		expect(Math.abs(live.serverNow() - (Date.now() + SKEW))).toBeLessThanOrEqual(1);
		live.stop();
	});

	it('왕복이 가장 짧았던 응답의 차이를 쓴다', async () => {
		// 중간값 추정의 틀림은 가는 길과 오는 길의 차이의 절반이라 왕복이 짧을수록 정확하다
		const live = open({ paths: [[1_900, 100]] }); // 첫 응답은 가는 길이 느렸다: 서버 시각을 900ms 앞서 잡는다
		await vi.advanceTimersByTimeAsync(0);
		expect(live.serverNow() - (Date.now() + SKEW)).toBe(900);
		server.paths.push([50, 50]); // 짧은 왕복이 오면 그것을 쓴다
		live.refresh();
		await vi.advanceTimersByTimeAsync(0);
		expect(live.serverNow() - (Date.now() + SKEW)).toBe(0);
		server.paths.push([100, 2_900]); // 그 뒤의 긴 왕복은 쓰지 않는다
		live.refresh();
		await vi.advanceTimersByTimeAsync(0);
		expect(live.serverNow() - (Date.now() + SKEW)).toBe(0);
		live.stop();
	});
});

describe('코드 받아 오기', () => {
	it('처음 받으면 지금 칸의 코드와 끝나는 시각, 마감 시각을 보인다', async () => {
		const live = open();
		expect(latest()).toMatchObject({
			status: 'loading',
			code: null,
			stale: false
		});
		await vi.advanceTimersByTimeAsync(0);
		const slot = serverSlot();
		expect(latest()).toMatchObject({
			status: 'open',
			code: codeOf(slot),
			slotEndsAt: (slot + 1) * SLOT,
			closesAt: server.closesAt,
			stale: false
		});
		live.stop();
	});

	it('칸 경계에서 다음 코드로 바뀌고, 곧바로 그다음 코드를 받는다', async () => {
		const live = open();
		await vi.advanceTimersByTimeAsync(0);
		const first = serverSlot();
		expect(server.calls).toBe(1);
		// 경계 직전에는 그대로다
		const untilBoundary = (first + 1) * SLOT - live.serverNow();
		await vi.advanceTimersByTimeAsync(untilBoundary - 50);
		expect(latest().code).toBe(codeOf(first));
		expect(server.calls).toBe(1);
		// 경계를 지나면 미리 받아 둔 다음 코드로 바뀌고(요청을 기다리지 않는다), 그다음 코드를 받으러 간다
		await vi.advanceTimersByTimeAsync(50);
		expect(seen.some((s) => s.code === codeOf(first + 1) && !s.stale)).toBe(true);
		expect(server.calls).toBe(2);
		await vi.advanceTimersByTimeAsync(0);
		expect(latest()).toMatchObject({
			code: codeOf(first + 1),
			slotEndsAt: (first + 2) * SLOT,
			stale: false
		});
		live.stop();
	});

	it('여러 칸을 지나도 서버 시각의 칸과 같은 코드를 보인다', async () => {
		const live = open();
		await vi.advanceTimersByTimeAsync(0);
		for (let i = 0; i < 6; i += 1) {
			await vi.advanceTimersByTimeAsync(SLOT);
			expect(latest().code).toBe(codeOf(serverSlot()));
			expect(latest().stale).toBe(false);
		}
		live.stop();
	});

	it('경계는 이 기기 시계가 아니라 서버 시각으로 잡는다', async () => {
		const live = open();
		await vi.advanceTimersByTimeAsync(0);
		const first = serverSlot();
		// 이 기기 시계로는 칸이 15초 뒤에 끝나지만, 서버 시각으로는 4.7초 남았다
		await vi.advanceTimersByTimeAsync((first + 1) * SLOT - (Date.now() + SKEW) + 10);
		expect(latest().code).toBe(codeOf(first + 1));
		live.stop();
	});

	it('경계에서 서버가 아직 앞 칸이면 조금 뒤 다시 받아 그다음 코드를 채운다', async () => {
		// 첫 응답(왕복 150ms)의 가는 길이 느려 이 화면은 서버 시각을 75ms 앞서 잡았다. 경계에서 받는 요청은 왕복이
		// 더 길어(220ms) 그 값을 바꾸지 않고, 가는 길이 짧아(20ms) 서버에는 아직 앞 칸일 때 닿는다. 그러면 지금 칸의
		// 다음 코드가 오지 않는다. 채우지 않으면 다음 경계에서 코드가 비고 흐려진다
		const live = open({
			paths: [
				[150, 0],
				[20, 200]
			],
			rtt: 400
		});
		await vi.advanceTimersByTimeAsync(0);
		const shownSlot = () => Math.floor(live.serverNow() / SLOT);
		await vi.advanceTimersByTimeAsync((shownSlot() + 1) * SLOT - live.serverNow());
		const calls = server.calls;
		await vi.advanceTimersByTimeAsync(TOP_UP_DELAY);
		expect(server.calls).toBe(calls + 1);
		await vi.advanceTimersByTimeAsync((shownSlot() + 1) * SLOT - live.serverNow());
		expect(seen.some((s) => s.stale || (s.status === 'open' && s.code === null))).toBe(false);
		expect(latest().code).toBe(codeOf(shownSlot()));
		live.stop();
	});
});

describe('받기 실패', () => {
	it('받기에 실패하면 흐림 상태가 되고, 다시 성공하면 지금 코드로 돌아온다', async () => {
		const live = open();
		await vi.advanceTimersByTimeAsync(0);
		const first = serverSlot();
		server.offline = 3; // 다음 받기부터 세 번 연결 실패
		await vi.advanceTimersByTimeAsync((first + 1) * SLOT - live.serverNow());
		expect(latest()).toMatchObject({ code: codeOf(first + 1), stale: true }); // 다음 코드는 있지만 그다음을 못 받았다
		// 다시 시도는 간격을 늘려 간다
		await vi.advanceTimersByTimeAsync(RETRY_DELAYS[0] + RETRY_DELAYS[1] + RETRY_DELAYS[2]);
		expect(server.calls).toBe(5);
		expect(latest()).toMatchObject({
			code: codeOf(serverSlot()),
			stale: false
		});
		live.stop();
	});

	it('서버 오류도 흐림이다', async () => {
		const live = open({ fail: 1 });
		await vi.advanceTimersByTimeAsync(0);
		expect(latest()).toMatchObject({
			status: 'loading',
			code: null,
			stale: true
		});
		await vi.advanceTimersByTimeAsync(RETRY_DELAYS[0]);
		expect(latest()).toMatchObject({
			status: 'open',
			code: codeOf(serverSlot()),
			stale: false
		});
		live.stop();
	});

	it('받아 둔 코드가 다 지나면 낡은 코드를 보이지 않는다', async () => {
		// 교수 연결이 끊기면 낡은 코드를 띄우지 않는다(스펙 오류 표). 받아 둔 칸이 끝나면 코드를 비운다
		const live = open();
		await vi.advanceTimersByTimeAsync(0);
		const first = serverSlot();
		server.offline = 1_000;
		await vi.advanceTimersByTimeAsync((first + 2) * SLOT - live.serverNow() + 10);
		expect(latest()).toMatchObject({ status: 'open', code: null, stale: true });
		server.offline = 0;
		await vi.advanceTimersByTimeAsync(RETRY_DELAYS[RETRY_DELAYS.length - 1]);
		expect(latest()).toMatchObject({
			code: codeOf(serverSlot()),
			stale: false
		});
		live.stop();
	});
});

describe('마감', () => {
	it('마감 시각이 되면 닫힘 상태가 되고 live를 다시 받게 한다', async () => {
		// 왕복 0: 경계마다 받기가 시계를 밀지 않게 해서 마감 직전을 정확히 맞춘다
		const live = open({ closesAt: START + SKEW + 40_000, rtt: 0 });
		await vi.advanceTimersByTimeAsync(0);
		await vi.advanceTimersByTimeAsync(server.closesAt - live.serverNow() - 100);
		expect(latest().status).toBe('open');
		expect(onClosed).not.toHaveBeenCalled();
		await vi.advanceTimersByTimeAsync(100);
		expect(latest()).toMatchObject({ status: 'closed', code: null });
		expect(onClosed).toHaveBeenCalledTimes(1);
		const calls = server.calls;
		await vi.advanceTimersByTimeAsync(60_000);
		expect(server.calls).toBe(calls); // 닫힌 뒤에는 받지 않는다
		live.stop();
	});

	it('마감이 칸 경계와 같으면 다음 칸 코드를 보이지 않고 닫는다', async () => {
		const boundary = (Math.floor((START + SKEW) / SLOT) + 2) * SLOT; // 서버 시각으로 두 번째 경계
		const live = open({ closesAt: boundary });
		await vi.advanceTimersByTimeAsync(0);
		await vi.advanceTimersByTimeAsync(boundary - live.serverNow());
		expect(latest()).toMatchObject({ status: 'closed', code: null });
		const shown = seen.filter((s) => s.code !== null).map((s) => s.slotEndsAt!);
		expect(Math.max(...shown)).toBe(boundary); // 마감 뒤에 시작하는 칸의 코드는 한 번도 보이지 않았다
		live.stop();
	});

	it('마감은 이 기기 시계가 아니라 서버 시각으로 잡는다', async () => {
		const live = open({ closesAt: START + SKEW + 40_000 });
		await vi.advanceTimersByTimeAsync(0);
		// 서버가 이 기기보다 앞서 있으므로, 이 기기 시계로 40초가 되기 전에 닫힌다
		await vi.advanceTimersByTimeAsync(server.closesAt - (Date.now() + SKEW) + 1);
		expect(latest().status).toBe('closed');
		expect(Date.now() - START).toBeLessThan(40_000 + 1_000); // 기기 시계로 잡았다면 40초 + SKEW 뒤에 닫힌다
		live.stop();
	});

	it('받는 도중 연장 알림이 오면 끝난 뒤 한 번 더 받는다', async () => {
		const live = open({ closesAt: START + SKEW + 40_000 });
		live.refresh(); // 처음 받기가 끝나기 전에
		server.closesAt += 5 * 60_000;
		await vi.advanceTimersByTimeAsync(0);
		expect(server.calls).toBe(2);
		expect(latest().closesAt).toBe(server.closesAt);
		live.stop();
	});

	it('서버가 창이 없다고 하면(409) 닫힘 상태가 되고 live를 다시 받게 한다', async () => {
		const live = open({ closed: true });
		await vi.advanceTimersByTimeAsync(0);
		expect(latest()).toMatchObject({
			status: 'closed',
			code: null,
			stale: false
		});
		expect(onClosed).toHaveBeenCalledTimes(1);
		live.stop();
	});

	it('연장으로 마감 시각이 늦어지면 다음 받기에서 새 마감 시각을 쓴다', async () => {
		const live = open({ closesAt: START + SKEW + 40_000 });
		await vi.advanceTimersByTimeAsync(0);
		server.closesAt += 5 * 60_000; // 교수가 연장했다
		live.refresh();
		await vi.advanceTimersByTimeAsync(0);
		expect(latest().closesAt).toBe(server.closesAt);
		await vi.advanceTimersByTimeAsync(60_000);
		expect(latest().status).toBe('open');
		expect(onClosed).not.toHaveBeenCalled();
		live.stop();
	});
});

describe('멈추기', () => {
	it('stop 뒤에는 받지 않고 알리지 않는다', async () => {
		const live = open();
		await vi.advanceTimersByTimeAsync(0);
		live.stop();
		const calls = server.calls;
		const count = seen.length;
		await vi.advanceTimersByTimeAsync(120_000);
		expect(server.calls).toBe(calls);
		expect(seen.length).toBe(count);
	});

	it('받는 도중 멈추면 그 응답을 버린다', async () => {
		const live = open();
		live.stop();
		await vi.advanceTimersByTimeAsync(0);
		expect(seen.length).toBe(1);
		expect(onClosed).not.toHaveBeenCalled();
	});
});

describe('검증에서 더한 경우', () => {
	it('서버 시각의 소수 자리를 브라우저와 상관없이 읽는다', () => {
		expect(parseServerTime('2026-03-01T09:00:15+00:00')).toBe(Date.UTC(2026, 2, 1, 9, 0, 15));
		expect(parseServerTime('2026-03-01T09:00:15.123456+00:00')).toBe(Date.UTC(2026, 2, 1, 9, 0, 15, 123));
		expect(() => parseServerTime('garbage')).toThrow();
		expect(() => parseServerTime(12)).toThrow();
	});

	it('정확히 칸 경계에서 다음 코드를 보인다', async () => {
		const live = open({ rtt: 0 });
		await vi.advanceTimersByTimeAsync(0);
		const first = serverSlot();
		await vi.advanceTimersByTimeAsync((first + 1) * SLOT_MS - live.serverNow());
		expect(live.serverNow()).toBe((first + 1) * SLOT_MS);
		expect(latest().code).toBe(codeOf(first + 1));
		live.stop();
	});

	it('다시 시도 간격을 늘려 가고, 성공하면 처음 간격부터 다시 센다', async () => {
		const live = open({ rtt: 0, offline: 1 });
		await vi.advanceTimersByTimeAsync(0); // 1번째 실패
		server.offline = 2;
		await vi.advanceTimersByTimeAsync(RETRY_DELAYS[0]); // 2번째(실패)
		expect(server.calls).toBe(2);
		await vi.advanceTimersByTimeAsync(RETRY_DELAYS[1] - 1);
		expect(server.calls).toBe(2); // 아직 2초가 안 됐다
		await vi.advanceTimersByTimeAsync(1); // 3번째(실패)
		expect(server.calls).toBe(3);
		await vi.advanceTimersByTimeAsync(RETRY_DELAYS[2]); // 4번째(성공)
		expect(latest()).toMatchObject({ status: 'open', stale: false });
		// 다시 실패하면 처음 간격(1초)부터
		server.offline = 1;
		live.refresh();
		await vi.advanceTimersByTimeAsync(0);
		const calls = server.calls;
		await vi.advanceTimersByTimeAsync(RETRY_DELAYS[0]);
		expect(server.calls).toBe(calls + 1);
		expect(latest().stale).toBe(false);
		live.stop();
	});

	it('응답이 오지 않으면 시간 제한 뒤 흐림이 되고 다시 시도한다', async () => {
		const live = open({ rtt: 0, hang: 1 });
		await vi.advanceTimersByTimeAsync(FETCH_TIMEOUT - 1);
		expect(latest()).toMatchObject({ status: 'loading', stale: false });
		await vi.advanceTimersByTimeAsync(1);
		expect(latest()).toMatchObject({ status: 'loading', stale: true });
		await vi.advanceTimersByTimeAsync(RETRY_DELAYS[0]);
		expect(latest()).toMatchObject({ status: 'open', code: codeOf(serverSlot()), stale: false });
		live.stop();
	});

	it('로그인이 끝났거나 권한이 없으면 다시 시도하지 않고 안내와 함께 멈춘다', async () => {
		for (const [status, message] of [
			[401, DENIED_MESSAGE],
			[403, '이 강좌에 대한 권한이 없습니다.'],
			[404, '이 강좌에 대한 권한이 없습니다.']
		] as const) {
			const live = open({ status });
			await vi.advanceTimersByTimeAsync(0);
			expect(latest()).toMatchObject({ status: 'denied', code: null, stale: false, message });
			await vi.advanceTimersByTimeAsync(60_000);
			live.refresh();
			doc.show();
			await vi.advanceTimersByTimeAsync(0);
			expect(server.calls).toBe(1);
			expect(onClosed).not.toHaveBeenCalled();
			live.stop();
		}
	});

	it('시각을 읽지 못하는 응답은 흐림이고 다시 시도한다', async () => {
		const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
		const live = open({ rtt: 0, body: { server_now: 'garbage' } });
		await vi.advanceTimersByTimeAsync(0);
		expect(latest()).toMatchObject({ status: 'loading', code: null, stale: true });
		expect(warn).toHaveBeenCalled();
		await vi.advanceTimersByTimeAsync(RETRY_DELAYS[0]);
		expect(latest()).toMatchObject({ status: 'open', stale: false });
		warn.mockRestore();
		live.stop();
	});

	it('받는 도중 다시 받으라는 요청이 오면, 실패해도 다시 시도 간격을 기다리지 않고 곧바로 받는다', async () => {
		for (const extra of [{ offline: 1 }, { fail: 1 }]) {
			const live = open({ rtt: 0, ...extra });
			live.refresh();
			await vi.advanceTimersByTimeAsync(0);
			expect(server.calls).toBe(2);
			expect(latest()).toMatchObject({ status: 'open', stale: false });
			live.stop();
		}
	});

	it('다시 시도를 기다리는 중에 받기에 성공하면 기다리던 다시 시도는 하지 않는다', async () => {
		const live = open({ rtt: 0, fail: 1 });
		await vi.advanceTimersByTimeAsync(0);
		live.refresh();
		await vi.advanceTimersByTimeAsync(0);
		expect(server.calls).toBe(2);
		await vi.advanceTimersByTimeAsync(RETRY_DELAYS[0]);
		expect(server.calls).toBe(2);
		live.stop();
	});

	it('끊긴 채로 마감 시각이 지나도 닫히고 live를 다시 받게 한다', async () => {
		const live = open({ closesAt: START + SKEW + 40_000 });
		await vi.advanceTimersByTimeAsync(0);
		server.offline = 1_000;
		await vi.advanceTimersByTimeAsync(41_000);
		expect(latest()).toMatchObject({ status: 'closed', code: null });
		expect(onClosed).toHaveBeenCalledTimes(1);
		live.stop();
	});

	it('마감으로 닫힌 뒤 받기가 409로 끝나도 onClosed는 한 번이다', async () => {
		const live = open({ closesAt: START + SKEW + 40_000, rtt: 0 });
		await vi.advanceTimersByTimeAsync(0);
		await vi.advanceTimersByTimeAsync(server.closesAt - live.serverNow() - 10);
		server.paths.push([0, 50]); // 마감 직전에 보낸 요청의 답이 마감 뒤에 온다
		server.closed = true;
		live.refresh();
		await vi.advanceTimersByTimeAsync(100);
		expect(latest().status).toBe('closed');
		expect(onClosed).toHaveBeenCalledTimes(1);
		live.stop();
	});

	it('멈춘 뒤 409가 와도 onClosed를 부르지 않는다', async () => {
		const live = open({ closed: true });
		live.stop();
		await vi.advanceTimersByTimeAsync(0);
		expect(onClosed).not.toHaveBeenCalled();
	});

	it('닫힌 뒤에도 refresh로 다시 받아, 다시 열렸으면 다시 보인다', async () => {
		// 교수가 '출석 다시 받기'를 눌렀다(T017). 화면은 attendance.updated를 받고 refresh를 부른다
		const live = open({ closed: true, rtt: 0 });
		await vi.advanceTimersByTimeAsync(0);
		expect(latest().status).toBe('closed');
		server.closed = false;
		live.refresh();
		await vi.advanceTimersByTimeAsync(0);
		expect(latest()).toMatchObject({ status: 'open', code: codeOf(serverSlot()), stale: false });
		await vi.advanceTimersByTimeAsync(SLOT_MS);
		expect(latest().code).toBe(codeOf(serverSlot())); // 경계도 다시 돈다
		live.stop();
	});

	it('왕복이 음수이거나 너무 길면 시차 계산에 쓰지 않는다', async () => {
		const live = open({ paths: [[50, 50]] });
		await vi.advanceTimersByTimeAsync(0);
		const good = live.serverNow() - Date.now();
		server.paths.push([100, -5_000]); // 받는 사이 기기 시계가 5초 뒤로 갔다(왕복이 음수)
		live.refresh();
		await vi.advanceTimersByTimeAsync(0);
		vi.setSystemTime(Date.now() + 5_000); // 테스트용 시계를 되돌린다(기기 시계는 그대로라 보고)
		expect(live.serverNow() - Date.now()).toBe(good);
		live.stop();
	});

	it('기기 시계가 바뀌면 최근 응답으로 곧 다시 맞춘다', async () => {
		const live = open({ paths: [[10, 10]] }); // 아주 짧은 왕복으로 시차를 잡았다
		await vi.advanceTimersByTimeAsync(0);
		expect(live.serverNow() - (Date.now() + SKEW)).toBe(0);
		server.skew += 3_000; // 기기 시계가 3초 뒤로 맞춰졌다(NTP). 서버와의 차이가 3초 늘었다
		for (let i = 0; i < SAMPLE_WINDOW; i += 1) {
			live.refresh(); // 그 뒤 응답은 왕복이 더 길다(200ms)
			await vi.advanceTimersByTimeAsync(0);
		}
		expect(live.serverNow() - (Date.now() + server.skew)).toBe(0);
		live.stop();
	});

	it('화면이 다시 보이면 늦어진 타이머를 기다리지 않고 바로 맞춘다', async () => {
		// 숨긴 탭이나 잠든 노트북은 타이머가 늦게 깬다. 다시 보이면 곧바로 다시 그리고 받는다
		const live = open({ rtt: 0 });
		await vi.advanceTimersByTimeAsync(0);
		vi.setSystemTime(Date.now() + 47_000); // 타이머는 깨지 않고 시간만 흘렀다
		const calls = server.calls;
		doc.show();
		await vi.advanceTimersByTimeAsync(0);
		expect(server.calls).toBe(calls + 1);
		expect(latest()).toMatchObject({ code: codeOf(serverSlot()), stale: false });
		live.stop();
	});

	it('stop 뒤에는 화면이 다시 보여도 받지 않는다', async () => {
		const live = open();
		await vi.advanceTimersByTimeAsync(0);
		live.stop();
		doc.show();
		await vi.advanceTimersByTimeAsync(0);
		expect(server.calls).toBe(1);
	});
});
