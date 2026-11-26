// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ClassSnapshot, LiveState } from '#lib/classLive.js';
import type { DeckSnapshot, Position } from '#lib/deckBridge.js';

// 수업 연결은 흉내 낸다: 테스트가 서버 상태(스냅샷)를 넣고, 화면이 보낸 넘기기를 본다
const live = vi.hoisted(() => ({
	listener: null as ((s: unknown) => void) | null,
	goto: vi.fn(),
	stop: vi.fn(),
	reload: vi.fn(),
	options: null as unknown
}));
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
			reload: live.reload,
			stop: live.stop
		};
	}
}));
// 슬라이드 다리도 흉내 낸다. 첫 번째가 현재 슬라이드, 두 번째가 다음 슬라이드 미리보기다
type FakeDeck = { listener: ((s: DeckSnapshot) => void) | null; onIntent?: (d: 'next' | 'prev') => void; goto: ReturnType<typeof vi.fn>; setMode: ReturnType<typeof vi.fn>; setLimit: ReturnType<typeof vi.fn>; stop: ReturnType<typeof vi.fn> };
const decks = vi.hoisted(() => ({ all: [] as FakeDeck[] }));
vi.mock('#lib/deckBridge.js', () => ({
	connectDeck: (_frame: unknown, options: { onIntent?: (d: 'next' | 'prev') => void } = {}) => {
		const deck: FakeDeck = { listener: null, onIntent: options.onIntent, goto: vi.fn(), setMode: vi.fn(), setLimit: vi.fn(), stop: vi.fn() };
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
const nav = vi.hoisted(() => ({ goto: vi.fn(() => Promise.resolve()) }));
vi.mock('$app/navigation', () => nav);
const api = vi.hoisted(() => ({ fetchDeckNotes: vi.fn(), sendItem: vi.fn(), endSession: vi.fn() }));
vi.mock('#lib/api.js', async (original) => ({
	...(await original<object>()),
	fetchDeckNotes: api.fetchDeckNotes,
	sendItem: api.sendItem,
	endSession: api.endSession
}));

import LivePage from './+page.svelte';

const CLASSROOM = { id: 7, name: '웹 프로그래밍', section_name: '월수반', status: 'active', student_count: 40, session_count: 3, created_at: 'x' } as const;
const STATE: LiveState = {
	session: { id: 5, title: '3주차 1회차', status: 'live', version: 3, started_at: '2026-03-04T05:00:00+00:00' },
	deck: { id: 9, slide_count: 4, available: true },
	current: { slide: 2, click: 0 },
	furthest: { slide: 2, click: 0 },
	limit: { slide: 2, click: 0 },
	items: []
};
const NOTES = {
	deck_id: 9,
	slide_count: 4,
	slides: [
		{ no: 1, title: '인사', note: '노트 1: 인사하기' },
		{ no: 2, title: '목표', note: '노트 2: 하나씩 보여 준다' },
		{ no: 3, title: '실습', note: '' },
		{ no: 4, title: '정리', note: '노트 4' }
	]
};

const snapshot = (over: Partial<ClassSnapshot> = {}): ClassSnapshot => ({
	status: 'live',
	liveSessionId: 5,
	state: STATE,
	presence: { follow: 30, browse: 4 },
	goodbye: null,
	loadError: null,
	loaded: true,
	...over
});

async function server(s: ClassSnapshot) {
	await act(() => live.listener?.(s));
}
async function slides(deck: FakeDeck, s: Partial<DeckSnapshot>) {
	await act(() => deck.listener?.({ ready: true, total: 4, position: null, clicksTotal: null, ...s }));
}
const main = () => decks.all[0];
const preview = () => decks.all[1];

async function open(s: ClassSnapshot = snapshot()) {
	render(LivePage, { params: { id: '7' }, data: { me: null, classroom: CLASSROOM, notice: null } });
	await server(s);
	// 현재 슬라이드가 서버 위치에 그려졌다(2번, 단계 3개)
	if (s.state?.deck && main()) await slides(main(), { position: { ...s.state.current }, clicksTotal: 3 });
}

beforeEach(() => {
	decks.all = [];
	live.listener = null;
	live.goto.mockReset();
	live.stop.mockReset();
	live.reload.mockReset();
	api.sendItem.mockReset();
	api.endSession.mockReset();
	nav.goto.mockClear();
	api.fetchDeckNotes.mockReset();
	api.fetchDeckNotes.mockResolvedValue(NOTES);
	vi.setSystemTime(new Date('2026-03-04T05:12:30+00:00'));
});
afterEach(() => {
	cleanup();
	vi.useRealTimers();
});

describe('위쪽 줄 (AC12)', () => {
	it('강좌·회차 이름, 경과 시간, 접속 학생 수, 프로젝터 화면 열기, 수업 종료가 있다', async () => {
		await open();
		const top = screen.getByRole('banner');
		expect(top.textContent).toContain('웹 프로그래밍');
		expect(top.textContent).toContain('3주차 1회차');
		expect(top.textContent).toContain('경과 12분');
		expect(top.textContent).toContain('접속 34명');
		expect(screen.getByRole('button', { name: '프로젝터 화면 열기' })).toBeTruthy();
		expect(screen.getByRole('button', { name: '수업 종료' })).toBeTruthy();
		expect(document.title).toContain('3주차 1회차');
	});

	it('딱 한 시간이면 1시간 0분이다', async () => {
		vi.setSystemTime(new Date('2026-03-04T06:00:00+00:00'));
		await open();
		expect(screen.getByRole('banner').textContent).toContain('경과 1시간 0분');
	});

	it('한 시간이 넘으면 시간과 분으로 보인다', async () => {
		vi.setSystemTime(new Date('2026-03-04T06:05:00+00:00'));
		await open();
		expect(screen.getByRole('banner').textContent).toContain('경과 1시간 5분');
	});

	it('접속 수를 아직 모르면 숫자를 지어내지 않는다', async () => {
		await open(snapshot({ presence: null }));
		expect(screen.getByRole('banner').textContent).not.toContain('접속 0명');
	});

	it('프로젝터 화면 열기는 프로젝터 주소를 새 창으로 연다', async () => {
		const opened = vi.spyOn(window, 'open').mockReturnValue(null);
		await open();
		await fireEvent.click(screen.getByRole('button', { name: '프로젝터 화면 열기' }));
		expect(opened).toHaveBeenCalledWith('/courses/7/projector', 'classroom-projector');
	});

	it('교수 연결로 붙는다', async () => {
		await open();
		expect(live.options).toMatchObject({ role: 'professor' });
	});
});

describe('슬라이드, 다음 슬라이드, 노트 (AC13, AC16)', () => {
	it('현재 슬라이드와 다음 미리보기 iframe에 이름이 있고 묶음 주소를 연다', async () => {
		await open();
		const current = screen.getByTitle('현재 슬라이드') as HTMLIFrameElement;
		const next = screen.getByTitle('다음 슬라이드 미리보기') as HTMLIFrameElement;
		expect(current.getAttribute('src')).toBe('/decks/9/');
		expect(next.getAttribute('src')).toBe('/decks/9/');
	});

	it('현재 슬라이드는 서버 위치로, 미리보기는 다음 위치로 보낸다(다시 열어도 마지막 위치)', async () => {
		await open();
		expect(main().goto).toHaveBeenLastCalledWith({ slide: 2, click: 0 });
		expect(main().setMode).toHaveBeenCalledWith('present');
		expect(preview().goto).toHaveBeenLastCalledWith({ slide: 2, click: 1 }); // 남은 단계가 있다(AC14)
	});

	it('현재 슬라이드의 발표자 노트가 보인다', async () => {
		await open();
		await waitFor(() => expect(screen.getByText('노트 2: 하나씩 보여 준다')).toBeTruthy());
		expect(api.fetchDeckNotes).toHaveBeenCalledWith(7, 5);
	});

	it('노트가 빈 슬라이드는 그렇다고 알린다', async () => {
		await open(snapshot({ state: { ...STATE, current: { slide: 3, click: 0 } } }));
		expect(await screen.findByText('이 슬라이드에는 노트가 없습니다.')).toBeTruthy();
	});

	it('묶음이 바뀌면 늦게 온 예전 노트로 새 노트를 덮지 않는다', async () => {
		let oldAnswer: (n: typeof NOTES) => void = () => {};
		api.fetchDeckNotes.mockReset();
		api.fetchDeckNotes
			.mockReturnValueOnce(new Promise((r) => (oldAnswer = r)))
			.mockResolvedValueOnce({ ...NOTES, deck_id: 10, slides: NOTES.slides.map((s) => ({ ...s, note: `새 ${s.note}` })) });
		await open();
		await server(snapshot({ state: { ...STATE, deck: { id: 10, slide_count: 4, available: true } } }));
		await waitFor(() => expect(screen.getByText('새 노트 2: 하나씩 보여 준다')).toBeTruthy());
		await act(() => oldAnswer(NOTES));
		expect(screen.queryByText('노트 2: 하나씩 보여 준다')).toBeNull();
		expect(screen.getByText('새 노트 2: 하나씩 보여 준다')).toBeTruthy();
	});

	it('묶음이 바뀌면 늦게 실패한 예전 노트 요청으로 새 노트를 실패라고 하지 않는다', async () => {
		let oldFail: (e: Error) => void = () => {};
		api.fetchDeckNotes.mockReset();
		api.fetchDeckNotes
			.mockReturnValueOnce(new Promise((_, reject) => (oldFail = reject)))
			.mockResolvedValueOnce(NOTES);
		await open();
		await server(snapshot({ state: { ...STATE, deck: { id: 10, slide_count: 4, available: true } } }));
		await waitFor(() => expect(screen.getByText('노트 2: 하나씩 보여 준다')).toBeTruthy());
		await act(() => oldFail(new Error('늦은 실패')));
		expect(screen.queryByText('발표자 노트를 불러오지 못했습니다.')).toBeNull();
	});

	it('노트를 불러오지 못하면 알린다', async () => {
		api.fetchDeckNotes.mockRejectedValue(new Error('x'));
		await open();
		expect(await screen.findByText('발표자 노트를 불러오지 못했습니다.')).toBeTruthy();
	});

	it('노트 파일과 빌드의 슬라이드 수가 다르면 알린다', async () => {
		await open();
		await slides(main(), { total: 5, position: { slide: 2, click: 0 }, clicksTotal: 3 });
		const alert = await screen.findByRole('alert');
		expect(alert.textContent).toContain('노트(4장)와 슬라이드(5장)의 수가 다릅니다.');
		expect(alert.textContent).toContain('템플릿으로 다시 빌드해 올려 주세요.');
	});

	it('묶음이 없으면 슬라이드 대신 안내가 보이고 넘기기 버튼이 없다', async () => {
		await open(snapshot({ state: { ...STATE, deck: null } }));
		expect(screen.getByText('올린 슬라이드가 없습니다. 메시지·자료 보내기만 쓸 수 있습니다.')).toBeTruthy();
		expect(screen.queryByTitle('현재 슬라이드')).toBeNull();
		expect(screen.queryByRole('button', { name: '다음' })).toBeNull();
	});

	it('묶음이 열리지 않으면 슬라이드를 열 수 없다고 알린다', async () => {
		await open(snapshot({ state: { ...STATE, deck: { id: 9, slide_count: 4, available: false } } }));
		expect(screen.getByRole('alert').textContent).toContain('슬라이드를 열 수 없습니다. 메시지·자료 보내기는 계속 쓸 수 있습니다.'); // 오류 동작 문구
		expect(screen.queryByTitle('현재 슬라이드')).toBeNull();
	});
});

describe('넘기기 (AC13, AC14, AC17)', () => {
	it('다음은 남은 단계, 이전은 앞 단계로 서버에 넘긴다', async () => {
		live.goto.mockResolvedValue(4);
		await open();
		await fireEvent.click(screen.getByRole('button', { name: '다음' }));
		expect(live.goto).toHaveBeenCalledWith({ slide: 2, click: 1 });
		await waitFor(() => expect((screen.getByRole('button', { name: '다음' }) as HTMLButtonElement).disabled).toBe(false));
		await server(snapshot({ state: { ...STATE, current: { slide: 2, click: 1 } } }));
		await slides(main(), { position: { slide: 2, click: 1 }, clicksTotal: 3 });
		await fireEvent.click(screen.getByRole('button', { name: '이전' }));
		expect(live.goto).toHaveBeenLastCalledWith({ slide: 2, click: 0 });
	});

	it('마지막 단계면 다음 슬라이드의 첫 단계로 넘긴다', async () => {
		live.goto.mockResolvedValue(4);
		await open(snapshot({ state: { ...STATE, current: { slide: 2, click: 3 } } }));
		await fireEvent.click(screen.getByRole('button', { name: '다음' }));
		expect(live.goto).toHaveBeenCalledWith({ slide: 3, click: 0 });
	});

	it('다른 탭에서 넘기면(서버 발행) 이 화면도 따라간다 (AC17)', async () => {
		await open();
		await server(snapshot({ state: { ...STATE, current: { slide: 4, click: 0 } } }));
		expect(main().goto).toHaveBeenLastCalledWith({ slide: 4, click: 0 });
	});

	it('위치가 바뀌어도 슬라이드 다리를 다시 만들지 않는다(다시 만들면 준비 전이라 지시가 사라진다)', async () => {
		await open();
		await server(snapshot({ state: { ...STATE, current: { slide: 3, click: 0 } } }));
		await server(snapshot({ state: { ...STATE, current: { slide: 4, click: 0 } } }));
		expect(decks.all).toHaveLength(2);
		expect(main().stop).not.toHaveBeenCalled();
	});

	it('처음에서는 이전이, 끝에서는 다음이 흐려진다', async () => {
		await open(snapshot({ state: { ...STATE, current: { slide: 1, click: 0 } } }));
		await slides(main(), { position: { slide: 1, click: 0 }, clicksTotal: 0 });
		expect((screen.getByRole('button', { name: '이전' }) as HTMLButtonElement).disabled).toBe(true);
		expect((screen.getByRole('button', { name: '다음' }) as HTMLButtonElement).disabled).toBe(false);
		await server(snapshot({ state: { ...STATE, current: { slide: 4, click: 1 } } }));
		await slides(main(), { position: { slide: 4, click: 1 }, clicksTotal: 1 });
		expect((screen.getByRole('button', { name: '다음' }) as HTMLButtonElement).disabled).toBe(true);
		expect((screen.getByRole('button', { name: '이전' }) as HTMLButtonElement).disabled).toBe(false);
	});

	it('끝이면 마지막 슬라이드라고 알리고, 미리보기는 지금 위치를 보인다', async () => {
		await open(snapshot({ state: { ...STATE, current: { slide: 4, click: 1 } } }));
		await slides(main(), { position: { slide: 4, click: 1 }, clicksTotal: 1 });
		const reason = screen.getByText('마지막 슬라이드입니다.');
		expect(screen.getByRole('button', { name: '다음' }).getAttribute('aria-describedby')).toBe(reason.id);
		expect(preview().goto).toHaveBeenLastCalledWith({ slide: 4, click: 1 });
	});

	it('처음이면 첫 슬라이드라고 알린다', async () => {
		await open(snapshot({ state: { ...STATE, current: { slide: 1, click: 0 } } }));
		await slides(main(), { position: { slide: 1, click: 0 }, clicksTotal: 0 });
		const reason = screen.getByText('첫 슬라이드입니다.');
		expect(screen.getByRole('button', { name: '이전' }).getAttribute('aria-describedby')).toBe(reason.id);
	});

	it('지금 위치를 화면 낭독기에도 알린다', async () => {
		await open();
		const where = screen.getByText(/2 \/ 4 슬라이드/);
		expect(where.getAttribute('aria-live')).toBe('polite');
		expect(where.textContent).toContain('단계 0/3');
	});

	it('슬라이드가 따라오는 동안에는 이전 슬라이드의 단계 수를 보이지 않고 끝이라고도 하지 않는다', async () => {
		await open(); // 2번 슬라이드(단계 3개)를 그렸다
		await server(snapshot({ state: { ...STATE, current: { slide: 4, click: 0 } } })); // 아직 2번을 보이는 중
		expect(screen.getByText(/4 \/ 4 슬라이드/).textContent).not.toContain('단계');
		expect((screen.getByRole('button', { name: '다음' }) as HTMLButtonElement).disabled).toBe(false);
		expect(screen.queryByText('마지막 슬라이드입니다.')).toBeNull();
	});

	it('같은 슬라이드라도 단계가 다르면 아직 따라오는 중이다', async () => {
		live.goto.mockResolvedValue(5);
		await open(); // (2, 0)을 그렸다
		await server(snapshot({ state: { ...STATE, current: { slide: 2, click: 1 } } }));
		await fireEvent.click(screen.getByRole('button', { name: '다음' }));
		expect(live.goto).not.toHaveBeenCalled();
		await slides(main(), { position: { slide: 2, click: 1 }, clicksTotal: 3 });
		await fireEvent.click(screen.getByRole('button', { name: '다음' }));
		expect(live.goto).toHaveBeenCalledWith({ slide: 2, click: 2 });
	});

	it('이전 슬라이드로 돌아가면 그 슬라이드의 마지막 단계로 간다', async () => {
		live.goto.mockResolvedValue(5);
		await open(); // 2번 슬라이드(단계 3개)를 그렸다
		await server(snapshot({ state: { ...STATE, current: { slide: 3, click: 0 } } }));
		await slides(main(), { position: { slide: 3, click: 0 }, clicksTotal: 0 });
		await fireEvent.click(screen.getByRole('button', { name: '이전' }));
		expect(live.goto).toHaveBeenCalledWith({ slide: 2, click: 3 });
	});

	it('서버 위치를 슬라이드가 아직 그리지 않았으면 넘기지 않는다(이전 슬라이드의 단계 수로 계산하지 않는다)', async () => {
		live.goto.mockResolvedValue(5);
		await open(); // 2번 슬라이드(단계 3개)
		await server(snapshot({ state: { ...STATE, current: { slide: 3, click: 0 } } }));
		const next = screen.getByRole('button', { name: '다음' }) as HTMLButtonElement;
		expect(next.getAttribute('aria-disabled')).toBe('true');
		expect(next.disabled).toBe(false); // 초점을 잃지 않게 흐리게만 한다
		await fireEvent.click(next);
		await fireEvent.keyDown(window, { key: 'ArrowRight' });
		expect(live.goto).not.toHaveBeenCalled();
		await slides(main(), { position: { slide: 3, click: 0 }, clicksTotal: 0 });
		expect(next.getAttribute('aria-disabled')).toBe('false');
		await fireEvent.click(next);
		expect(live.goto).toHaveBeenCalledWith({ slide: 4, click: 0 });
	});

	it('ack를 받기 전에는 같은 요청을 다시 보내지 않는다', async () => {
		let answer: (v: number) => void = () => {};
		live.goto.mockReturnValue(new Promise<number>((r) => (answer = r)));
		await open();
		const next = screen.getByRole('button', { name: '다음' });
		await fireEvent.click(next);
		await fireEvent.click(next);
		await fireEvent.keyDown(window, { key: 'ArrowRight' });
		expect(live.goto).toHaveBeenCalledTimes(1);
		expect((next as HTMLButtonElement).disabled).toBe(false); // 기다리는 동안에도 초점이 그대로 있다
		expect(next.getAttribute('aria-disabled')).toBe('true');
		const previous = screen.getByRole('button', { name: '이전' }) as HTMLButtonElement;
		expect(previous.disabled).toBe(false);
		expect(previous.getAttribute('aria-disabled')).toBe('true');
		await act(() => answer(4));
		await fireEvent.click(next);
		expect(live.goto).toHaveBeenCalledTimes(2);
	});

	it('서버가 거절하면 이유를 보인다', async () => {
		live.goto.mockRejectedValue({ reason: 'out_of_range', message: '그 위치로 넘길 수 없습니다. 슬라이드 범위를 확인해 주세요.' });
		await open();
		await fireEvent.click(screen.getByRole('button', { name: '다음' }));
		expect((await screen.findByRole('alert')).textContent).toContain('그 위치로 넘길 수 없습니다.');
	});

	it('키보드 →·Space는 다음, ←는 이전이다', async () => {
		live.goto.mockResolvedValue(4);
		await open();
		await fireEvent.keyDown(window, { key: 'ArrowRight' });
		expect(live.goto).toHaveBeenLastCalledWith({ slide: 2, click: 1 });
		await waitFor(() => expect((screen.getByRole('button', { name: '다음' }) as HTMLButtonElement).disabled).toBe(false));
		await fireEvent.keyDown(window, { key: ' ' });
		expect(live.goto).toHaveBeenCalledTimes(2);
		await waitFor(() => expect((screen.getByRole('button', { name: '이전' }) as HTMLButtonElement).disabled).toBe(false));
		await fireEvent.keyDown(window, { key: 'ArrowLeft' });
		expect(live.goto).toHaveBeenLastCalledWith({ slide: 1, click: 0 });
	});

	it('버튼이나 링크에 초점이 있으면 Space는 그 버튼의 몫이다(화살표는 넘긴다)', async () => {
		live.goto.mockResolvedValue(4);
		await open();
		const projector = screen.getByRole('button', { name: '프로젝터 화면 열기' });
		projector.focus();
		await fireEvent.keyDown(projector, { key: ' ' });
		const previous = screen.getByRole('button', { name: '이전' });
		await fireEvent.keyDown(previous, { key: ' ' });
		expect(live.goto).not.toHaveBeenCalled();
		await fireEvent.keyDown(projector, { key: 'ArrowRight' });
		expect(live.goto).toHaveBeenCalledTimes(1);
	});

	it('Shift+Space와 길게 눌러 반복되는 키는 넘기지 않는다', async () => {
		await open();
		await fireEvent.keyDown(window, { key: ' ', shiftKey: true });
		await fireEvent.keyDown(window, { key: 'ArrowRight', repeat: true });
		expect(live.goto).not.toHaveBeenCalled();
	});

	it('글 입력 칸에 초점이 있거나 다른 키를 함께 누르면 키보드로 넘기지 않는다', async () => {
		await open();
		const input = document.createElement('input');
		const textarea = document.createElement('textarea');
		document.body.append(input, textarea);
		await fireEvent.keyDown(input, { key: 'ArrowRight' });
		await fireEvent.keyDown(textarea, { key: ' ' });
		await fireEvent.keyDown(window, { key: 'ArrowRight', ctrlKey: true });
		await fireEvent.keyDown(window, { key: 'ArrowLeft', metaKey: true });
		expect(live.goto).not.toHaveBeenCalled();
	});

	it('현재 슬라이드 안에서 넘기려 한 방향(deck:intent)도 넘기기다', async () => {
		live.goto.mockResolvedValue(4);
		await open();
		await act(() => main().onIntent?.('next'));
		expect(live.goto).toHaveBeenCalledWith({ slide: 2, click: 1 });
		expect(preview().onIntent).toBeUndefined(); // 미리보기는 넘기지 않는다
	});
});

describe('메시지·자료 보내기 탭 (AC31, C12)', () => {
	it('회차가 바뀌면 보내기 칸을 새로 시작한다', async () => {
		await open();
		await fireEvent.input(screen.getByLabelText('글'), { target: { value: '1회차에 쓰던 글' } });
		await server(snapshot({ state: { ...STATE, session: { ...STATE.session, id: 6 } } }));
		expect((screen.getByLabelText('글') as HTMLTextAreaElement).value).toBe('');
	});

	it('오른쪽에 보내기 칸과 이 회차의 보낸 항목이 있다', async () => {
		await open(snapshot({ state: { ...STATE, items: [{ id: 1, body: '과제', url: null, created_at: '2026-03-04T05:01:00+00:00', retracted_at: null }] } }));
		const panel = screen.getByRole('region', { name: '메시지·자료 보내기' });
		expect(panel.textContent).toContain('과제');
		expect(screen.getByRole('button', { name: '학생에게 보내기' })).toBeTruthy();
	});

	it('슬라이드가 없거나 열리지 않아도 보내기는 쓸 수 있다', async () => {
		await open(snapshot({ state: { ...STATE, deck: null } }));
		expect(screen.getByRole('region', { name: '메시지·자료 보내기' })).toBeTruthy();
		cleanup();
		await open(snapshot({ state: { ...STATE, deck: { id: 9, slide_count: 4, available: false } } }));
		expect(screen.getByRole('region', { name: '메시지·자료 보내기' })).toBeTruthy();
	});

	it('연결이 끊기면 보낼 글이 있어도 보내기가 흐려진다', async () => {
		await open();
		await fireEvent.input(screen.getByLabelText('글'), { target: { value: '보낼 글' } });
		await server(snapshot({ status: 'reconnecting' }));
		expect((screen.getByRole('button', { name: '학생에게 보내기' }) as HTMLButtonElement).disabled).toBe(false);
		expect(screen.getByRole('button', { name: '학생에게 보내기' }).getAttribute('aria-disabled')).toBe('true');
	});

	it('이 회차에 보내고, 보낸 뒤 상태를 다시 받는다', async () => {
		api.sendItem.mockResolvedValue({ id: 9, body: '공지', url: null, created_at: '2026-03-04T05:13:00+00:00', retracted_at: null });
		await open();
		await fireEvent.input(screen.getByLabelText('글'), { target: { value: '공지' } });
		await fireEvent.click(screen.getByRole('button', { name: '학생에게 보내기' }));
		await waitFor(() => expect(live.reload).toHaveBeenCalled());
		expect(api.sendItem.mock.calls[0].slice(0, 2)).toEqual([7, 5]);
	});
});

describe('수업 종료 (AC37)', () => {
	const ASK = '수업을 끝낼까요? 학생은 이번 수업에서 본 슬라이드와 받은 자료를 계속 볼 수 있습니다.';

	it('누르면 서버를 부르기 전에 확인 문구가 나온다', async () => {
		await open();
		await fireEvent.click(screen.getByRole('button', { name: '수업 종료' }));
		const dialog = await screen.findByRole('alertdialog');
		// AC37 문구: 제목 "수업을 끝낼까요?" + 설명
		const [question, detail] = ASK.split('? ');
		expect(within(dialog).getByRole('heading', { name: `${question}?` })).toBeTruthy();
		expect(dialog.textContent).toContain(detail);
		expect(api.endSession).not.toHaveBeenCalled();
	});

	it('확인하면 회차를 끝내고 관리 페이지로 돌아간다', async () => {
		api.endSession.mockResolvedValue({ id: 5, status: 'ended', version: 7 });
		await open();
		await fireEvent.click(screen.getByRole('button', { name: '수업 종료' }));
		await fireEvent.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: '수업 종료' }));
		await waitFor(() => expect(nav.goto).toHaveBeenCalledWith('/courses/7/admin'));
		expect(api.endSession).toHaveBeenCalledWith(7, 5);
	});

	it('취소하면 그대로다', async () => {
		await open();
		await fireEvent.click(screen.getByRole('button', { name: '수업 종료' }));
		await fireEvent.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: '취소' }));
		await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
		expect(api.endSession).not.toHaveBeenCalled();
		expect(nav.goto).not.toHaveBeenCalled();
		expect(screen.getByTitle('현재 슬라이드')).toBeTruthy();
	});

	it('끝내지 못하면 확인 창 안에 이유와 할 일을 보이고 수업 화면에 머문다', async () => {
		api.endSession.mockRejectedValue(new TypeError('Failed to fetch'));
		await open();
		await fireEvent.click(screen.getByRole('button', { name: '수업 종료' }));
		const dialog = await screen.findByRole('alertdialog');
		await fireEvent.click(within(dialog).getByRole('button', { name: '수업 종료' }));
		const alert = await within(dialog).findByRole('alert');
		expect(alert.textContent).toContain('수업을 끝내지 못했습니다.');
		expect(alert.textContent).toContain('네트워크 연결을 확인하고 다시 시도해 주세요.');
		expect(nav.goto).not.toHaveBeenCalled();
	});

	it('서버가 거절하면 그 안내를 보인다', async () => {
		const { ApiError } = await import('#lib/api.js');
		api.endSession.mockRejectedValue(new ApiError(409, '아직 시작하지 않은 회차입니다.'));
		await open();
		await fireEvent.click(screen.getByRole('button', { name: '수업 종료' }));
		const dialog = await screen.findByRole('alertdialog');
		await fireEvent.click(within(dialog).getByRole('button', { name: '수업 종료' }));
		expect((await within(dialog).findByRole('alert')).textContent).toContain('아직 시작하지 않은 회차입니다.');
	});

	it('취소하면 초점이 수업 종료 버튼으로 돌아가고 다시 열 수 있다', async () => {
		await open();
		const button = screen.getByRole('button', { name: '수업 종료' });
		await fireEvent.click(button);
		await fireEvent.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: '취소' }));
		await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
		await waitFor(() => expect(document.activeElement).toBe(button));
		await fireEvent.click(button);
		expect(await screen.findByRole('alertdialog')).toBeTruthy();
	});

	it('확인 창이 열린 동안에는 화살표로 슬라이드를 넘기지 않는다(발표용 리모컨)', async () => {
		live.goto.mockResolvedValue(4);
		await open();
		await fireEvent.click(screen.getByRole('button', { name: '수업 종료' }));
		await screen.findByRole('alertdialog');
		await fireEvent.keyDown(window, { key: 'ArrowRight' });
		await fireEvent.keyDown(window, { key: 'ArrowLeft' });
		expect(live.goto).not.toHaveBeenCalled();
	});

	it('확인 창을 연 뒤 다른 탭에서 회차가 바뀌어도 연 때의 회차를 끝낸다', async () => {
		api.endSession.mockResolvedValue({ id: 5, status: 'ended', version: 7 });
		await open();
		await fireEvent.click(screen.getByRole('button', { name: '수업 종료' }));
		const dialog = await screen.findByRole('alertdialog');
		// 다른 탭에서 5번을 끝내고 6번을 시작했다
		await server(snapshot({ liveSessionId: 6, state: { ...STATE, session: { ...STATE.session, id: 6, title: '다른 회차' } } }));
		await fireEvent.click(within(dialog).getByRole('button', { name: '수업 종료' }));
		await waitFor(() => expect(api.endSession).toHaveBeenCalled());
		expect(api.endSession).toHaveBeenCalledWith(7, 5);
		await waitFor(() => expect(nav.goto).toHaveBeenCalledWith('/courses/7/admin'));
	});

	it('끝내는 중에 화면을 떠났으면 다 끝난 뒤에 관리 페이지로 끌고 가지 않는다', async () => {
		let finish: (v: unknown) => void = () => {};
		api.endSession.mockReturnValue(new Promise((r) => (finish = r)));
		await open();
		await fireEvent.click(screen.getByRole('button', { name: '수업 종료' }));
		await fireEvent.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: '수업 종료' }));
		cleanup();
		await act(() => finish({ id: 5, status: 'ended', version: 7 }));
		expect(nav.goto).not.toHaveBeenCalled();
	});

	it('진행 중인 수업이 없으면 수업 종료 버튼이 없다', async () => {
		await open(snapshot({ state: null, liveSessionId: null }));
		expect(screen.queryByRole('button', { name: '수업 종료' })).toBeNull();
		cleanup();
		await open(snapshot({ state: { ...STATE, session: { ...STATE.session, status: 'ended' } }, liveSessionId: null }));
		expect(screen.queryByRole('button', { name: '수업 종료' })).toBeNull();
	});
});

