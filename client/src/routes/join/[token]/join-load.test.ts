import { describe, expect, it, vi } from 'vitest';
import { load } from './+page';

const respond = (status: number, body: unknown) => () =>
	Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));
const REVOKED = '이 링크는 더 이상 사용할 수 없습니다. 교수님께 새 링크를 받으세요.';
const ARCHIVED = '이 강좌는 보관되었습니다. 교수님께 문의해 주세요.';

describe('초대 링크 load (AC10, AC22)', () => {
	it('열린 강좌면 이름과 분반을 돌려준다', async () => {
		const fetch = vi.fn(respond(200, { name: '웹 프로그래밍', section_name: '월수반' }));
		expect(await load({ fetch, params: { token: 'tok' } } as never)).toEqual({
			token: 'tok',
			invite: { open: true, classroom: { name: '웹 프로그래밍', section_name: '월수반' } }
		});
		expect(fetch).toHaveBeenCalledWith('/api/join/tok', expect.anything());
	});

	it('폐기됐거나 틀린 링크(404)는 서버의 안내 문구로 닫힌 화면을 보인다', async () => {
		expect(await load({ fetch: respond(404, { detail: REVOKED }), params: { token: 'x' } } as never)).toEqual({
			token: 'x',
			invite: { open: false, message: REVOKED }
		});
	});

	it('보관된 강좌(403)도 서버의 안내 문구로 닫힌 화면을 보인다', async () => {
		expect(await load({ fetch: respond(403, { detail: ARCHIVED }), params: { token: 'x' } } as never)).toEqual({
			token: 'x',
			invite: { open: false, message: ARCHIVED }
		});
	});

	it('서버 오류나 연결 문제는 오류 화면이 안내하도록 올린다', async () => {
		await expect(load({ fetch: respond(500, {}), params: { token: 'x' } } as never)).rejects.toThrow();
		await expect(load({ fetch: () => Promise.reject(new TypeError('network')), params: { token: 'x' } } as never)).rejects.toThrow();
	});
});
