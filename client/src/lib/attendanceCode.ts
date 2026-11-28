/**
 * 출석코드 받아 오기와 서버 시각 맞추기(003 T015, AC3). 교수 수업 화면과 프로젝터가 함께 쓴다.
 *
 * plan '코드 전달': 화면은 `GET …/attendance/code`로 지금·다음 코드, 각 칸이 끝나는 시각, 마감 시각, 서버 시각을 받는다.
 * - 서버 시각과의 차이는 요청 왕복의 중간값으로 구한다. 최근 응답 가운데 왕복이 가장 짧았던 것의 값을 쓴다
 *   (틀림이 가장 작다). 최근 것만 보므로 기기 시계가 바뀌어도(NTP 보정, 잠자기에서 깸) 곧 다시 맞는다.
 * - 칸 경계(서버 시각)에서 미리 받아 둔 다음 코드로 바꾸고, 곧바로 그다음 코드를 받는다. 그래서 여러 화면이 함께 바뀐다.
 * - 받기에 실패하면 흐림(`stale`)이다. 간격을 늘려 가며 다시 받고, 성공하면 지금 코드로 돌아온다.
 *   받아 둔 칸이 다 지나면 코드를 비운다. 받아 둔 다음 칸 코드는 서버 시각으로 맞는 코드라 흐리게 보인다(낡은 코드가 아니다).
 * - 마감 시각(서버 시각)이 되거나 서버가 창이 없다고 하면(409) 닫힘이고, `onClosed`로 화면이 `live`를 다시 받게 한다.
 *   닫힌 뒤에도 `refresh()`로 다시 받을 수 있다(다시 받기·연장 알림). 열려 있으면 다시 보인다.
 * - 로그인이 끝났거나(401) 권한이 없거나(403) 회차가 없으면(404) 다시 시도하지 않고 `denied`로 멈춘다.
 * - 화면이 다시 보이면(숨긴 탭, 잠자기에서 깸) 늦어진 타이머를 기다리지 않고 바로 다시 그리고 받는다.
 * 이 모듈은 칸 경계와 마감에만 알린다. 남은 시간 막대·원은 화면이 `slotEndsAt - serverNow()`로 따로 그린다(`SLOT_MS`).
 * WebSocket을 쓰지 않으므로, 교수 연결이 끊겨도 프로젝터는 HTTP로 계속 코드를 바꾼다(C12).
 */

export type AttendanceCodeStatus = 'loading' | 'open' | 'closed' | 'denied';
export type AttendanceCodeSnapshot = {
	status: AttendanceCodeStatus;
	/** 지금 보일 6자리 코드. 아직 없거나 받아 둔 칸이 다 지났거나 닫혔으면 null. */
	code: string | null;
	/** 지금 칸이 끝나는 서버 시각(ms). */
	slotEndsAt: number | null;
	/** 마감 서버 시각(ms). */
	closesAt: number | null;
	/** 마지막 받기가 실패했거나 보일 코드가 없다(흐리게, "다시 연결하는 중"). */
	stale: boolean;
	/** `denied`일 때 보일 안내(한국어). */
	message: string | null;
};

type CodeResponse = {
	current: { code: string; ends_at: string };
	next: { code: string; ends_at: string };
	closes_at: string;
	server_now: string;
};

type Doc = Pick<Document, 'addEventListener' | 'removeEventListener' | 'visibilityState'>;
type Options = {
	fetchFn?: typeof fetch;
	/** 이 기기의 시각(ms). 테스트가 바꾼다. */
	now?: () => number;
	/** 닫혔을 때(마감 시각, 409). 화면은 `live`를 다시 받아 창 상태를 확인한다. */
	onClosed?: () => void;
	document?: Doc;
};

/** 칸 길이(서버 `attendance_core`와 같다). 남은 시간 막대의 분모. */
export const SLOT_MS = 15_000;
/** 실패한 받기를 다시 하는 간격. 마지막 값을 계속 쓴다. */
export const RETRY_DELAYS = [1_000, 2_000, 5_000, 10_000];
/** 받은 응답에 지금 칸 다음 코드가 없으면(경계에서 서버가 아직 앞 칸이었다) 이만큼 뒤에 다시 받는다. */
export const TOP_UP_DELAY = 1_000;
/** 응답이 이만큼 오지 않으면 끊긴 것으로 보고 다시 시도한다(교실 와이파이가 말없이 멈출 때). */
export const FETCH_TIMEOUT = 5_000;
/** 시차를 고를 최근 응답 수. 15초마다 받으니 약 2분이다. */
export const SAMPLE_WINDOW = 8;
/** 이보다 긴(또는 음수인) 왕복은 시차 계산에 쓰지 않는다(그사이 기기 시계가 바뀌었을 수 있다). */
export const MAX_RTT = 10_000;

