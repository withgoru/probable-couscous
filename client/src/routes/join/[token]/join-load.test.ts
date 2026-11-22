import { describe, expect, it, vi } from 'vitest';
import { load } from './+page';

const reply = (status: number, body: unknown) =>
	Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));
const respond = (status: number, body: unknown) => () => reply(status, body);
const REVOKED = '이 링크는 더 이상 사용할 수 없습니다. 교수님께 새 링크를 받으세요.';
const ARCHIVED = '이 강좌는 보관되었습니다. 교수님께 문의해 주세요.';
const CLASSROOM = { name: '웹 프로그래밍', section_name: '월수반' };

/** 링크 열기와 내 상태를 주소로 나눠 답하는 가짜 fetch. */
function server(me: () => Promise<Response>) {
	const calls: string[] = [];
	const fetch = vi.fn((url: string) => {
		calls.push(url);
		return url.endsWith('/me') ? me() : reply(200, CLASSROOM);
	});
	return { fetch, calls };
}

describe('초대 링크 load (AC10, AC22)', () => {
	it('열린 강좌면 이름과 분반, 이 기기의 입장 상태를 돌려준다', async () => {
		const { fetch } = server(() => reply(200, { state: 'login' }));
		expect(await load({ fetch, params: { token: 'tok' } } as never)).toEqual({
			token: 'tok',
			invite: { open: true, classroom: CLASSROOM, me: { state: 'login' } }
		});
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

describe('로그인 유지와 다시 입장 (AC35, AC37)', () => {
	it('링크를 연 다음에 내 상태를 묻는다(링크 열기가 기기 쿠키를 심는다)', async () => {
		const { fetch, calls } = server(() => reply(200, { state: 'login' }));
		await load({ fetch, params: { token: 'tok' } } as never);
		expect(calls).toEqual(['/api/join/tok', '/api/join/tok/me']);
	});

	it('입장한 기기면 입장 완료 상태와 강좌 이름·닉네임을 돌려준다 (AC35)', async () => {
		const me = { state: 'entered', nickname: '느긋한 고래', classroom: '웹 프로그래밍' };
		const { fetch } = server(() => reply(200, me));
		const data = await load({ fetch, params: { token: 'tok' } } as never);
		expect(data).toMatchObject({ invite: { open: true, me } });
	});

	it('다른 강좌에서 인증한 기기면 안내 단계와 이 강좌의 닉네임을 돌려준다 (AC37)', async () => {
		const me = { state: 'notice', nickname: '용감한 수달', classroom: '웹 프로그래밍' };
		const { fetch } = server(() => reply(200, me));
		expect(await load({ fetch, params: { token: 'tok' } } as never)).toMatchObject({ invite: { open: true, me } });
	});

	it('내 상태를 묻다 실패하면 막지 않고 이메일 단계부터 시작한다', async () => {
		const { fetch } = server(() => reply(500, {}));
		expect(await load({ fetch, params: { token: 'tok' } } as never)).toMatchObject({ invite: { open: true, me: { state: 'login' } } });
		const offline = server(() => Promise.reject(new TypeError('network')));
		expect(await load({ fetch: offline.fetch, params: { token: 'tok' } } as never)).toMatchObject({ invite: { open: true, me: { state: 'login' } } });
	});

	it('내 상태를 묻는 사이 보관됐으면(403) 닫힌 화면을 보인다', async () => {
		const { fetch } = server(() => reply(403, { detail: ARCHIVED }));
		expect(await load({ fetch, params: { token: 'tok' } } as never)).toEqual({ token: 'tok', invite: { open: false, message: ARCHIVED } });
	});
});
