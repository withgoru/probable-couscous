/**
 * 교수 관리 화면의 실시간 연결(`/ws/admin/{강좌}`, T023).
 *
 * 서버는 "무엇이 바뀌었다"만 번호와 함께 보낸다. 화면은 받으면 HTTP로 목록을 다시 불러온다.
 * 연결할 때마다 서버가 구독을 먼저 걸고 `ready`를 보내므로, `ready`를 받은 뒤 목록을 불러오면 그 사이 변화도 놓치지 않는다.
 * 끊기면 간격을 늘려 가며 다시 연결하고, 다시 연결되면 `ready`로 목록을 새로 받는다(C13).
 */

export type AdminEvent = { type: string; id?: number; status?: string };
export type LiveStatus = 'live' | 'reconnecting' | 'never-connected';
export type AdminHandlers = {
	onReady: () => void;
	onEvent: (event: AdminEvent) => void;
	onStatus: (status: LiveStatus) => void;
};
type Where = { protocol: string; host: string };

export const RETRY_DELAYS = [1_000, 2_000, 5_000, 10_000];

export function adminSocketUrl(classroomId: number, where: Where): string {
	return `${where.protocol === 'https:' ? 'wss' : 'ws'}://${where.host}/ws/admin/${classroomId}`;
}

/** 연결을 연다. 돌려준 함수를 부르면 닫고 다시 연결하지 않는다(화면을 떠날 때). */
export function connectAdmin(
	classroomId: number,
	handlers: AdminHandlers,
	options: { location?: Where; Socket?: typeof WebSocket } = {}
): () => void {
	const where = options.location ?? window.location;
	const Socket = options.Socket ?? WebSocket;
	let socket: WebSocket | null = null;
	let timer: ReturnType<typeof setTimeout> | null = null;
	let failures = 0;
	let everReady = false;
	let stopped = false;

	function open() {
		const s = new Socket(adminSocketUrl(classroomId, where));
		socket = s;
		let ready = false;
		s.onmessage = (message) => {
			let event: AdminEvent;
			try {
				event = JSON.parse(String(message.data));
			} catch {
				return;
			}
			if (!event || typeof event.type !== 'string') return;
			if (event.type === 'ready') {
				ready = true;
				everReady = true;
				failures = 0;
				handlers.onStatus('live');
				handlers.onReady();
			} else {
				handlers.onEvent(event);
			}
		};
		s.onclose = () => {
			if (stopped || socket !== s) return;
			socket = null;
			if (!ready && !everReady && failures === 0) handlers.onStatus('never-connected');
			handlers.onStatus('reconnecting');
			const wait = RETRY_DELAYS[Math.min(failures, RETRY_DELAYS.length - 1)];
			failures += 1;
			timer = setTimeout(open, wait);
		};
	}

	open();
	return () => {
		stopped = true;
		if (timer) clearTimeout(timer);
		socket?.close();
		socket = null;
	};
}
