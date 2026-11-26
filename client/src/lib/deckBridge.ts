/**
 * 슬라이드 iframe과의 다리(002 plan "iframe과의 대화", T014).
 *
 * 슬라이드 묶음 안의 애드온(`slides-template/setup/root.ts`)과 `postMessage`로만 대화한다. 연결·인증은 하지 않는다.
 * - 슬라이드 → 화면: `deck:ready{total}`, `deck:moved{slide, click, clicksTotal, total}`, `deck:intent{next|prev}`
 * - 화면 → 슬라이드: `deck:goto{slide, click}`, `deck:mode{mode}`
 *
 * 같은 출처이고 그 iframe 창에서 온 메시지만 받는다. 준비(`deck:ready`) 전에 받은 지시는 마지막 것만 기억했다가
 * 준비되면 보낸다. iframe이 다시 뜨면(새 `deck:ready`) 기억한 지시를 다시 보낸다.
 * 따라가기를 풀지, 범위 안인지 같은 판단은 하지 않는다. 그것은 이 다리를 쓰는 화면의 일이다.
 */

export type Position = { slide: number; click: number };
export type DeckMode = 'follow' | 'browse' | 'present';
export type Direction = 'next' | 'prev';
export type DeckSnapshot = {
	ready: boolean;
	total: number | null;
	position: Position | null;
	clicksTotal: number | null;
};

type Listener = (snapshot: DeckSnapshot) => void;
type Options = {
	origin?: string;
	target?: Pick<EventTarget, 'addEventListener' | 'removeEventListener'>;
	onIntent?: (direction: Direction) => void;
};

const whole = (value: unknown, min: number): value is number =>
	typeof value === 'number' && Number.isInteger(value) && value >= min;

/** `frame()`은 지금 iframe의 창(`iframe.contentWindow`). iframe을 바꿔 끼워도 다리는 그대로 쓴다. */
export function connectDeck(frame: () => Window | null, options: Options = {}) {
	const origin = options.origin ?? window.location.origin;
	const target = options.target ?? window;
	let snapshot: DeckSnapshot = { ready: false, total: null, position: null, clicksTotal: null };
	const listeners = new Set<Listener>();

	let mode: DeckMode | null = null;
	let lastGoto: Position | null = null;

	function update(next: Partial<DeckSnapshot>) {
		snapshot = { ...snapshot, ...next };
		for (const listener of listeners) listener(snapshot);
	}

	function post(message: Record<string, unknown>) {
		if (snapshot.ready) frame()?.postMessage(message, origin);
	}

	function replay() {
		if (mode) post({ type: 'deck:mode', mode });
		if (lastGoto) post({ type: 'deck:goto', ...lastGoto });
	}

	function onMessage(event: Event) {
		const { origin: from, source, data } = event as MessageEvent;
		const win = frame();
		if (from !== origin || !win || source !== win) return;
		if (!data || typeof data !== 'object') return;
		const message = data as Record<string, unknown>;
		if (message.type === 'deck:ready' && whole(message.total, 1)) {
			update({ ready: true, total: message.total });
			replay();
		} else if (message.type === 'deck:moved' && whole(message.slide, 1) && whole(message.click, 0)) {
			update({
				position: { slide: message.slide, click: message.click },
				clicksTotal: whole(message.clicksTotal, 0) ? message.clicksTotal : snapshot.clicksTotal,
				total: whole(message.total, 1) ? message.total : snapshot.total
			});
		} else if (message.type === 'deck:intent' && (message.direction === 'next' || message.direction === 'prev')) {
			options.onIntent?.(message.direction);
		}
	}

	target.addEventListener('message', onMessage);

	return {
		subscribe(listener: Listener): () => void {
			listeners.add(listener);
			listener(snapshot);
			return () => listeners.delete(listener);
		},
		goto(position: Position) {
			lastGoto = { slide: position.slide, click: position.click };
			post({ type: 'deck:goto', ...lastGoto });
		},
		setMode(next: DeckMode) {
			mode = next;
			post({ type: 'deck:mode', mode });
		},
		stop() {
			target.removeEventListener('message', onMessage);
			listeners.clear();
		}
	};
}

export type DeckBridge = ReturnType<typeof connectDeck>;
