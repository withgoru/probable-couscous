// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

const nav = vi.hoisted(() => ({ invalidate: vi.fn(() => Promise.resolve()) }));
const api = vi.hoisted(() => ({
	addStudent: vi.fn(),
	regenerateInvite: vi.fn(),
	fetchJoinRequests: vi.fn(),
	fetchPendingAuth: vi.fn(),
	approveJoinRequest: vi.fn()
}));
// 실시간 연결은 흉내 낸다: 화면이 넘긴 처리기를 잡아 두고 테스트가 서버 이벤트를 일으킨다
type Handlers = { onReady: () => void; onEvent: (e: { type: string; id?: number }) => void; onStatus: (s: string) => void };
const live = vi.hoisted(() => ({ handlers: null as unknown, classroomId: 0, stop: vi.fn(), connectAdmin: vi.fn() }));
vi.mock('$app/navigation', () => nav);
vi.mock('#lib/api.js', async (original) => ({
	...(await original<object>()),
	addStudent: api.addStudent,
	regenerateInvite: api.regenerateInvite,
	fetchJoinRequests: api.fetchJoinRequests,
	fetchPendingAuth: api.fetchPendingAuth,
	approveJoinRequest: api.approveJoinRequest
}));
vi.mock('#lib/adminLive.js', () => ({
	connectAdmin: (id: number, handlers: unknown) => {
		live.classroomId = id;
		live.handlers = handlers;
		live.connectAdmin(id);
		return live.stop;
	}
}));
const server = () => live.handlers as Handlers;

import { act, fireEvent, waitFor } from '@testing-library/svelte';
import { beforeEach } from 'vitest';
import { load } from './+page';
import AdminPage from './+page.svelte';

afterEach(cleanup);

const reply = (status: number, body: unknown) => () =>
	Promise.resolve(new Response(JSON.stringify(body), { status }));
const params = (id: string) => ({ id });
const ROSTER = { entries: [], count: 0, limit: 200 };
const session = (id: number, title: string, status: 'scheduled' | 'live' | 'ended') => ({
	id, title, status, sort_order: id, created_at: 'x', can_delete: status === 'scheduled', deck: null
});
const SESSIONS = [session(1, '1회차', 'ended'), session(2, '2회차', 'live'), session(3, '3회차', 'scheduled')];
const INVITE = { token: 'abc', url: 'http://localhost:8000/join/abc' };
// 강좌와 명단을 주소로 구분해 답한다
const routed = (
	classroom: () => Response | Promise<Response>,
	roster: () => Response | Promise<Response> = () => new Response(JSON.stringify(ROSTER)),
	invite: () => Response | Promise<Response> = () => new Response(JSON.stringify(INVITE)),
	sessions: () => Response | Promise<Response> = () => new Response(JSON.stringify({ items: SESSIONS }))
) =>
	vi.fn((url: string) =>
		Promise.resolve(
			url.endsWith('/roster')
				? roster()
				: url.endsWith('/invite')
					? invite()
					: url.endsWith('/sessions')
						? sessions()
						: classroom()
		)
	);
const res = (status: number, body: unknown) => () => new Response(JSON.stringify(body), { status });
const MINE = { id: 7, name: '알고리즘', section_name: null, status: 'active', student_count: 0, session_count: 0, created_at: 'x' } as const;

