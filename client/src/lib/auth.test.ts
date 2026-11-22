import { isRedirect } from '@sveltejs/kit';
import { describe, expect, it, vi } from 'vitest';
import { loadSession, urlOutOfSync } from './auth';

const ME = { github_id: 101, login: 'kim' };
const loggedIn = () => Promise.resolve(new Response(JSON.stringify(ME), { status: 200 }));
const loggedOut = () => Promise.resolve(new Response('{}', { status: 401 }));
const at = (path: string) => new URL(path, 'http://localhost:8000');

async function redirectOf(promise: Promise<unknown>) {
	try {
		await promise;
	} catch (e) {
		if (isRedirect(e)) return { status: e.status, location: e.location };
		throw e;
	}
	return null;
}

describe('로그인 가드 (AC3)', () => {
	it('로그인되어 있으면 내 정보를 돌려준다', async () => {
		expect(await loadSession(loggedIn, at('/courses'))).toEqual({ me: ME });
	});

	it.each(['/courses', '/courses/42/admin', '/mypage', '/', '/something-unknown'])(
		'로그인하지 않은 채 %s를 열면 로그인 화면으로 보낸다',
		async (path) => {
			expect(await redirectOf(loadSession(loggedOut, at(path)))).toEqual({ status: 302, location: '/login' });
		}
	);

	it('로그인 화면은 로그인하지 않아도 열린다', async () => {
		expect(await loadSession(loggedOut, at('/login'))).toEqual({ me: null });
		expect(await loadSession(loggedOut, at('/login?error=not_allowed'))).toEqual({ me: null });
	});

	it('서버 오류는 로그인 화면으로 보내지 않고 오류로 올린다', async () => {
		const broken = () => Promise.resolve(new Response('{}', { status: 500 }));
		await expect(loadSession(broken, at('/courses'))).rejects.toThrow();
	});

	it('경로를 바꿔 가며 뚫을 수 없다: 쿼리와 해시에 login이 들어 있어도 보호된다', async () => {
		for (const path of ['/courses?next=/login', '/courses#/login', '/login/../courses', '/Login']) {
			const result = await redirectOf(loadSession(loggedOut, at(path)));
			expect(result, path).toEqual({ status: 302, location: '/login' });
		}
	});
});

describe('학생 입장 화면은 교수 로그인과 무관하다', () => {
	it('초대 링크 주소는 로그인하지 않아도 열리고 교수 로그인을 묻지도 않는다', async () => {
		const fetch = vi.fn(loggedOut);
		expect(await loadSession(fetch, at('/join/abcDEF_123-x'))).toEqual({ me: null });
		expect(fetch).not.toHaveBeenCalled();
	});

	it('교수로 로그인한 브라우저에서 열어도 학생 화면이라 교수 메뉴를 붙이지 않는다', async () => {
		expect(await loadSession(loggedIn, at('/join/abc'))).toEqual({ me: null });
	});

	it.each(['/join', '/join/', '/joinx/abc', '/join/abc/extra'])('%s는 학생 입장 주소가 아니라 보호된다', async (path) => {
		expect(await redirectOf(loadSession(loggedOut, at(path)))).toEqual({ status: 302, location: '/login' });
	});
});

describe('루트 레이아웃이 가드를 쓴다', () => {
	it('load가 loadSession을 거친다', async () => {
		const { load, ssr } = await import('../routes/+layout');
		expect(ssr).toBe(false);
		const fetch = vi.fn(loggedOut);
		const result = await redirectOf(Promise.resolve(load({ fetch, url: at('/courses') } as never)));
		expect(result).toEqual({ status: 302, location: '/login' });
		expect(fetch).toHaveBeenCalledWith('/api/me', expect.anything());
	});
});

describe('뒤로 가기 뒤 주소 맞추기 (AC4)', () => {
	const shown = new URL('http://localhost:8000/login');

	it('화면의 주소와 브라우저 주소가 같으면 맞출 필요가 없다', () => {
		expect(urlOutOfSync(shown, { pathname: '/login', search: '' })).toBe(false);
	});

	it('로그아웃 뒤 뒤로 가기: 브라우저는 /courses인데 화면은 /login이면 맞춘다', () => {
		expect(urlOutOfSync(shown, { pathname: '/courses', search: '' })).toBe(true);
	});

	it('쿼리가 다르면 맞춘다', () => {
		expect(urlOutOfSync(new URL('http://x/login?error=not_allowed'), { pathname: '/login', search: '' })).toBe(true);
	});

	it('해시는 비교하지 않는다', () => {
		expect(urlOutOfSync(shown, { pathname: '/login', search: '' })).toBe(false);
	});
});
