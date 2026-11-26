// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ClassSnapshot, LiveState } from '#lib/classLive.js';
import type { DeckSnapshot } from '#lib/deckBridge.js';

// 수업 연결과 슬라이드 다리는 흉내 낸다(교수 수업 화면 테스트와 같은 방식)
const live = vi.hoisted(() => ({ listener: null as ((s: unknown) => void) | null, goto: vi.fn(), stop: vi.fn(), options: null as unknown }));
vi.mock('#lib/classLive.js', () => ({
	connectClass: (_id: number, options: unknown) => {
		live.options = options;
		return {
			subscribe: (fn: (s: unknown) => void) => {
				live.listener = fn;
				return () => {};
			},
			goto: live.goto,
			setMode: vi.fn(),
			reload: vi.fn(),
			stop: live.stop
		};
	}
}));
type FakeDeck = { listener: ((s: DeckSnapshot) => void) | null; options: { onIntent?: unknown }; goto: ReturnType<typeof vi.fn>; setMode: ReturnType<typeof vi.fn>; stop: ReturnType<typeof vi.fn> };
const decks = vi.hoisted(() => ({ all: [] as FakeDeck[] }));
vi.mock('#lib/deckBridge.js', () => ({
	connectDeck: (_frame: unknown, options: { onIntent?: unknown } = {}) => {
		const deck: FakeDeck = { listener: null, options, goto: vi.fn(), setMode: vi.fn(), stop: vi.fn() };
		decks.all.push(deck);
		return {
			subscribe: (fn: (s: DeckSnapshot) => void) => {
				deck.listener = fn;
				return () => {};
			},
			goto: deck.goto,
			setMode: deck.setMode,
			stop: deck.stop
		};
	}
}));

import ProjectorPage from './+page.svelte';