describe('관리 페이지 load (AC8)', () => {
	it('내 강좌면 강좌를 돌려준다', async () => {
		const classroom = MINE;
		const fetch = routed(res(200, classroom));
		expect(await load({ fetch, params: params('7'), depends: vi.fn() } as never)).toEqual({
			classroom,
			roster: ROSTER,
			invite: INVITE,
			sessions: SESSIONS,
			notice: null
		});
		expect(fetch).toHaveBeenCalledWith('/api/classrooms/7/sessions', expect.anything());
		expect(fetch).toHaveBeenCalledWith('/api/classrooms/7/invite', expect.anything());
		expect(fetch).toHaveBeenCalledWith('/api/classrooms/7', expect.anything());
		expect(fetch).toHaveBeenCalledWith('/api/classrooms/7/roster', expect.anything());
	});

	it('명단을 다시 불러올 수 있게 의존성을 등록한다', async () => {
		const depends = vi.fn();
		await load({ fetch: routed(res(200, MINE)), params: params('7'), depends } as never);
		expect(depends).toHaveBeenCalledWith('app:roster');
		expect(depends).toHaveBeenCalledWith('app:invite');
		expect(depends).toHaveBeenCalledWith('app:sessions'); // 회차를 만들거나 지운 뒤 다시 불러온다
	});

	it('다른 교수의 강좌(403)는 오류 화면이 아니라 안내로 돌려준다', async () => {
		const fetch = routed(res(403, { detail: '이 강좌를 볼 권한이 없습니다.' }), res(403, { detail: '이 강좌를 볼 권한이 없습니다.' }));
		const result = await load({ fetch, params: params('7'), depends: vi.fn() } as never);
		expect(result).toEqual({
			classroom: null,
			roster: null,
			invite: null,
			sessions: null,
			notice: { status: 403, message: '이 강좌를 볼 권한이 없습니다.' }
		});
	});

	it('없는 강좌(404)도 안내로 돌려준다', async () => {
		const result = (await load({ fetch: routed(res(404, { detail: '찾을 수 없는 강좌입니다.' }), res(404, { detail: '찾을 수 없는 강좌입니다.' })), params: params('999'), depends: vi.fn() } as never)) as {
			notice: { status: number };
		};
		expect(result.notice.status).toBe(404);
	});

	it('숫자가 아닌 주소는 서버를 부르지 않고 없는 강좌로 본다', async () => {
		const fetch = vi.fn(reply(200, {}));
		const result = (await load({ fetch, params: params('abc'), depends: vi.fn() } as never)) as { notice: { status: number } };
		expect(result.notice.status).toBe(404);
		expect(fetch).not.toHaveBeenCalled();
	});

	it('서버 오류는 안내가 아니라 오류로 올린다', async () => {
		await expect(load({ fetch: reply(500, {}), params: params('7'), depends: vi.fn() } as never)).rejects.toThrow();
	});

	it('초대 링크를 불러오지 못하면 오류로 올린다', async () => {
		const fetch = routed(res(200, MINE), undefined, res(500, {}));
		await expect(load({ fetch, params: params('7'), depends: vi.fn() } as never)).rejects.toThrow();
	});

	it('명단을 불러오지 못하면 오류로 올린다', async () => {
		const fetch = routed(res(200, MINE), res(500, {}));
		await expect(load({ fetch, params: params('7'), depends: vi.fn() } as never)).rejects.toThrow();
	});

	it('회차 목록을 불러오지 못하면 오류로 올린다', async () => {
		const fetch = routed(res(200, MINE), undefined, undefined, res(500, {}));
		await expect(load({ fetch, params: params('7'), depends: vi.fn() } as never)).rejects.toThrow();
	});
});

