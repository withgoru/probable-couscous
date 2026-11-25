import { describe, expect, it, vi } from 'vitest';
import { connectDeck, type DeckSnapshot } from './deckBridge';

const ORIGIN = 'http://localhost:8000';

/** 슬라이드 iframe(애드온)을 흉내 낸다. 부모가 보낸 것을 모으고, 애드온이 보낸 것처럼 메시지를 일으킨다. */
function setup() {
	const target = new EventTarget();
	const frame = { postMessage: vi.fn() };
	let current: typeof frame | null = frame;
	const snapshots: DeckSnapshot[] = [];
	const intents: string[] = [];
	const deck = connectDeck(() => current as unknown as Window | null, {
		origin: ORIGIN,
		target,
		onIntent: (direction) => intents.push(direction)
	});
	deck.subscribe((s) => snapshots.push(s));
	const fromDeck = (data: unknown, opts: { origin?: string; source?: unknown } = {}) => {
		const event = Object.assign(new Event('message'), {
			data,
			origin: opts.origin ?? ORIGIN,
			source: 'source' in opts ? opts.source : current
		});
		target.dispatchEvent(event);
	};
	const sent = () => frame.postMessage.mock.calls.map((c) => c[0]);
	return {
		deck,
		frame,
		fromDeck,
		sent,
		intents,
		now: () => snapshots[snapshots.length - 1],
		swap: (next: typeof frame | null) => (current = next)
	};
}

describe('슬라이드에서 오는 메시지', () => {
	it('처음에는 준비 전이다', () => {
		expect(setup().now()).toEqual({ ready: false, total: null, position: null, clicksTotal: null });
	});

	it('deck:ready와 deck:moved를 상태로 바꾼다', () => {
		const { fromDeck, now } = setup();
		fromDeck({ type: 'deck:ready', total: 4 });
		expect(now()).toEqual({ ready: true, total: 4, position: null, clicksTotal: null });
		fromDeck({ type: 'deck:moved', slide: 2, click: 1, clicksTotal: 3, total: 4 });
		expect(now()).toEqual({ ready: true, total: 4, position: { slide: 2, click: 1 }, clicksTotal: 3 });
	});

	it('deck:intent를 방향으로 알린다 (AC26)', () => {
		const { fromDeck, intents } = setup();
		fromDeck({ type: 'deck:intent', direction: 'next' });
		fromDeck({ type: 'deck:intent', direction: 'prev' });
		fromDeck({ type: 'deck:intent', direction: 'sideways' });
		expect(intents).toEqual(['next', 'prev']);
	});

	it('다른 출처나 다른 창에서 온 메시지는 무시한다', () => {
		const { fromDeck, now, intents } = setup();
		fromDeck({ type: 'deck:ready', total: 4 }, { origin: 'https://evil.example' });
		fromDeck({ type: 'deck:ready', total: 4 }, { source: { postMessage() {} } });
		fromDeck({ type: 'deck:intent', direction: 'next' }, { source: null });
		expect(now().ready).toBe(false);
		expect(intents).toEqual([]);
	});

	it('모양이 맞지 않는 메시지는 무시한다', () => {
		const { fromDeck, now } = setup();
		fromDeck({ type: 'deck:ready', total: 4 });
		for (const data of [null, 'deck:moved', { type: 'deck:moved', slide: '2', click: 0 }, { type: 'deck:moved', slide: 0, click: 0 }, { type: 'deck:ready', total: -1 }]) {
			fromDeck(data);
		}
		expect(now()).toEqual({ ready: true, total: 4, position: null, clicksTotal: null });
	});
});

describe('슬라이드로 보내는 지시', () => {
	it('준비되면 goto·limit·mode를 같은 출처로만 보낸다', () => {
		const { deck, fromDeck, frame, sent } = setup();
		fromDeck({ type: 'deck:ready', total: 4 });
		deck.setMode('follow');
		deck.setLimit({ slide: 3, click: 1 });
		deck.goto({ slide: 2, click: 0 });
		expect(sent()).toEqual([
			{ type: 'deck:mode', mode: 'follow' },
			{ type: 'deck:limit', limit: { slide: 3, click: 1 } },
			{ type: 'deck:goto', slide: 2, click: 0 }
		]);
		expect(frame.postMessage.mock.calls.every((c) => c[1] === ORIGIN)).toBe(true);
	});

	it('준비 전의 지시는 마지막 것만 기억했다가 준비되면 보낸다', () => {
		const { deck, fromDeck, sent } = setup();
		deck.goto({ slide: 2, click: 0 });
		deck.goto({ slide: 3, click: 1 });
		deck.setLimit(null);
		deck.setMode('present');
		expect(sent()).toEqual([]);
		fromDeck({ type: 'deck:ready', total: 4 });
		expect(sent()).toEqual([
			{ type: 'deck:mode', mode: 'present' },
			{ type: 'deck:limit', limit: null },
			{ type: 'deck:goto', slide: 3, click: 1 }
		]);
	});

	it('iframe이 다시 뜨면(새 deck:ready) 기억한 지시를 다시 보낸다', () => {
		const { deck, fromDeck, sent } = setup();
		fromDeck({ type: 'deck:ready', total: 4 });
		deck.setLimit({ slide: 2, click: 0 });
		deck.goto({ slide: 2, click: 0 });
		fromDeck({ type: 'deck:ready', total: 4 });
		expect(sent().slice(2)).toEqual([
			{ type: 'deck:limit', limit: { slide: 2, click: 0 } },
			{ type: 'deck:goto', slide: 2, click: 0 }
		]);
	});

	it('iframe이 없으면 보내지 않고 실패하지도 않는다', () => {
		const { deck, fromDeck, swap, frame } = setup();
		fromDeck({ type: 'deck:ready', total: 4 });
		swap(null);
		expect(() => deck.goto({ slide: 2, click: 0 })).not.toThrow();
		expect(frame.postMessage).not.toHaveBeenCalled();
	});
});

describe('정리', () => {
	it('멈추면 메시지를 더 듣지 않는다', () => {
		const { deck, fromDeck, now, intents } = setup();
		deck.stop();
		fromDeck({ type: 'deck:ready', total: 4 });
		fromDeck({ type: 'deck:intent', direction: 'next' });
		expect(now().ready).toBe(false);
		expect(intents).toEqual([]);
	});
});
