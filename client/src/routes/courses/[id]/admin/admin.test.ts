// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

const nav = vi.hoisted(() => ({ invalidate: vi.fn(() => Promise.resolve()) }));
const api = vi.hoisted(() => ({ addStudent: vi.fn() }));
vi.mock('$app/navigation', () => nav);
vi.mock('#lib/api.js', async (original) => ({ ...(await original<object>()), addStudent: api.addStudent }));

import { fireEvent, waitFor } from '@testing-library/svelte';
import { load } from './+page';
import AdminPage from './+page.svelte';

afterEach(cleanup);

const reply = (status: number, body: unknown) => () =>
	Promise.resolve(new Response(JSON.stringify(body), { status }));
const params = (id: string) => ({ id });
const ROSTER = { entries: [], count: 0, limit: 200 };
// 강좌와 명단을 주소로 구분해 답한다
const routed = (classroom: () => Response | Promise<Response>, roster: () => Response | Promise<Response> = () => new Response(JSON.stringify(ROSTER))) =>
	vi.fn((url: string) => Promise.resolve(url.endsWith('/roster') ? roster() : classroom()));
const res = (status: number, body: unknown) => () => new Response(JSON.stringify(body), { status });
const MINE = { id: 7, name: '알고리즘', section_name: null, status: 'active', student_count: 0, created_at: 'x' } as const;

describe('관리 페이지 load (AC8)', () => {
	it('내 강좌면 강좌를 돌려준다', async () => {
		const classroom = MINE;
		const fetch = routed(res(200, classroom));
		expect(await load({ fetch, params: params('7'), depends: vi.fn() } as never)).toEqual({
			classroom,
			roster: ROSTER,
			notice: null
		});
		expect(fetch).toHaveBeenCalledWith('/api/classrooms/7', expect.anything());
		expect(fetch).toHaveBeenCalledWith('/api/classrooms/7/roster', expect.anything());
	});

	it('명단을 다시 불러올 수 있게 의존성을 등록한다', async () => {
		const depends = vi.fn();
		await load({ fetch: routed(res(200, MINE)), params: params('7'), depends } as never);
		expect(depends).toHaveBeenCalledWith('app:roster');
	});

	it('다른 교수의 강좌(403)는 오류 화면이 아니라 안내로 돌려준다', async () => {
		const fetch = routed(res(403, { detail: '이 강좌를 볼 권한이 없습니다.' }), res(403, { detail: '이 강좌를 볼 권한이 없습니다.' }));
		const result = await load({ fetch, params: params('7'), depends: vi.fn() } as never);
		expect(result).toEqual({
			classroom: null,
			roster: null,
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

	it('명단을 불러오지 못하면 오류로 올린다', async () => {
		const fetch = routed(res(200, MINE), res(500, {}));
		await expect(load({ fetch, params: params('7'), depends: vi.fn() } as never)).rejects.toThrow();
	});
});

describe('관리 페이지 화면', () => {
	it('권한이 없으면 AC8의 문구와 돌아갈 길을 보여 준다', () => {
		render(AdminPage, {
			params: { id: '7' },
			data: { me: null, classroom: null, roster: null, notice: { status: 403, message: '이 강좌를 볼 권한이 없습니다.' } }
		});
		const alert = screen.getByRole('alert');
		expect(alert.textContent).toContain('이 강좌를 볼 권한이 없습니다');
		expect(alert.textContent).toContain('내 강좌');
		expect(screen.getByRole('link', { name: '내 강좌로 돌아가기' }).getAttribute('href')).toBe('/courses');
	});

	it('없는 강좌면 그렇게 알려 준다', () => {
		render(AdminPage, {
			params: { id: '7' },
			data: { me: null, classroom: null, roster: null, notice: { status: 404, message: '찾을 수 없는 강좌입니다.' } }
		});
		expect(screen.getByRole('alert').textContent).toContain('찾을 수 없는 강좌입니다');
	});

	it('내 강좌면 이름과 수강생 명단이 보인다', () => {
		render(AdminPage, { params: { id: '7' },
			data: { me: null, classroom: MINE, roster: ROSTER, notice: null } });
		expect(screen.getByRole('heading', { level: 1, name: '관리 페이지' })).toBeTruthy();
		expect(screen.getByText('알고리즘')).toBeTruthy();
		expect(screen.getByRole('heading', { level: 2, name: '수강생 명단' })).toBeTruthy();
		expect(screen.queryByRole('alert')).toBeNull();
	});

	it('권한이 없을 때는 명단 영역이 없다', () => {
		render(AdminPage, { params: { id: '7' },
			data: { me: null, classroom: null, roster: null, notice: { status: 403, message: 'x' } } });
		expect(screen.queryByRole('heading', { name: '수강생 명단' })).toBeNull();
	});

	it('학생을 추가하면 명단을 다시 불러온다(app:roster)', async () => {
		api.addStudent.mockResolvedValue({ id: 3, student_no: '3', name: '박', email: 'p@x.kr' });
		render(AdminPage, { params: { id: '7' }, data: { me: null, classroom: MINE, roster: ROSTER, notice: null } });
		for (const [l, v] of [['학번', '3'], ['이름', '박'], ['이메일', 'p@x.kr']]) {
			await fireEvent.input(screen.getByLabelText(l), { target: { value: v } });
		}
		await fireEvent.click(screen.getByRole('button', { name: '학생 추가' }));
		await waitFor(() => expect(nav.invalidate).toHaveBeenCalledWith('app:roster'));
	});
});