describe('관리 페이지 위쪽의 회차 선택 (002 AC1, AC3)', () => {
	const page = (sessions: typeof SESSIONS) => ({
		params: { id: '7' },
		data: { me: null, classroom: MINE, roster: ROSTER, invite: INVITE, sessions, notice: null }
	});
	const trigger = () => screen.getByRole('button', { name: /회차 선택/ });

	it('진행 중인 회차가 있으면 그 회차가 처음 선택돼 있다', () => {
		render(AdminPage, page(SESSIONS));
		expect(trigger().textContent).toContain('2회차');
		expect(trigger().textContent).toContain('진행 중');
	});

	it('진행 중인 회차가 없으면 아직 끝나지 않은 첫 예정 회차가 선택돼 있다', () => {
		render(AdminPage, page([session(1, '1회차', 'ended'), session(3, '3회차', 'scheduled'), session(4, '4회차', 'scheduled')]));
		expect(trigger().textContent).toContain('3회차');
	});

	it('모두 끝났으면 마지막 회차가 선택돼 있다', () => {
		render(AdminPage, page([session(1, '1회차', 'ended'), session(2, '2회차', 'ended')]));
		expect(trigger().textContent).toContain('2회차');
	});

	it('회차가 없으면 안내와 회차 만들기가 보인다', () => {
		render(AdminPage, page([]));
		expect(screen.getByText('아직 회차가 없습니다. 회차를 만들어 수업을 준비하세요.')).toBeTruthy();
		expect(screen.getByRole('button', { name: '회차 만들기' })).toBeTruthy();
	});

	it('고른 회차의 자료와 수업 버튼이 보인다 (002 AC5, AC9, AC18)', () => {
		render(AdminPage, page(SESSIONS));
		expect(screen.getByRole('region', { name: '이 회차의 자료' })).toBeTruthy();
		expect(screen.getByRole('link', { name: '수업 화면으로' }).getAttribute('href')).toBe('/courses/7/live');
	});

	it('회차가 없으면 자료와 수업 버튼도 없다', () => {
		render(AdminPage, page([]));
		expect(screen.queryByRole('region', { name: '이 회차의 자료' })).toBeNull();
		expect(screen.queryByRole('button', { name: '수업 시작' })).toBeNull();
	});

	it('보관된 강좌에서는 수업 시작 대신 안내가 보인다 (002 AC11)', () => {
		render(AdminPage, {
			params: { id: '7' },
			data: { me: null, classroom: { ...MINE, status: 'archived' }, roster: ROSTER, invite: INVITE, sessions: [session(3, '3회차', 'scheduled')], notice: null }
		});
		expect(screen.getByText('보관된 강좌는 수업을 시작할 수 없습니다.')).toBeTruthy();
		expect(screen.queryByRole('button', { name: '수업 시작' })).toBeNull();
	});

	it('다른 회차를 고르면 그 회차가 선택된다', async () => {
		render(AdminPage, page(SESSIONS));
		await fireEvent.keyDown(trigger(), { key: 'Enter' });
		await fireEvent.click(await screen.findByRole('menuitemradio', { name: /3회차/ }));
		await waitFor(() => expect(trigger().textContent).toContain('3회차'));
	});
});

describe('관리 페이지 화면', () => {
	it('권한이 없으면 AC8의 문구와 돌아갈 길을 보여 준다', () => {
		render(AdminPage, {
			params: { id: '7' },
			data: { me: null, classroom: null, roster: null, invite: null, sessions: null, notice: { status: 403, message: '이 강좌를 볼 권한이 없습니다.' } }
		});
		const alert = screen.getByRole('alert');
		expect(alert.textContent).toContain('이 강좌를 볼 권한이 없습니다');
		expect(alert.textContent).toContain('내 강좌');
		expect(screen.getByRole('link', { name: '내 강좌로 돌아가기' }).getAttribute('href')).toBe('/courses');
	});

	it('없는 강좌면 그렇게 알려 준다', () => {
		render(AdminPage, {
			params: { id: '7' },
			data: { me: null, classroom: null, roster: null, invite: null, sessions: null, notice: { status: 404, message: '찾을 수 없는 강좌입니다.' } }
		});
		expect(screen.getByRole('alert').textContent).toContain('찾을 수 없는 강좌입니다');
	});

	it('내 강좌면 이름과 수강생 명단이 보인다', () => {
		render(AdminPage, { params: { id: '7' },
			data: { me: null, classroom: MINE, roster: ROSTER, invite: INVITE, sessions: [], notice: null } });
		expect(screen.getByRole('heading', { level: 1, name: '관리 페이지' })).toBeTruthy();
		expect(screen.getByText('알고리즘')).toBeTruthy();
		expect(screen.getByRole('heading', { level: 2, name: '수강생 명단' })).toBeTruthy();
		expect(screen.getByRole('heading', { level: 2, name: '초대 링크' })).toBeTruthy();
		expect((screen.getByLabelText('초대 링크 주소') as HTMLInputElement).value).toBe(INVITE.url);
		expect(screen.queryByRole('alert')).toBeNull();
	});

	it('권한이 없을 때는 명단 영역이 없다', () => {
		render(AdminPage, { params: { id: '7' },
			data: { me: null, classroom: null, roster: null, invite: null, sessions: null, notice: { status: 403, message: 'x' } } });
		expect(screen.queryByRole('heading', { name: '수강생 명단' })).toBeNull();
		expect(screen.queryByRole('heading', { name: '초대 링크' })).toBeNull();
	});

	it('링크를 다시 만들면 초대 링크를 다시 불러온다(app:invite)', async () => {
		api.regenerateInvite.mockResolvedValue({ token: 'n', url: 'http://localhost:8000/join/n' });
		nav.invalidate.mockClear();
		render(AdminPage, { params: { id: '7' }, data: { me: null, classroom: MINE, roster: ROSTER, invite: INVITE, sessions: [], notice: null } });
		await fireEvent.click(screen.getByRole('button', { name: '링크 다시 만들기' }));
		await waitFor(() => expect(nav.invalidate).toHaveBeenCalledWith('app:invite'));
	});

	it('학생을 추가하면 명단을 다시 불러온다(app:roster)', async () => {
		api.addStudent.mockResolvedValue({ id: 3, student_no: '3', name: '박', email: 'p@x.kr' });
		render(AdminPage, { params: { id: '7' }, data: { me: null, classroom: MINE, roster: ROSTER, invite: INVITE, sessions: [], notice: null } });
		for (const [l, v] of [['학번', '3'], ['이름', '박'], ['이메일', 'p@x.kr']]) {
			await fireEvent.input(screen.getByLabelText(l), { target: { value: v } });
		}
		await fireEvent.click(screen.getByRole('button', { name: '학생 추가' }));
		await waitFor(() => expect(nav.invalidate).toHaveBeenCalledWith('app:roster'));
	});
});