describe('동기화 현황 (AC15, C7)', () => {
	it('슬라이드 아래에 따라가는 중과 직접 넘겨 보는 중이 숫자로만 보인다', async () => {
		await open();
		const line = screen.getByText('따라가는 중 30명 · 직접 넘겨 보는 중 4명');
		expect(line.closest('[aria-label="슬라이드"]')).toBeTruthy();
		// 이전·다음 바로 아래, 다음 슬라이드 카드보다 위(목업 Main)
		const next = screen.getByRole('button', { name: '다음' });
		const card = screen.getByRole('heading', { name: '다음 슬라이드' });
		expect(next.compareDocumentPosition(line) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
		expect(line.compareDocumentPosition(card) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
	});

	it('학생이 들어오거나 바꾸면 숫자가 바뀐다', async () => {
		await open();
		await server(snapshot({ presence: { follow: 31, browse: 3 } }));
		expect(screen.getByText('따라가는 중 31명 · 직접 넘겨 보는 중 3명')).toBeTruthy();
		expect(screen.getByRole('banner').textContent).toContain('접속 34명');
	});

	it('현황을 아직 받지 못했으면 숫자를 지어내지 않는다', async () => {
		await open(snapshot({ presence: null }));
		expect(screen.queryByText(/따라가는 중 \d+명/)).toBeNull();
	});

	it('슬라이드가 없거나 열리지 않아도 현황은 보인다', async () => {
		await open(snapshot({ state: { ...STATE, deck: null } }));
		expect(screen.getByText('따라가는 중 30명 · 직접 넘겨 보는 중 4명').closest('[aria-label="슬라이드"]')).toBeTruthy();
		cleanup();
		await open(snapshot({ state: { ...STATE, deck: { id: 9, slide_count: 4, available: false } } }));
		expect(screen.getByText('따라가는 중 30명 · 직접 넘겨 보는 중 4명')).toBeTruthy();
	});
});

describe('연결 끊김 (C12)', () => {
	const OFFLINE = '연결이 끊겼습니다. 다시 연결하는 중…';

	it('끊기면 안내가 보이고 이전·다음이 흐려지며 누르거나 키를 눌러도 보내지 않는다', async () => {
		live.goto.mockResolvedValue(4);
		await open();
		await server(snapshot({ status: 'reconnecting' }));
		const notice = screen.getByText(OFFLINE);
		expect(notice.closest('[role="status"]')).toBeTruthy();
		for (const name of ['이전', '다음']) {
			const button = screen.getByRole('button', { name }) as HTMLButtonElement;
			expect(button.getAttribute('aria-disabled')).toBe('true');
			expect(button.getAttribute('aria-describedby')).toContain('offline-notice');
		}
		await fireEvent.click(screen.getByRole('button', { name: '다음' }));
		await fireEvent.keyDown(window, { key: 'ArrowRight' });
		expect(live.goto).not.toHaveBeenCalled();
	});

	it('안내 자리는 끊기기 전부터 있어서 화면 낭독기가 끊김을 읽는다', async () => {
		await open();
		const region = document.querySelector('[data-connection-notice]') as HTMLElement;
		expect(region.getAttribute('role')).toBe('status');
		expect(region.textContent?.trim()).toBe('');
		await server(snapshot({ status: 'reconnecting' }));
		expect(document.querySelector('[data-connection-notice]')).toBe(region); // 같은 자리에 글만 들어온다
		expect(region.textContent).toContain(OFFLINE);
	});

	it('끊긴 동안의 현황 숫자는 끊기기 전 것이라고 밝힌다', async () => {
		await open();
		await server(snapshot({ status: 'reconnecting' }));
		expect(screen.getByText('따라가는 중 30명 · 직접 넘겨 보는 중 4명 (연결이 끊기기 전)')).toBeTruthy();
		expect(screen.getByRole('banner').textContent).toContain('접속 34명 (연결이 끊기기 전)');
		await server(snapshot({ status: 'live', presence: { follow: 10, browse: 24 } }));
		expect(screen.getByText('따라가는 중 10명 · 직접 넘겨 보는 중 24명')).toBeTruthy();
	});

	it('넘기는 중에 끊겨 실패하면 오류를 따로 남기지 않는다(끊김 안내가 대신하고, 다시 붙으면 사라진다)', async () => {
		live.goto.mockRejectedValue({ reason: 'offline', message: '연결이 끊겼습니다. 다시 연결되면 넘겨 주세요.' });
		await open();
		await fireEvent.click(screen.getByRole('button', { name: '다음' }));
		await server(snapshot({ status: 'reconnecting' }));
		await server(snapshot({ status: 'live' }));
		expect(screen.queryByText('연결이 끊겼습니다. 다시 연결되면 넘겨 주세요.')).toBeNull();
		expect(screen.queryByRole('alert')).toBeNull();
	});

	it('끊겨도 마지막 슬라이드는 그대로 둔다', async () => {
		await open();
		await server(snapshot({ status: 'reconnecting' }));
		expect(screen.getByTitle('현재 슬라이드')).toBeTruthy();
		expect(main().stop).not.toHaveBeenCalled();
	});

	it('다시 붙으면 안내가 사라지고 저장된 위치에서 이어진다', async () => {
		live.goto.mockResolvedValue(6);
		await open();
		await server(snapshot({ status: 'reconnecting' }));
		await server(snapshot({ status: 'live', state: { ...STATE, current: { slide: 3, click: 0 }, session: { ...STATE.session, version: 5 } } }));
		expect(screen.queryByText(OFFLINE)).toBeNull();
		expect(main().goto).toHaveBeenLastCalledWith({ slide: 3, click: 0 });
		await slides(main(), { position: { slide: 3, click: 0 }, clicksTotal: 0 });
		expect(screen.getByRole('button', { name: '다음' }).getAttribute('aria-disabled')).toBe('false');
		await fireEvent.click(screen.getByRole('button', { name: '다음' }));
		expect(live.goto).toHaveBeenCalledWith({ slide: 4, click: 0 });
	});

	it('슬라이드가 없는 수업에서도 끊기면 알린다', async () => {
		await open(snapshot({ state: { ...STATE, deck: null } }));
		await server(snapshot({ status: 'reconnecting', state: { ...STATE, deck: null } }));
		expect(screen.getByText(OFFLINE)).toBeTruthy();
	});
});

describe('수업이 없거나 끝났을 때', () => {
	it('불러오는 동안에는 그렇게 알린다', async () => {
		render(LivePage, { params: { id: '7' }, data: { me: null, classroom: CLASSROOM, notice: null } });
		await server(snapshot({ status: 'connecting', state: null, liveSessionId: null, loaded: false }));
		expect(screen.getByText('수업을 불러오는 중…')).toBeTruthy();
	});

	it('연결은 됐지만 아직 상태를 받지 못했으면 수업이 없다고 하지 않는다', async () => {
		render(LivePage, { params: { id: '7' }, data: { me: null, classroom: CLASSROOM, notice: null } });
		await server(snapshot({ status: 'live', state: null, liveSessionId: null, loaded: false }));
		expect(screen.getByText('수업을 불러오는 중…')).toBeTruthy();
		expect(screen.queryByText('진행 중인 수업이 없습니다.')).toBeNull();
	});

	it('불러오기에 실패하면 무엇이 잘못됐는지와 할 일을 알린다', async () => {
		render(LivePage, { params: { id: '7' }, data: { me: null, classroom: CLASSROOM, notice: null } });
		await server(snapshot({ state: null, liveSessionId: null, loaded: false, loadError: '불러오지 못했습니다 (500)' }));
		const alert = screen.getByRole('alert');
		expect(alert.textContent).toContain('불러오지 못했습니다 (500)');
		expect(alert.textContent).toContain('잠시 뒤 자동으로 다시 불러옵니다.');
		expect(screen.queryByText('진행 중인 수업이 없습니다.')).toBeNull();
	});

	it('진행 중인 수업이 없으면 관리 페이지로 가는 길을 알린다', async () => {
		await open(snapshot({ state: null, liveSessionId: null }));
		expect(screen.getByText('진행 중인 수업이 없습니다.')).toBeTruthy();
		expect(screen.getByRole('link', { name: '관리 페이지로' }).getAttribute('href')).toBe('/courses/7/admin');
	});

	it('수업이 끝났으면 그렇게 알린다', async () => {
		await open(snapshot({ state: { ...STATE, session: { ...STATE.session, status: 'ended' } }, liveSessionId: null }));
		expect(screen.getByText('수업이 끝났습니다.')).toBeTruthy();
		expect(screen.queryByRole('button', { name: '다음' })).toBeNull();
	});

	it('권한이 없거나 없는 강좌면 안내만 보인다', () => {
		render(LivePage, { params: { id: '7' }, data: { me: null, classroom: null, notice: { status: 403, message: '이 강좌를 볼 권한이 없습니다.' } } });
		expect(screen.getByRole('alert').textContent).toContain('이 강좌를 볼 권한이 없습니다.');
		expect(decks.all).toHaveLength(0);
	});

	it('화면을 떠나면 연결을 닫는다', async () => {
		await open();
		cleanup();
		expect(live.stop).toHaveBeenCalled();
	});
});

describe('교수 수업 화면 load', () => {
	const reply = (status: number, body: unknown) => vi.fn(() => Promise.resolve(new Response(JSON.stringify(body), { status })));

	it('강좌를 받는다', async () => {
		const { load } = await import('./+page');
		const fetch = reply(200, CLASSROOM);
		expect(await load({ fetch, params: { id: '7' } } as never)).toEqual({ classroom: CLASSROOM, notice: null });
		expect((fetch.mock.calls[0] as unknown as [string])[0]).toBe('/api/classrooms/7');
	});

	it('다른 교수의 강좌나 없는 강좌는 안내로 돌려준다', async () => {
		const { load } = await import('./+page');
		expect(await load({ fetch: reply(403, { detail: '이 강좌를 볼 권한이 없습니다.' }), params: { id: '7' } } as never)).toEqual({
			classroom: null,
			notice: { status: 403, message: '이 강좌를 볼 권한이 없습니다.' }
		});
		const fetch = reply(200, {});
		expect(((await load({ fetch, params: { id: 'x' } } as never)) as { notice: { status: number } }).notice.status).toBe(404);
		expect(fetch).not.toHaveBeenCalled();
	});

	it('서버 오류는 오류로 올린다', async () => {
		const { load } = await import('./+page');
		await expect(load({ fetch: reply(500, {}), params: { id: '7' } } as never)).rejects.toThrow();
	});
});
