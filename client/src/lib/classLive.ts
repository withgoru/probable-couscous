/**
 * 수업 연결(`/ws/class/{강좌}`, 002 T014). 교수 수업 화면, 프로젝터, 학생 수업 화면이 함께 쓴다.
 *
 * 진실은 서버 DB다(C13). 이 모듈은 다음을 따른다(plan "놓친 것 채우기").
 *  1. 연결하면 서버가 구독을 먼저 걸고 `ready`를 보낸다.
 *  2. 그 뒤 HTTP로 회차 목록과 상태(`…/live`)를 통째로 받는다.
 *  3. 발행은 받은 `version`의 바로 다음 것만 적용한다. 건너뛴 것이 있으면 통째로 다시 받는다.
 *
 * 다시 받는 때: 다시 연결했을 때, `resync`를 받았을 때, 화면이 다시 보였을 때(`visibilitychange`), 회차 상태가 바뀌었을 때.
 * 끊기면 1·2·5·10초 간격으로 다시 붙고, 그동안 마지막 상태는 그대로 둔다(C12).
 * `goodbye`를 받거나 4403으로 닫히면(명단에서 빠짐, 로그인 끊김) 다시 붙지 않는다.
 */

import type { Position } from './deckBridge';

export type Role = 'professor' | 'projector' | 'student';
export type LiveItem = {
	id: number;
	body: string | null;
	url: string | null;
	created_at: string;
	retracted_at?: string | null; // 교수에게만 온다
};
export type LiveState = {
	session: {
		id: number;
		title: string;
		status: 'scheduled' | 'live' | 'ended';
		version: number;
		/** 마지막으로 시작(또는 이어서)한 시각. 교수 화면의 경과 시간(AC12). */
		started_at?: string | null;
	};
	/** `public`: 학생에게 공개한 묶음(AC47). 공개 묶음은 처음부터 끝까지 넘겨 본다. */
	deck: LiveDeck | null;
	current: Position;
	items: LiveItem[];
};
export type LiveDeck = { id: number; slide_count: number; available: boolean; public: boolean };
export type ClassStatus = 'connecting' | 'live' | 'reconnecting' | 'gone';
export type ClassSnapshot = {
	status: ClassStatus;
	liveSessionId: number | null;
	state: LiveState | null;
	presence: { follow: number; browse: number } | null;
	goodbye: { reason: string; message: string } | null;
	loadError: string | null;
	/** 처음 불러오기를 마쳤는가. 거짓이면 아직 "수업 없음"인지 모른다. */
	loaded: boolean;
};
export type GotoFailure = { reason: string; message: string };

type Where = { protocol: string; host: string };
type Doc = Pick<EventTarget, 'addEventListener' | 'removeEventListener'> & { visibilityState: string };
type Options = {
	role: Role;
	/** 정한 회차(다시 보기). 없으면 진행 중인 회차를 따라간다. */
	sessionId?: number | null;
	fetchFn?: typeof fetch;
	location?: Where;
	Socket?: typeof WebSocket;
	document?: Doc;
};
type Incoming = Record<string, unknown> & { type: string };

export const RETRY_DELAYS = [1_000, 2_000, 5_000, 10_000];
export const GOODBYE_CODE = 4403;
const OFFLINE: GotoFailure = { reason: 'offline', message: '연결이 끊겼습니다. 다시 연결되면 넘겨 주세요.' };

export function classSocketUrl(classroomId: number, role: Role, where: Where): string {
	const scheme = where.protocol === 'https:' ? 'wss' : 'ws';
	return `${scheme}://${where.host}/ws/class/${classroomId}${role === 'projector' ? '?role=projector' : ''}`;
}

const isPosition = (value: unknown): value is Position =>
	!!value &&
	typeof value === 'object' &&
	Number.isInteger((value as Position).slide) &&
	Number.isInteger((value as Position).click);

async function getJson<T>(fetchFn: typeof fetch, url: string): Promise<T> {
	const res = await fetchFn(url, { credentials: 'same-origin', headers: { Accept: 'application/json' } });
	if (!res.ok) {
		let detail: unknown;
		try {
			detail = ((await res.json()) as { detail?: unknown }).detail;
		} catch {
			// 본문이 JSON이 아니면 상태 번호만 쓴다
		}
		throw new Error(typeof detail === 'string' ? detail : `불러오지 못했습니다 (${res.status})`);
	}
	return (await res.json()) as T;
}