// --- 입장 요청과 대기 중인 인증, 실시간 (AC40, AC45, T029) -------------------------------------------------------------

describe('관리 페이지의 입장 요청과 대기 중인 인증', () => {
	const REQUESTS = [{ id: 1, name: '박민수', student_no: '20249999', email: 'park@x.kr', created_at: '2026-03-02T05:05:00+00:00' }];
	const PENDING = [
		{ id: 11, student_no: '1', name: '김철수', notified_at: '2026-03-02T05:05:00+00:00', status: 'waiting', code: '349498', expires_at: '2999-01-01T00:00:00+00:00' }
	];
	const DATA = { me: null, classroom: MINE, roster: ROSTER, invite: INVITE, sessions: [], notice: null };

	beforeEach(() => {
		nav.invalidate.mockClear();
		live.stop.mockClear();
		live.connectAdmin.mockClear();
		api.fetchJoinRequests.mockReset().mockResolvedValue(REQUESTS);
		api.fetchPendingAuth.mockReset().mockResolvedValue(PENDING);
		api.approveJoinRequest.mockReset();
	});

	it('화면을 열면 이 강좌의 실시간 연결을 열고, 준비되기 전에는 불러오는 중이다', () => {
		render(AdminPage, { params: { id: '7' }, data: DATA });
		expect(live.connectAdmin).toHaveBeenCalledWith(7);
		expect(screen.getByRole('heading', { level: 2, name: /입장 요청/ })).toBeTruthy();
		expect(screen.getByRole('heading', { level: 2, name: /대기 중인 인증/ })).toBeTruthy();
		expect(screen.getAllByText('불러오는 중…')).toHaveLength(2);
		expect(api.fetchPendingAuth).not.toHaveBeenCalled(); // 코드를 볼 때마다 기록되므로 준비된 뒤 한 번만 부른다
	});

	it('연결이 준비되면 두 목록을 불러온다', async () => {
		render(AdminPage, { params: { id: '7' }, data: DATA });
		await act(() => server().onReady());
		expect(await screen.findByText('박민수')).toBeTruthy();
		expect(screen.getByText('349498')).toBeTruthy();
		expect(api.fetchJoinRequests).toHaveBeenCalledWith(7);
		expect(api.fetchPendingAuth).toHaveBeenCalledWith(7);
	});

	it('새 입장 요청 이벤트가 오면 새로고침 없이 입장 요청만 다시 불러온다 (AC40)', async () => {
		render(AdminPage, { params: { id: '7' }, data: DATA });
		await act(() => server().onReady());
		await screen.findByText('박민수');
		api.fetchJoinRequests.mockResolvedValue([...REQUESTS, { ...REQUESTS[0], id: 2, name: '최지은', student_no: '2' }]);
		await act(() => server().onEvent({ type: 'join_request.created', id: 2 }));
		expect(await screen.findByText('최지은')).toBeTruthy();
		expect(api.fetchPendingAuth).toHaveBeenCalledTimes(1); // 대기 중인 인증은 다시 부르지 않는다(코드 열람 기록이 늘지 않게)
	});

	it('대기 중인 인증 이벤트가 오면 그 목록만 다시 불러온다 (AC45)', async () => {
		render(AdminPage, { params: { id: '7' }, data: DATA });
		await act(() => server().onReady());
		await screen.findByText('349498');
		api.fetchPendingAuth.mockResolvedValue([{ ...PENDING[0], status: 'used', used_at: '2026-03-02T05:07:00+00:00', code: undefined }]);
		await act(() => server().onEvent({ type: 'pending_auth.updated', id: 11 }));
		expect(await screen.findByText(/사용됨/)).toBeTruthy();
		expect(api.fetchJoinRequests).toHaveBeenCalledTimes(1);
	});

	it('명단이 바뀌었다는 이벤트가 오면 명단을 다시 불러온다', async () => {
		render(AdminPage, { params: { id: '7' }, data: DATA });
		await act(() => server().onReady());
		await act(() => server().onEvent({ type: 'roster.updated' }));
		expect(nav.invalidate).toHaveBeenCalledWith('app:roster');
	});

	it('resync가 오면(이벤트가 밀렸다) 모두 다시 불러온다', async () => {
		render(AdminPage, { params: { id: '7' }, data: DATA });
		await act(() => server().onReady());
		await act(() => server().onEvent({ type: 'resync' }));
		await waitFor(() => expect(api.fetchPendingAuth).toHaveBeenCalledTimes(2));
		expect(api.fetchJoinRequests).toHaveBeenCalledTimes(2);
		expect(nav.invalidate).toHaveBeenCalledWith('app:roster');
	});

	it('연결이 끊기면 다시 연결 중이라고 알리고, 다시 연결되면 안내를 거둔다', async () => {
		render(AdminPage, { params: { id: '7' }, data: DATA });
		await act(() => server().onReady());
		await act(() => server().onStatus('reconnecting'));
		const banner = screen.getByText(/실시간 연결이 끊겼습니다. 다시 연결하는 중입니다./);
		expect(banner.closest('[role="status"]')).toBeTruthy(); // 읽어 주는 도구에도 알린다
		await act(() => server().onStatus('live'));
		expect(screen.queryByText(/실시간 연결이 끊겼습니다/)).toBeNull();
	});

	it('한 번도 연결되지 못하면 목록은 한 번 불러와 보여 준다', async () => {
		render(AdminPage, { params: { id: '7' }, data: DATA });
		await act(() => server().onStatus('never-connected'));
		expect(await screen.findByText('박민수')).toBeTruthy();
		expect(screen.getByText('349498')).toBeTruthy();
	});

	it('목록을 불러오지 못하면 그 구역에 이유와 할 일을 보인다', async () => {
		api.fetchJoinRequests.mockRejectedValue(new TypeError('Failed to fetch'));
		render(AdminPage, { params: { id: '7' }, data: DATA });
		await act(() => server().onReady());
		const alert = await screen.findByRole('alert');
		expect(alert.textContent).toContain('입장 요청을 불러오지 못했습니다.');
		expect(alert.textContent).toContain('다시 연결되면 자동으로 다시 불러옵니다.');
	});

	it('승인하면 입장 요청과 명단을 다시 불러온다 (AC41)', async () => {
		api.approveJoinRequest.mockResolvedValue({ id: 1, status: 'approved' });
		render(AdminPage, { params: { id: '7' }, data: DATA });
		await act(() => server().onReady());
		await fireEvent.click(await screen.findByRole('button', { name: '승인: 박민수 (20249999)' }));
		await waitFor(() => expect(api.fetchJoinRequests).toHaveBeenCalledTimes(2));
		expect(nav.invalidate).toHaveBeenCalledWith('app:roster');
	});

	it('화면을 떠나면 실시간 연결을 닫는다', () => {
		const { unmount } = render(AdminPage, { params: { id: '7' }, data: DATA });
		unmount();
		expect(live.stop).toHaveBeenCalled();
	});

	it('권한이 없는 화면에서는 연결하지 않는다', () => {
		render(AdminPage, { params: { id: '7' }, data: { me: null, classroom: null, roster: null, invite: null, sessions: null, notice: { status: 403, message: 'x' } } });
		expect(live.connectAdmin).not.toHaveBeenCalled();
	});
});