const CLASSROOM = { id: 7, name: '웹 프로그래밍', section_name: null, status: 'active', student_count: 40, session_count: 3, created_at: 'x' } as const;
const STATE: LiveState = {
	session: { id: 5, title: '3주차 1회차', status: 'live', version: 3, started_at: '2026-03-04T05:00:00+00:00' },
	deck: { id: 9, slide_count: 4, available: true, public: false },
	current: { slide: 2, click: 1 },
	items: []
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

async function server(s: ClassSnapshot) {
	await act(() => live.listener?.(s));
}
async function open(s: ClassSnapshot = snapshot()) {
	render(ProjectorPage, { params: { id: '7' }, data: { me: null, classroom: CLASSROOM, notice: null } });
	await server(s);
}
const deck = () => decks.all[0];

beforeEach(() => {
	decks.all = [];
	live.listener = null;
	live.goto.mockReset();
	live.stop.mockReset();
});
afterEach(() => {
	cleanup();
	vi.useRealTimers();
	// 테스트가 넣은 전체 화면 API를 치운다(다음 테스트로 새지 않게)
	delete (document.documentElement as { requestFullscreen?: unknown }).requestFullscreen;
	delete (document as { exitFullscreen?: unknown }).exitFullscreen;
	Object.defineProperty(document, 'fullscreenElement', { configurable: true, get: () => null });
});

describe('슬라이드만 화면 가득 (AC19)', () => {
	it('프로젝터로 연결하고 슬라이드 하나만 보인다', async () => {
		await open();
		expect(live.options).toMatchObject({ role: 'projector' });
		const frame = screen.getByTitle('슬라이드') as HTMLIFrameElement;
		expect(frame.getAttribute('src')).toBe('/decks/9/');
		expect(document.querySelectorAll('iframe')).toHaveLength(1); // 다음 슬라이드 미리보기 없음
		expect(screen.queryByText(/노트/)).toBeNull();
		expect(screen.queryByRole('button', { name: '다음' })).toBeNull();
		expect(screen.queryByRole('button', { name: '이전' })).toBeNull();
		expect(document.title).toContain('3주차 1회차');
		// 화면 낭독기용 제목은 있지만 보이지 않는다(슬라이드 위에 얹지 않는다)
		expect(screen.getByRole('heading', { level: 1, name: '3주차 1회차 · 프로젝터 화면' }).className).toContain('sr-only');
	});

	it('16:9 맞춤 상자에 슬라이드를 얹는다', async () => {
		await open();
		const box = (screen.getByTitle('슬라이드') as HTMLElement).parentElement as HTMLElement;
		expect(box.className).toContain('aspect-video');
	});

	it('전체 화면 버튼과 F 키로 전체 화면이 된다', async () => {
		const request = vi.fn(() => Promise.resolve());
		document.documentElement.requestFullscreen = request;
		await open();
		await fireEvent.click(screen.getByRole('button', { name: '전체 화면' }));
		expect(request).toHaveBeenCalledTimes(1);
		await fireEvent.keyDown(window, { key: 'f' });
		await fireEvent.keyDown(window, { key: 'F' });
		expect(request).toHaveBeenCalledTimes(3);
	});

	it('전체 화면이면 F 키로 빠져나오고 전체 화면 버튼을 숨긴다', async () => {
		const exit = vi.fn(() => Promise.resolve());
		document.exitFullscreen = exit;
		await open();
		Object.defineProperty(document, 'fullscreenElement', { configurable: true, get: () => document.documentElement });
		await act(() => document.dispatchEvent(new Event('fullscreenchange')));
		expect(screen.queryByRole('button', { name: '전체 화면' })).toBeNull();
		await fireEvent.keyDown(window, { key: 'f' });
		expect(exit).toHaveBeenCalled();
		Object.defineProperty(document, 'fullscreenElement', { configurable: true, get: () => null });
		await act(() => document.dispatchEvent(new Event('fullscreenchange')));
		expect(screen.getByRole('button', { name: '전체 화면' })).toBeTruthy();
	});

	it('F 키는 다른 키를 함께 누르거나(Ctrl+F 찾기) 길게 누르면 받지 않고, 받으면 브라우저 기본 동작을 막는다', async () => {
		const request = vi.fn(() => Promise.resolve());
		document.documentElement.requestFullscreen = request;
		await open();
		for (const mod of ['ctrlKey', 'metaKey', 'altKey']) await fireEvent.keyDown(window, { key: 'f', [mod]: true });
		await fireEvent.keyDown(window, { key: 'f', repeat: true });
		expect(request).not.toHaveBeenCalled();
		const event = new KeyboardEvent('keydown', { key: 'f', cancelable: true });
		window.dispatchEvent(event);
		expect(event.defaultPrevented).toBe(true);
		expect(request).toHaveBeenCalledTimes(1);
	});

	it('전체 화면을 켤 수 없으면 무엇을 하면 되는지 구석에 알린다', async () => {
		document.documentElement.requestFullscreen = vi.fn(() => Promise.reject(new Error('denied')));
		await open();
		await fireEvent.click(screen.getByRole('button', { name: '전체 화면' }));
		expect(await screen.findByText('전체 화면을 켤 수 없습니다. 브라우저의 전체 화면(F11)을 써 주세요.')).toBeTruthy();
	});

	it('전체 화면 버튼은 마우스를 움직이지 않으면 3초 뒤 숨고, 움직이거나 초점이 가면 다시 보인다', async () => {
		vi.useFakeTimers();
		await open();
		expect(screen.getByRole('button', { name: '전체 화면' })).toBeTruthy();
		await act(() => vi.advanceTimersByTime(3_000));
		expect(screen.queryByRole('button', { name: '전체 화면' })).toBeNull();
		await fireEvent.mouseMove(window);
		const button = screen.getByRole('button', { name: '전체 화면' });
		button.focus();
		await act(() => vi.advanceTimersByTime(10_000));
		expect(screen.getByRole('button', { name: '전체 화면' })).toBeTruthy(); // 초점이 있으면 숨기지 않는다
		await fireEvent.keyDown(window, { key: 'Tab' });
		expect(screen.getByRole('button', { name: '전체 화면' })).toBeTruthy();
	});

	it('전체 화면 버튼은 오른쪽 아래 구석에 있다(왼쪽 위에 얹지 않는다, AC21)', async () => {
		await open();
		const button = screen.getByRole('button', { name: '전체 화면' });
		expect(button.closest('[data-corner="bottom-right"]')).toBeTruthy();
	});
});

describe('교수 위치를 따라오고 직접 넘기지 않는다 (AC20)', () => {
	it('서버의 위치(슬라이드와 단계)로 슬라이드를 옮긴다', async () => {
		await open();
		expect(deck().setMode).toHaveBeenCalledWith('present');
		expect(deck().goto).toHaveBeenLastCalledWith({ slide: 2, click: 1 });
		await server(snapshot({ state: { ...STATE, current: { slide: 3, click: 0 } } }));
		expect(deck().goto).toHaveBeenLastCalledWith({ slide: 3, click: 0 });
		expect(decks.all).toHaveLength(1); // 위치가 바뀌어도 다리를 다시 만들지 않는다
	});

	it('iframe이 먼저 생기고 위치가 나중에 와도 그 위치로 간다', async () => {
		render(ProjectorPage, { params: { id: '7' }, data: { me: null, classroom: CLASSROOM, notice: null } });
		await server(snapshot({ state: { ...STATE, current: { slide: 1, click: 0 } } }));
		await server(snapshot({ state: { ...STATE, current: { slide: 3, click: 0 } } }));
		expect(deck().goto).toHaveBeenLastCalledWith({ slide: 3, click: 0 });
	});

	it('묶음이 바뀌면 예전 다리를 닫고 새 다리로 지금 위치를 보낸다', async () => {
		await open();
		const old = deck();
		await server(snapshot({ state: { ...STATE, deck: { id: 10, slide_count: 4, available: true, public: false } } }));
		expect(old.stop).toHaveBeenCalled();
		expect(decks.all).toHaveLength(2);
		expect(decks.all[1].goto).toHaveBeenLastCalledWith({ slide: 2, click: 1 });
		expect((screen.getByTitle('슬라이드') as HTMLIFrameElement).getAttribute('src')).toBe('/decks/10/');
	});

	it('키보드와 슬라이드 안의 넘기기로 넘겨지지 않는다', async () => {
		await open();
		for (const key of ['ArrowRight', 'ArrowLeft', ' ', 'PageDown', 'Enter']) await fireEvent.keyDown(window, { key });
		expect(live.goto).not.toHaveBeenCalled();
		expect(deck().options.onIntent).toBeUndefined();
	});

	it('슬라이드 iframe은 누르거나 초점을 받지 않는다(F 키가 늘 이 화면에 온다)', async () => {
		await open();
		const frame = screen.getByTitle('슬라이드') as HTMLIFrameElement;
		expect(frame.getAttribute('tabindex')).toBe('-1');
		expect(frame.className).toContain('pointer-events-none');
	});
});

describe('연결 끊김 표시 (AC21)', () => {
	it('평소에는 아무 표시도 없고, 끊기면 오른쪽 아래에만 작게 보인다', async () => {
		await open();
		const corner = document.querySelector('[data-connection-notice]') as HTMLElement;
		expect(corner.getAttribute('role')).toBe('status');
		expect(corner.textContent?.trim()).toBe('');
		await server(snapshot({ status: 'reconnecting' }));
		expect(corner.textContent).toContain('연결 끊김');
		expect(corner.closest('[data-corner="bottom-right"]')).toBeTruthy();
		expect(screen.getByTitle('슬라이드')).toBeTruthy(); // 슬라이드는 그대로
	});

	it('다시 붙으면 표시가 사라지고 교수의 현재 위치로 간다', async () => {
		await open();
		await server(snapshot({ status: 'reconnecting' }));
		await server(snapshot({ status: 'live', state: { ...STATE, current: { slide: 4, click: 0 } } }));
		expect((document.querySelector('[data-connection-notice]') as HTMLElement).textContent?.trim()).toBe('');
		expect(deck().goto).toHaveBeenLastCalledWith({ slide: 4, click: 0 });
	});
});

describe('슬라이드를 보일 수 없을 때', () => {
	it('불러오는 동안', async () => {
		render(ProjectorPage, { params: { id: '7' }, data: { me: null, classroom: CLASSROOM, notice: null } });
		await server(snapshot({ state: null, liveSessionId: null, loaded: false, status: 'connecting' }));
		expect(screen.getByText('수업을 불러오는 중…')).toBeTruthy();
	});

	it('처음 불러오기에 실패하면 이유와 할 일을 보인다', async () => {
		render(ProjectorPage, { params: { id: '7' }, data: { me: null, classroom: CLASSROOM, notice: null } });
		await server(snapshot({ state: null, liveSessionId: null, loaded: false, loadError: '불러오지 못했습니다 (500)' }));
		const alert = screen.getByRole('alert');
		expect(alert.textContent).toContain('불러오지 못했습니다 (500)');
		expect(alert.textContent).toContain('잠시 뒤 자동으로 다시 불러옵니다.');
	});

	it('보던 수업이 끝나면(진행 중인 회차가 사라지면) 수업이 끝났다고 알린다', async () => {
		await open();
		await server(snapshot({ state: null, liveSessionId: null }));
		expect(screen.getByText('수업이 끝났습니다.')).toBeTruthy();
		expect(screen.queryByText('진행 중인 수업이 없습니다.')).toBeNull();
		expect(deck().stop).toHaveBeenCalled();
	});

	it('진행 중인 수업이 없으면 그렇게 알린다', async () => {
		await open(snapshot({ state: null, liveSessionId: null }));
		expect(screen.getByText('진행 중인 수업이 없습니다.')).toBeTruthy();
	});

	it('수업이 끝나면 그렇게 알린다', async () => {
		await open(snapshot({ state: { ...STATE, session: { ...STATE.session, status: 'ended' } }, liveSessionId: null }));
		expect(screen.getByText('수업이 끝났습니다.')).toBeTruthy();
		expect(screen.queryByTitle('슬라이드')).toBeNull();
	});

	it('슬라이드가 없는 수업은 회차 이름을 크게 보인다', async () => {
		await open(snapshot({ state: { ...STATE, deck: null } }));
		expect(screen.getByText('3주차 1회차', { selector: 'p' })).toBeTruthy();
		expect(screen.queryByTitle('슬라이드')).toBeNull();
	});

	it('묶음이 열리지 않으면 그렇게 알린다', async () => {
		await open(snapshot({ state: { ...STATE, deck: { id: 9, slide_count: 4, available: false, public: false } } }));
		expect(screen.getByText('슬라이드를 열 수 없습니다.')).toBeTruthy();
	});

	it('권한이 없거나 없는 강좌면 안내만 보인다', () => {
		render(ProjectorPage, { params: { id: '7' }, data: { me: null, classroom: null, notice: { status: 403, message: '이 강좌를 볼 권한이 없습니다.' } } });
		expect(screen.getByRole('alert').textContent).toContain('이 강좌를 볼 권한이 없습니다.');
		expect(decks.all).toHaveLength(0);
	});

	it('화면을 떠나면 연결을 닫는다', async () => {
		await open();
		cleanup();
		expect(live.stop).toHaveBeenCalled();
	});
});