const DENIED = new Set([401, 403, 404]);
export const DENIED_MESSAGE = '출석코드를 볼 수 없습니다. 다시 로그인한 뒤 수업 화면을 새로 열어 주세요.';

/** 보낸 때(t0)와 받은 때(t1) 사이 중간에 서버 시각이 serverNow였다고 보고, 서버 시각 - 이 기기 시각을 구한다. */
export function offsetFrom(t0: number, serverNow: number, t1: number): number {
	return serverNow - (t0 + t1) / 2;
}

/** 서버 시각(파이썬 isoformat). 소수 자릿수가 셋보다 길면 브라우저마다 읽기가 달라 셋으로 자른다. */
export function parseServerTime(value: unknown): number {
	const ms = typeof value === 'string' ? Date.parse(value.replace(/(\.\d{3})\d+/, '$1')) : NaN;
	if (Number.isNaN(ms)) throw new Error('서버 시각을 읽지 못했습니다.');
	return ms;
}

export function connectAttendanceCode(classroomId: number, sessionId: number, options: Options = {}) {
	const fetchFn = options.fetchFn ?? fetch;
	const now = options.now ?? (() => Date.now());
	const doc = options.document ?? (typeof document === 'undefined' ? null : document);
	const url = `/api/classrooms/${classroomId}/sessions/${sessionId}/attendance/code`;

	let snapshot: AttendanceCodeSnapshot = {
		status: 'loading',
		code: null,
		slotEndsAt: null,
		closesAt: null,
		stale: false,
		message: null
	};
	const listeners = new Set<(s: AttendanceCodeSnapshot) => void>();
	const slots = new Map<number, string>(); // 칸이 끝나는 서버 시각 → 코드
	const samples: { rtt: number; offset: number }[] = [];
	let offset: number | null = null;
	let closesAt: number | null = null;
	let stale = false;
	let failures = 0;
	let loading: AbortController | null = null;
	let again = false; // 받는 도중 다시 받으라는 요청이 왔다(연장 알림 등). 끝나면 한 번 더 받는다
	let stopped = false;
	let tickTimer: ReturnType<typeof setTimeout> | null = null;
	let fetchTimer: ReturnType<typeof setTimeout> | null = null;

	const serverNow = () => now() + (offset ?? 0);
	const finished = () => stopped || snapshot.status === 'denied';

	function emit(next: AttendanceCodeSnapshot) {
		snapshot = next;
		for (const listener of listeners) listener(snapshot);
	}

	function clearTimers() {
		if (tickTimer) clearTimeout(tickTimer);
		if (fetchTimer) clearTimeout(fetchTimer);
		tickTimer = fetchTimer = null;
	}

	function close() {
		if (snapshot.status === 'closed') return;
		clearTimers();
		slots.clear();
		stale = false;
		emit({ status: 'closed', code: null, slotEndsAt: null, closesAt, stale: false, message: null });
		options.onClosed?.();
	}

	function deny(message: string) {
		clearTimers();
		slots.clear();
		emit({ status: 'denied', code: null, slotEndsAt: null, closesAt, stale: false, message });
	}

	/** 지금 서버 시각의 칸을 고른다. 칸이 끝나거나 마감되는 때에 다시 부르도록 걸어 둔다. */
	function render(): number | null {
		if (finished() || snapshot.status === 'closed') return null;
		const at = serverNow();
		if (closesAt !== null && at >= closesAt) {
			close();
			return null;
		}
		for (const endsAt of [...slots.keys()]) if (endsAt <= at) slots.delete(endsAt);
		const endsAt = slots.size ? Math.min(...slots.keys()) : null;
		const code = endsAt === null ? null : slots.get(endsAt)!;
		const status: AttendanceCodeStatus = offset === null ? 'loading' : 'open';
		emit({
			status,
			code,
			slotEndsAt: endsAt,
			closesAt,
			stale: stale || (status === 'open' && code === null),
			message: null
		});

		if (tickTimer) clearTimeout(tickTimer);
		tickTimer = null;
		const wakeAt = Math.min(endsAt ?? Infinity, closesAt ?? Infinity);
		if (offset !== null && wakeAt !== Infinity) {
			tickTimer = setTimeout(onBoundary, Math.max(0, wakeAt - serverNow()));
		}
		return endsAt;
	}

	function onBoundary() {
		tickTimer = null;
		render();
		if (snapshot.status === 'open') void load(); // 바꾸자마자 그다음 코드를 받는다
	}

	function schedule(delay: number) {
		if (finished() || snapshot.status === 'closed') return;
		if (fetchTimer) clearTimeout(fetchTimer);
		fetchTimer = setTimeout(() => {
			fetchTimer = null;
			void load();
		}, delay);
	}

	function fail() {
		stale = true;
		const delay = RETRY_DELAYS[Math.min(failures, RETRY_DELAYS.length - 1)];
		failures += 1;
		render();
		schedule(delay);
	}

	function adopt(rtt: number, sample: number) {
		if (rtt < 0 || rtt > MAX_RTT) return; // 그사이 기기 시계가 바뀌었거나 너무 느려 믿을 수 없다
		samples.push({ rtt, offset: sample });
		if (samples.length > SAMPLE_WINDOW) samples.shift();
		offset = samples.reduce((best, s) => (s.rtt < best.rtt ? s : best)).offset;
	}

	/** 한 번 받는다. 닫힌 뒤에는 `reopen`일 때만(화면이 다시 받으라고 할 때) 받는다. */
	async function load(reopen = false) {
		if (finished() || (snapshot.status === 'closed' && !reopen)) return;
		if (loading) {
			again = true;
			return;
		}
		const controller = new AbortController();
		loading = controller;
		again = false;
		if (fetchTimer) clearTimeout(fetchTimer);
		fetchTimer = null;
		const timeout = setTimeout(() => controller.abort(), FETCH_TIMEOUT);
		try {
			await handle(controller);
		} finally {
			clearTimeout(timeout);
			loading = null;
			if (again && !stopped) void load(reopen);
		}
	}

	async function handle(controller: AbortController) {
		const t0 = now();
		let res: Response;
		let t1: number;
		let body: CodeResponse | null = null;
		try {
			res = await fetchFn(url, {
				credentials: 'same-origin',
				cache: 'no-store',
				headers: { Accept: 'application/json' },
				signal: controller.signal
			});
			t1 = now(); // 본문을 읽는 시간은 왕복에 넣지 않는다
			if (res.ok) body = (await res.json()) as CodeResponse;
		} catch {
			if (!stopped) fail();
			return;
		}
		if (stopped) return;
		if (res.status === 409) return close();
		if (DENIED.has(res.status)) return deny(await detail(res));
		if (!body) return fail();

		let parsed: { serverAt: number; closes: number; current: [number, string]; next: [number, string] };
		try {
			parsed = {
				serverAt: parseServerTime(body.server_now),
				closes: parseServerTime(body.closes_at),
				current: [parseServerTime(body.current.ends_at), String(body.current.code)],
				next: [parseServerTime(body.next.ends_at), String(body.next.code)]
			};
		} catch {
			console.warn('출석코드 응답의 시각을 읽지 못했습니다.', body);
			return fail();
		}
		adopt(t1 - t0, offsetFrom(t0, parsed.serverAt, t1));
		if (offset === null) return fail(); // 믿을 만한 왕복이 아직 없다
		if (snapshot.status === 'closed') emit({ ...snapshot, status: 'open' }); // 다시 열렸다
		closesAt = parsed.closes;
		slots.set(...parsed.current);
		slots.set(...parsed.next);
		stale = false;
		failures = 0;
		const shown = render();
		// 경계 바로 뒤라 서버가 아직 앞 칸이었으면, 지금 칸 다음 코드가 없다. 조금 뒤 다시 받아 채운다
		if (shown !== null && ![...slots.keys()].some((endsAt) => endsAt > shown)) schedule(TOP_UP_DELAY);
	}

	async function detail(res: Response): Promise<string> {
		if (res.status === 401) return DENIED_MESSAGE;
		try {
			const body = (await res.json()) as { detail?: unknown };
			if (typeof body.detail === 'string') return body.detail;
		} catch {
			// 본문이 없거나 JSON이 아니다
		}
		return DENIED_MESSAGE;
	}

	function onVisible() {
		if (doc?.visibilityState !== 'visible') return;
		render(); // 숨은 동안 늦어진 타이머를 기다리지 않는다
		void load();
	}

	doc?.addEventListener('visibilitychange', onVisible);
	void load();

	return {
		subscribe(listener: (s: AttendanceCodeSnapshot) => void): () => void {
			listeners.add(listener);
			listener(snapshot);
			return () => listeners.delete(listener);
		},
		/** 서버 시각 추정(ms). 남은 시간 막대·원을 그릴 때 쓴다. */
		serverNow,
		/** 지금 다시 받는다(연장·다시 받기 알림을 받았을 때). 닫혀 있어도 받아서, 다시 열렸으면 다시 보인다. */
		refresh() {
			void load(true);
		},
		stop() {
			stopped = true;
			clearTimers();
			loading?.abort();
			doc?.removeEventListener('visibilitychange', onVisible);
			listeners.clear();
		}
	};
}

export type AttendanceCode = ReturnType<typeof connectAttendanceCode>;
