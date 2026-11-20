import { describe, expect, it, vi } from 'vitest';
import { ApiError, cloneClassroom, createClassroom, fetchClassroom, fetchClassrooms, fetchMe, fetchMySummary, fetchRoster, addStudent, importRoster, logout } from './api';

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

const ITEM = { id: 7, name: '알고리즘', section_name: '월수반', status: 'active', student_count: 0, created_at: 'x' };

describe('fetchClassrooms', () => {
	it('목록과 개수를 돌려준다', async () => {
		const body = { classrooms: [ITEM], counts: { active: 1, archived: 0 } };
		const fetch = vi.fn(() => json(200, body));
		expect(await fetchClassrooms(fetch)).toEqual(body);
		expect(fetch).toHaveBeenCalledWith('/api/classrooms', expect.objectContaining({ credentials: 'same-origin' }));
	});

	it('실패하면 서버가 준 한국어 안내를 담은 ApiError를 올린다', async () => {
		const err = await fetchClassrooms(() => json(401, { detail: '로그인이 필요합니다.' })).catch((e) => e);
		expect(err).toBeInstanceOf(ApiError);
		expect(err.status).toBe(401);
		expect(err.message).toBe('로그인이 필요합니다.');
	});

	it('안내가 없는 오류도 상태 번호가 있는 ApiError다', async () => {
		const err = await fetchClassrooms(() => Promise.resolve(new Response('oops', { status: 502 }))).catch((e) => e);
		expect(err).toBeInstanceOf(ApiError);
		expect(err.status).toBe(502);
		expect(err.message).toContain('502');
	});
});

describe('createClassroom', () => {
	it('이름과 분반을 JSON으로 보내고 만든 강좌를 돌려준다', async () => {
		const fetch = vi.fn(() => json(201, ITEM));
		expect(await createClassroom({ name: '알고리즘', section_name: '월수반' }, fetch)).toEqual(ITEM);
		const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
		expect(url).toBe('/api/classrooms');
		expect(init.method).toBe('POST');
		expect(JSON.parse(init.body as string)).toEqual({ name: '알고리즘', section_name: '월수반' });
		expect((init.headers as Record<string, string>)['Content-Type']).toBe('application/json');
	});

	it('422이면 서버의 한국어 문장이 그대로 메시지가 된다', async () => {
		const err = await createClassroom({ name: ' ' }, () => json(422, { detail: '강좌 이름을 입력해 주세요.' })).catch((e) => e);
		expect(err).toBeInstanceOf(ApiError);
		expect(err.status).toBe(422);
		expect(err.message).toBe('강좌 이름을 입력해 주세요.');
	});

	it('연결 실패는 ApiError가 아닌 오류로 올라간다', async () => {
		const err = await createClassroom({ name: 'x' }, () => Promise.reject(new TypeError('network'))).catch((e) => e);
		expect(err).not.toBeInstanceOf(ApiError);
	});
});

describe('fetchClassroom', () => {
	it('한 강좌를 돌려준다', async () => {
		const fetch = vi.fn(() => json(200, ITEM));
		expect(await fetchClassroom(7, fetch)).toEqual(ITEM);
		expect(fetch).toHaveBeenCalledWith('/api/classrooms/7', expect.anything());
	});

	it('권한이 없으면 403과 안내를 담은 ApiError다 (AC8)', async () => {
		const err = await fetchClassroom(7, () => json(403, { detail: '이 강좌를 볼 권한이 없습니다.' })).catch((e) => e);
		expect(err.status).toBe(403);
		expect(err.message).toBe('이 강좌를 볼 권한이 없습니다.');
	});
});

describe('cloneClassroom', () => {
	it('원본 번호의 복제 경로로 이름과 분반을 보내고 만든 강좌를 돌려준다', async () => {
		const fetch = vi.fn(() => json(201, { ...ITEM, id: 8 }));
		expect(await cloneClassroom(7, { name: '알고리즘', section_name: null }, fetch)).toEqual({ ...ITEM, id: 8 });
		const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
		expect(url).toBe('/api/classrooms/7/clone');
		expect(init.method).toBe('POST');
		expect(JSON.parse(init.body as string)).toEqual({ name: '알고리즘', section_name: null });
	});

	it('권한이 없으면 서버의 한국어 안내를 담은 ApiError다', async () => {
		const err = await cloneClassroom(7, { name: 'x' }, () => json(403, { detail: '이 강좌를 볼 권한이 없습니다.' })).catch((e) => e);
		expect(err).toBeInstanceOf(ApiError);
		expect(err.status).toBe(403);
		expect(err.message).toBe('이 강좌를 볼 권한이 없습니다.');
	});
});

