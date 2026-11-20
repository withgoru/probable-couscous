import { describe, expect, it, vi } from 'vitest';
import { fetchMe, logout } from './api';

const json = (status: number, body: unknown) =>
	Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));

describe('fetchMe', () => {
	it('로그인되어 있으면 내 정보를 돌려준다', async () => {
		const fetch = vi.fn(() => json(200, { github_id: 101, login: 'kim' }));
		expect(await fetchMe(fetch)).toEqual({ github_id: 101, login: 'kim' });
		expect(fetch).toHaveBeenCalledWith('/api/me', expect.objectContaining({ credentials: 'same-origin' }));
	});

	it('401이면 로그인하지 않은 것이라 null이다', async () => {
		expect(await fetchMe(() => json(401, { detail: '로그인이 필요합니다.' }))).toBeNull();
	});

	it('서버 오류(500)는 로그인하지 않은 것으로 보지 않고 오류로 올린다', async () => {
		await expect(fetchMe(() => json(500, {}))).rejects.toThrow();
	});

	it('연결이 안 되면 오류로 올린다', async () => {
		await expect(fetchMe(() => Promise.reject(new TypeError('network')))).rejects.toThrow();
	});
});

describe('logout', () => {
	it('POST /api/auth/logout을 보낸다', async () => {
		const fetch = vi.fn(() => Promise.resolve(new Response(null, { status: 204 })));
		await logout(fetch);
		expect(fetch).toHaveBeenCalledWith('/api/auth/logout', expect.objectContaining({ method: 'POST' }));
	});

	it('실패하면 오류로 올린다', async () => {
		await expect(logout(() => json(403, {}))).rejects.toThrow();
		await expect(logout(() => Promise.reject(new TypeError('network')))).rejects.toThrow();
	});
});