/** 연결을 연다. 화면을 떠날 때 `stop()`을 부른다. */
export function connectClass(classroomId: number, options: Options) {
	const { role } = options;
	const fetchFn = options.fetchFn ?? fetch;
	const where = options.location ?? window.location;
	const Socket = options.Socket ?? WebSocket;
	const doc = options.document ?? document;

	let snapshot: ClassSnapshot = {
		status: 'connecting',
		liveSessionId: null,
		state: null,
		presence: null,
		goodbye: null,
		loadError: null,
		loaded: false
	};
	const listeners = new Set<(s: ClassSnapshot) => void>();
	let socket: WebSocket | null = null;
	let ready = false;
	let timer: ReturnType<typeof setTimeout> | null = null;
	let reloadTimer: ReturnType<typeof setTimeout> | null = null;
	let failures = 0;
	let loadFailures = 0;
	let stopped = false;
	let loading: Promise<void> | null = null;
	let again = false; // 불러오는 동안 다시 받으라는 신호가 왔다
	let queued: Incoming[] = []; // 불러오는 동안 온 발행
	let mode: 'follow' | 'browse' = 'follow';
	let nextReq = 0;
	const pending = new Map<string, { resolve: (v: number) => void; reject: (f: GotoFailure) => void }>();

	function update(next: Partial<ClassSnapshot>) {
		snapshot = { ...snapshot, ...next };
		for (const listener of listeners) listener(snapshot);
	}

	function setState(state: LiveState) {
		update({ state });
	}

	async function fetchAll() {
		const list = await getJson<{ live_session_id: number | null }>(fetchFn, `/api/class/${classroomId}/sessions`);
		const focus = options.sessionId ?? list.live_session_id;
		const state =
			focus == null ? null : await getJson<LiveState>(fetchFn, `/api/class/${classroomId}/sessions/${focus}/live`);
		return { liveSessionId: list.live_session_id, state };
	}

	function reload() {
		if (stopped) return;
		if (loading) {
			again = true;
			return;
		}
		if (reloadTimer) clearTimeout(reloadTimer);
		reloadTimer = null;
		loading = (async () => {
			try {
				const { liveSessionId, state } = await fetchAll();
				if (stopped) return;
				loadFailures = 0;
				update({ liveSessionId, state, loadError: null, loaded: true });
				const events = queued;
				queued = [];
				for (const event of events) apply(event);
			} catch (err) {
				if (stopped) return;
				update({ loadError: err instanceof Error ? err.message : '불러오지 못했습니다.' });
				const wait = RETRY_DELAYS[Math.min(loadFailures, RETRY_DELAYS.length - 1)];
				loadFailures += 1;
				reloadTimer = setTimeout(reload, wait);
			} finally {
				loading = null;
				if (again) {
					again = false;
					reload();
				}
			}
		})();
	}

	/** 발행 하나를 적용한다. 바로 다음 version이면 적용, 건너뛰었으면 다시 받기, 지난 것이면 무시. */
	function apply(event: Incoming) {
		const state = snapshot.state;
		const sessionEvent =
			event.type === 'position' ||
			event.type === 'deck.updated' ||
			event.type === 'item.created' ||
			event.type === 'item.retracted';
		if (!sessionEvent || !state || event.session_id !== state.session.id) return;
		const version = event.version;
		if (typeof version !== 'number' || version <= state.session.version) return;
		if (version > state.session.version + 1) return reload(); // 놓친 것이 있다
		const session = { ...state.session, version };
		if (event.type === 'position') {
			if (!isPosition(event.current)) return;
			setState({ ...state, session, current: { ...event.current } });
		} else if (event.type === 'deck.updated') {
			// 교수가 공개·비공개를 바꿨다(AC48). 묶음이 그대로라 위치는 둔다
			const deck = event.deck as LiveDeck | undefined;
			if (!deck || typeof deck.id !== 'number' || typeof deck.public !== 'boolean') return reload();
			setState({ ...state, session, deck: { ...deck } });
		} else if (role === 'professor') {
			reload(); // 교수 목록은 거둔 시각까지 보여 주므로 다시 받는다
		} else if (event.type === 'item.created') {
			const item = event.item as LiveItem | undefined;
			if (!item || typeof item.id !== 'number') return;
			setState({ ...state, session, items: [...state.items, item] });
		} else {
			setState({ ...state, session, items: state.items.filter((i) => i.id !== event.item_id) });
		}
	}

	function onEvent(event: Incoming) {
		switch (event.type) {
			case 'ready':
				ready = true;
				failures = 0;
				update({ status: 'live' });
				if (role === 'student' && mode !== 'follow') send({ type: 'mode', mode });
				reload();
				return;
			case 'resync':
			case 'session.updated':
				return reload();
			case 'presence':
				if (typeof event.follow === 'number' && typeof event.browse === 'number')
					update({ presence: { follow: event.follow, browse: event.browse } });
				return;
			case 'goodbye':
				update({ goodbye: { reason: String(event.reason), message: String(event.message) }, status: 'gone' });
				return;
			case 'ack':
			case 'error': {
				const waiter = typeof event.req === 'string' ? pending.get(event.req) : undefined;
				if (!waiter) return;
				pending.delete(event.req as string);
				if (event.type === 'ack') waiter.resolve(Number(event.version));
				else waiter.reject({ reason: String(event.reason), message: String(event.message) });
				return;
			}
			default:
				if (loading) queued.push(event);
				else apply(event);
		}
	}

	function send(message: Record<string, unknown>): boolean {
		if (!socket || !ready || socket.readyState !== 1) return false;
		socket.send(JSON.stringify(message));
		return true;
	}

	function failPending() {
		for (const waiter of pending.values()) waiter.reject(OFFLINE);
		pending.clear();
	}

	function open() {
		if (stopped) return;
		timer = null;
		const s = new Socket(classSocketUrl(classroomId, role, where));
		socket = s;
		ready = false;
		s.onmessage = (message) => {
			let event: unknown;
			try {
				event = JSON.parse(String(message.data));
			} catch {
				return;
			}
			if (event && typeof event === 'object' && typeof (event as Incoming).type === 'string') onEvent(event as Incoming);
		};
		s.onclose = (closing) => {
			if (stopped || socket !== s) return;
			socket = null;
			ready = false;
			failPending();
			if (closing.code === GOODBYE_CODE || snapshot.goodbye) {
				update({ status: 'gone' });
				return; // 내보냈다: 다시 붙지 않는다
			}
			update({ status: 'reconnecting' });
			const wait = RETRY_DELAYS[Math.min(failures, RETRY_DELAYS.length - 1)];
			failures += 1;
			timer = setTimeout(open, wait);
		};
	}

	function onVisible() {
		if (stopped || doc.visibilityState !== 'visible' || snapshot.status === 'gone') return;
		if (socket) return reload();
		if (timer) clearTimeout(timer);
		open(); // 끊긴 채였다면 기다리지 않고 바로 붙는다(붙으면 ready에서 다시 받는다)
	}

	doc.addEventListener('visibilitychange', onVisible);
	open();

	return {
		subscribe(listener: (s: ClassSnapshot) => void): () => void {
			listeners.add(listener);
			listener(snapshot);
			return () => listeners.delete(listener);
		},
		/** 교수 넘기기. 서버가 DB에 쓴 뒤 `ack`의 version으로 끝나고, 거절하면 그 안내로 실패한다. */
		goto(position: Position): Promise<number> {
			const state = snapshot.state;
			if (!state) return Promise.reject(OFFLINE);
			nextReq += 1;
			const req = `g${nextReq}`;
			const message = { type: 'goto', session_id: state.session.id, slide: position.slide, click: position.click, req };
			return new Promise<number>((resolve, reject) => {
				if (!send(message)) return reject(OFFLINE);
				pending.set(req, { resolve, reject });
			});
		},
		/** 학생의 따라가기 상태. 다시 붙으면 다시 알린다(서버는 새 연결을 따라가는 중으로 센다). */
		setMode(next: 'follow' | 'browse') {
			mode = next;
			if (role === 'student') send({ type: 'mode', mode });
		},
		reload,
		stop() {
			stopped = true;
			doc.removeEventListener('visibilitychange', onVisible);
			if (timer) clearTimeout(timer);
			if (reloadTimer) clearTimeout(reloadTimer);
			failPending();
			const s = socket;
			socket = null;
			s?.close();
			listeners.clear();
		}
	};
}

export type ClassLive = ReturnType<typeof connectClass>;