describe('fetchMySummary', () => {
	const BODY = {
		github_id: 101, login: 'kim', counts: { active: 1, archived: 0 }, active_students: 0, active_classrooms: [ITEM]
	};

	it('마이페이지 요약을 돌려준다', async () => {
		const fetch = vi.fn(() => json(200, BODY));
		expect(await fetchMySummary(fetch)).toEqual(BODY);
		expect(fetch).toHaveBeenCalledWith('/api/me/summary', expect.objectContaining({ credentials: 'same-origin' }));
	});

	it('실패하면 ApiError를 올린다', async () => {
		const err = await fetchMySummary(() => json(401, { detail: '로그인이 필요합니다.' })).catch((e) => e);
		expect(err).toBeInstanceOf(ApiError);
		expect(err.status).toBe(401);
	});
});

describe('명단 API', () => {
	const ROSTER = { entries: [{ id: 1, student_no: '1', name: '김', email: 'a@x.kr', entered: false }], count: 1, limit: 200 };

	it('fetchRoster는 명단을 돌려준다', async () => {
		const fetch = vi.fn(() => json(200, ROSTER));
		expect(await fetchRoster(7, fetch)).toEqual(ROSTER);
		expect(fetch).toHaveBeenCalledWith('/api/classrooms/7/roster', expect.objectContaining({ credentials: 'same-origin' }));
	});

	it('addStudent는 JSON으로 보내고 추가된 학생을 돌려준다', async () => {
		const fetch = vi.fn(() => json(201, { id: 5, student_no: '1', name: '김', email: 'a@x.kr' }));
		const input = { student_no: '1', name: '김', email: 'a@x.kr' };
		expect((await addStudent(7, input, fetch)).id).toBe(5);
		expect(fetch).toHaveBeenCalledWith(
			'/api/classrooms/7/roster',
			expect.objectContaining({ method: 'POST', body: JSON.stringify(input) })
		);
	});

	it('칸에 대한 오류는 field와 안내를 담은 ApiError다', async () => {
		const err = await addStudent(7, { student_no: '1', name: '김', email: 'x' }, () =>
			json(422, { detail: { field: 'email', message: '이메일 형식을 확인해 주세요.' } })
		).catch((e) => e);
		expect(err).toBeInstanceOf(ApiError);
		expect(err.field).toBe('email');
		expect(err.message).toBe('이메일 형식을 확인해 주세요.');
	});

	it('칸이 없는 오류(200명 초과)는 field가 null이다', async () => {
		const err = await importRoster(7, new File(['x'], 'a.csv'), () =>
			json(422, { detail: { field: null, message: '명단은 200명까지 등록할 수 있습니다. 3명을 줄여 다시 올려 주세요.' } })
		).catch((e) => e);
		expect(err.field).toBeNull();
		expect(err.message).toContain('200명까지');
	});

	it('문자열 detail은 field가 없다', async () => {
		const err = await fetchRoster(7, () => json(403, { detail: '이 강좌를 볼 권한이 없습니다.' })).catch((e) => e);
		expect(err.field).toBeUndefined();
		expect(err.message).toBe('이 강좌를 볼 권한이 없습니다.');
	});

	it('importRoster는 파일을 그대로 text/csv 본문으로 보낸다', async () => {
		const result = { added: 2, skipped: 1, skipped_lines: [{ line: 3, reason: '빈 칸' }] };
		const fetch = vi.fn(() => json(200, result));
		const file = new File(['학번,이름,이메일\n'], 'a.csv', { type: 'text/csv' });
		expect(await importRoster(7, file, fetch)).toEqual(result);
		const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
		expect(url).toBe('/api/classrooms/7/roster/import');
		expect(init.method).toBe('POST');
		expect(init.body).toBe(file);
		expect((init.headers as Record<string, string>)['Content-Type']).toBe('text/csv');
	});

	it('칸 정보가 없는 객체 detail은 field가 null이다', async () => {
		const err = await fetchRoster(7, () => json(422, { detail: { message: '안내' } })).catch((e) => e);
		expect(err.field).toBeNull();
	});
});
