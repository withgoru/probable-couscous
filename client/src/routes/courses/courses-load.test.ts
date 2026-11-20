import { describe, expect, it, vi } from 'vitest';
import { load } from './+page';

const BODY = { classrooms: [], counts: { active: 0, archived: 0 } };
const ok = () => Promise.resolve(new Response(JSON.stringify(BODY), { status: 200 }));

describe('내 강좌 load', () => {
	it('목록을 불러오고, 새로 만든 뒤 다시 불러올 수 있게 의존성을 등록한다', async () => {
		const depends = vi.fn();
		const fetch = vi.fn(ok);
		expect(await load({ fetch, depends } as never)).toEqual(BODY);
		expect(fetch).toHaveBeenCalledWith('/api/classrooms', expect.anything());
		expect(depends).toHaveBeenCalledWith('app:classrooms');
	});

	it('실패하면 오류로 올려 오류 화면이 안내한다', async () => {
		const fail = () => Promise.resolve(new Response('{"detail":"x"}', { status: 500 }));
		await expect(load({ fetch: fail, depends: vi.fn() } as never)).rejects.toThrow();
	});
});
