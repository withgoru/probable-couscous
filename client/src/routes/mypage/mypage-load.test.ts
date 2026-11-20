import { describe, expect, it, vi } from 'vitest';
import { load } from './+page';

const BODY = { github_id: 1, login: 'kim', counts: { active: 0, archived: 0 }, active_students: 0, active_classrooms: [] };

describe('마이페이지 load', () => {
	it('요약을 불러온다', async () => {
		const fetch = vi.fn(() => Promise.resolve(new Response(JSON.stringify(BODY), { status: 200 })));
		expect(await load({ fetch } as never)).toEqual(BODY);
		expect(fetch).toHaveBeenCalledWith('/api/me/summary', expect.anything());
	});

	it('실패하면 오류로 올려 오류 화면이 안내한다', async () => {
		const fail = () => Promise.resolve(new Response('{"detail":"x"}', { status: 500 }));
		await expect(load({ fetch: fail } as never)).rejects.toThrow();
	});
});
