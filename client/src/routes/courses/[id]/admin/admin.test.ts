// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { load } from './+page';
import AdminPage from './+page.svelte';

afterEach(cleanup);

const reply = (status: number, body: unknown) => () =>
	Promise.resolve(new Response(JSON.stringify(body), { status }));
const params = (id: string) => ({ id });
const MINE = { id: 7, name: '알고리즘', section_name: null, status: 'active', student_count: 0, created_at: 'x' } as const;

describe('관리 페이지 load (AC8)', () => {
	it('내 강좌면 강좌를 돌려준다', async () => {
		const classroom = MINE;
		const fetch = vi.fn(reply(200, classroom));
		expect(await load({ fetch, params: params('7') } as never)).toEqual({ classroom, notice: null });
		expect(fetch).toHaveBeenCalledWith('/api/classrooms/7', expect.anything());
	});

	it('다른 교수의 강좌(403)는 오류 화면이 아니라 안내로 돌려준다', async () => {
		const result = await load({
			fetch: reply(403, { detail: '이 강좌를 볼 권한이 없습니다.' }),
			params: params('7')
		} as never);
		expect(result).toEqual({ classroom: null, notice: { status: 403, message: '이 강좌를 볼 권한이 없습니다.' } });
	});

	it('없는 강좌(404)도 안내로 돌려준다', async () => {
		const result = (await load({ fetch: reply(404, { detail: '찾을 수 없는 강좌입니다.' }), params: params('999') } as never)) as {
			notice: { status: number };
		};
		expect(result.notice.status).toBe(404);
	});

	it('숫자가 아닌 주소는 서버를 부르지 않고 없는 강좌로 본다', async () => {
		const fetch = vi.fn(reply(200, {}));
		const result = (await load({ fetch, params: params('abc') } as never)) as { notice: { status: number } };
		expect(result.notice.status).toBe(404);
		expect(fetch).not.toHaveBeenCalled();
	});

	it('서버 오류는 안내가 아니라 오류로 올린다', async () => {
		await expect(load({ fetch: reply(500, {}), params: params('7') } as never)).rejects.toThrow();
	});
});

describe('관리 페이지 화면', () => {
	it('권한이 없으면 AC8의 문구와 돌아갈 길을 보여 준다', () => {
		render(AdminPage, {
			params: { id: '7' },
			data: { me: null, classroom: null, notice: { status: 403, message: '이 강좌를 볼 권한이 없습니다.' } }
		});
		const alert = screen.getByRole('alert');
		expect(alert.textContent).toContain('이 강좌를 볼 권한이 없습니다');
		expect(alert.textContent).toContain('내 강좌');
		expect(screen.getByRole('link', { name: '내 강좌로 돌아가기' }).getAttribute('href')).toBe('/courses');
	});

	it('없는 강좌면 그렇게 알려 준다', () => {
		render(AdminPage, {
			params: { id: '7' },
			data: { me: null, classroom: null, notice: { status: 404, message: '찾을 수 없는 강좌입니다.' } }
		});
		expect(screen.getByRole('alert').textContent).toContain('찾을 수 없는 강좌입니다');
	});

	it('내 강좌면 이름이 보인다(내용은 T013에서 채운다)', () => {
		render(AdminPage, { params: { id: '7' },
			data: { me: null, classroom: MINE, notice: null } });
		expect(screen.getByRole('heading', { level: 1, name: '관리 페이지' })).toBeTruthy();
		expect(screen.getByText('알고리즘')).toBeTruthy();
		expect(screen.queryByRole('alert')).toBeNull();
	});
});
