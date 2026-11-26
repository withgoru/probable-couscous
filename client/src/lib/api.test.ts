import { describe, expect, it, vi } from 'vitest';
import { ApiError, archiveClassroom, createSession, deleteSession, endSession, fetchClassLive, fetchDeckNotes, retractItem, sendItem, removeDeck, resumeSession, startSession, uploadDeck, fetchSessions, renameSession, cloneClassroom, createClassroom, fetchClassroom, fetchClassrooms, fetchMe, fetchMySummary, fetchRoster, addStudent, importRoster, fetchInvite, regenerateInvite, logout, openInvite, submitJoinEmail, requestAccess, verifyCode, resendCode, notifyProfessor, fetchJoinState, enterClassroom, removeStudent, revokeStudentLogin } from './api';

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

const ITEM = { id: 7, name: '알고리즘', section_name: '월수반', status: 'active', student_count: 0, session_count: 0, created_at: 'x' };

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

describe('archiveClassroom', () => {
	it('수업 중이라 거절되면 안내와 진행 중인 회차 번호를 담은 ApiError다 (002 AC46)', async () => {
		const detail = '1회차 수업이 진행 중입니다. 수업을 끝낸 뒤 보관해 주세요.';
		const err = await archiveClassroom(7, () => json(409, { detail, live_session_id: 12 })).catch((e) => e);
		expect(err).toBeInstanceOf(ApiError);
		expect(err.status).toBe(409);
		expect(err.message).toBe(detail);
		expect(err.data).toEqual({ live_session_id: 12 });
	});

	it('이미 보관된 강좌면 덧붙은 값 없이 안내만 담는다', async () => {
		const err = await archiveClassroom(7, () => json(409, { detail: '이미 보관된 강좌입니다.' })).catch((e) => e);
		expect(err.message).toBe('이미 보관된 강좌입니다.');
		expect(err.data).toBeUndefined();
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

describe('초대 링크 API', () => {
	const INVITE = { token: 'abc', url: 'http://localhost:8000/join/abc' };

	it('fetchInvite는 링크를 돌려준다', async () => {
		const fetch = vi.fn(() => json(200, INVITE));
		expect(await fetchInvite(7, fetch)).toEqual(INVITE);
		expect(fetch).toHaveBeenCalledWith('/api/classrooms/7/invite', expect.objectContaining({ credentials: 'same-origin' }));
	});

	it('regenerateInvite는 POST로 새 링크를 받는다', async () => {
		const fetch = vi.fn(() => json(200, { token: 'new', url: 'http://localhost:8000/join/new' }));
		expect((await regenerateInvite(7, fetch)).token).toBe('new');
		expect(fetch).toHaveBeenCalledWith(
			'/api/classrooms/7/invite/regenerate',
			expect.objectContaining({ method: 'POST', credentials: 'same-origin' })
		);
	});

	it('실패하면 서버의 안내를 담은 ApiError를 올린다', async () => {
		const err = await regenerateInvite(7, () => json(403, { detail: '이 강좌를 볼 권한이 없습니다.' })).catch((e) => e);
		expect(err).toBeInstanceOf(ApiError);
		expect(err.message).toBe('이 강좌를 볼 권한이 없습니다.');
	});
});

describe('학생 입장 API', () => {
	it('openInvite는 강좌 이름을 받아 온다(기기 쿠키를 받으려고 같은 출처 쿠키를 쓴다)', async () => {
		const fetch = vi.fn(() => json(200, { name: '웹', section_name: null }));
		expect(await openInvite('tok', fetch)).toEqual({ name: '웹', section_name: null });
		expect(fetch).toHaveBeenCalledWith('/api/join/tok', expect.objectContaining({ credentials: 'same-origin' }));
	});

	it('토큰은 주소에 안전하게 넣는다', async () => {
		const fetch = vi.fn(() => json(200, { name: '웹', section_name: null }));
		await openInvite('a/b?c', fetch);
		expect(fetch).toHaveBeenCalledWith('/api/join/a%2Fb%3Fc', expect.anything());
	});

	it('폐기된 링크와 보관된 강좌는 서버의 안내를 담은 ApiError다', async () => {
		const revoked = await openInvite('t', () => json(404, { detail: '이 링크는 더 이상 사용할 수 없습니다. 교수님께 새 링크를 받으세요.' })).catch((e) => e);
		expect(revoked).toBeInstanceOf(ApiError);
		expect([revoked.status, revoked.message]).toEqual([404, '이 링크는 더 이상 사용할 수 없습니다. 교수님께 새 링크를 받으세요.']);
		const archived = await openInvite('t', () => json(403, { detail: '이 강좌는 보관되었습니다. 교수님께 문의해 주세요.' })).catch((e) => e);
		expect([archived.status, archived.message]).toEqual([403, '이 강좌는 보관되었습니다. 교수님께 문의해 주세요.']);
	});

	it('submitJoinEmail은 이메일을 보내고 다음 단계를 돌려준다', async () => {
		const fetch = vi.fn((..._a: unknown[]) => json(200, { next: 'code', wait_seconds: 60 }));
		expect(await submitJoinEmail('tok', 'kim@x.kr', fetch)).toEqual({ next: 'code', wait_seconds: 60 });
		const [url, init] = fetch.mock.calls[0] as [string, RequestInit];
		expect(url).toBe('/api/join/tok/email');
		expect(init.method).toBe('POST');
		expect(JSON.parse(init.body as string)).toEqual({ email: 'kim@x.kr' });
	});

	it('submitJoinEmail의 칸 오류는 어느 칸인지와 함께 올린다', async () => {
		const err = await submitJoinEmail('t', 'x', () => json(422, { detail: { field: 'email', message: '이메일 형식을 확인해 주세요.' } })).catch((e) => e);
		expect([err.status, err.field, err.message]).toEqual([422, 'email', '이메일 형식을 확인해 주세요.']);
	});

	it('requestAccess는 이메일, 이름, 학번을 보내고 결과를 돌려준다(새 요청 201, 그 밖 200)', async () => {
		const fetch = vi.fn((..._a: unknown[]) => json(201, { next: 'requested', message: '요청을 보냈습니다.' }));
		const answer = await requestAccess('tok', { email: 'a@x.kr', name: '박민수', student_no: '2024' }, fetch);
		expect(answer).toEqual({ next: 'requested', message: '요청을 보냈습니다.' });
		const [url, init] = fetch.mock.calls[0] as [string, RequestInit];
		expect(url).toBe('/api/join/tok/request-access');
		expect(JSON.parse(init.body as string)).toEqual({ email: 'a@x.kr', name: '박민수', student_no: '2024' });
		expect(await requestAccess('t', { email: 'a', name: 'b', student_no: 'c' }, () => json(200, { next: 'rejected', message: 'm' }))).toEqual({ next: 'rejected', message: 'm' });
	});
});

describe('코드 단계 API', () => {
	it('verifyCode는 이메일, 코드, 로그인 유지 선택을 보내고 닉네임을 돌려준다', async () => {
		const fetch = vi.fn((..._a: unknown[]) => json(200, { next: 'notice', nickname: '느긋한 고래' }));
		expect(await verifyCode('tok', { email: 'kim@x.kr', code: '123456', keep_login: true }, fetch)).toEqual({ next: 'notice', nickname: '느긋한 고래' });
		const [url, init] = fetch.mock.calls[0] as [string, RequestInit];
		expect(url).toBe('/api/join/tok/code');
		expect(init.credentials).toBe('same-origin'); // 기기 쿠키를 보내고 로그인 쿠키를 받는다
		expect(JSON.parse(init.body as string)).toEqual({ email: 'kim@x.kr', code: '123456', keep_login: true });
	});

	it('틀린 코드는 남은 횟수와 결과 종류를 ApiError.data에 담는다', async () => {
		const detail = { field: 'code', message: '코드가 맞지 않습니다. 4번 더 입력할 수 있습니다.', outcome: 'wrong', remaining: 4 };
		const err = await verifyCode('t', { email: 'a', code: '1', keep_login: true }, () => json(422, { detail })).catch((e) => e);
		expect([err.status, err.field, err.message]).toEqual([422, 'code', detail.message]);
		expect(err.data).toEqual({ outcome: 'wrong', remaining: 4 });
	});

	it('resendCode는 다시 받기를 보내고, 너무 빠르면 남은 초를 data에 담는다', async () => {
		const fetch = vi.fn((..._a: unknown[]) => json(200, { next: 'code', wait_seconds: 60 }));
		expect(await resendCode('tok', 'kim@x.kr', fetch)).toEqual({ next: 'code', wait_seconds: 60 });
		expect(fetch.mock.calls[0][0]).toBe('/api/join/tok/resend');
		const err = await resendCode('t', 'a', () => json(429, { detail: { field: null, message: '코드는 7초 뒤에 다시 받을 수 있습니다.', wait_seconds: 7 } })).catch((e) => e);
		expect([err.status, err.message, err.data]).toEqual([429, '코드는 7초 뒤에 다시 받을 수 있습니다.', { wait_seconds: 7 }]);
	});

	it('notifyProfessor는 교수님께 알리고 안내 문구를 돌려준다', async () => {
		const fetch = vi.fn((..._a: unknown[]) => json(200, { next: 'notified', message: '교수님께 알렸습니다.' }));
		expect(await notifyProfessor('tok', 'kim@x.kr', fetch)).toEqual({ next: 'notified', message: '교수님께 알렸습니다.' });
		const [url, init] = fetch.mock.calls[0] as [string, RequestInit];
		expect(url).toBe('/api/join/tok/notify-professor');
		expect(JSON.parse(init.body as string)).toEqual({ email: 'kim@x.kr' });
	});
});

describe('입장 상태와 입장 확정 API', () => {
	it('fetchJoinState는 이 기기의 이 강좌 상태를 받아 온다', async () => {
		const fetch = vi.fn(() => json(200, { state: 'entered', nickname: 'n', classroom: '웹' }));
		expect(await fetchJoinState('tok', fetch)).toEqual({ state: 'entered', nickname: 'n', classroom: '웹' });
		expect(fetch).toHaveBeenCalledWith('/api/join/tok/me', expect.objectContaining({ credentials: 'same-origin' }));
	});

	it('enterClassroom은 확인하고 입장을 보내고 강좌 이름과 닉네임을 돌려준다', async () => {
		const fetch = vi.fn((..._a: unknown[]) => json(200, { next: 'entered', nickname: 'n', classroom: '웹' }));
		expect(await enterClassroom('tok', fetch)).toEqual({ next: 'entered', nickname: 'n', classroom: '웹' });
		const [url, init] = fetch.mock.calls[0] as [string, RequestInit];
		expect([url, init.method, init.credentials]).toEqual(['/api/join/tok/enter', 'POST', 'same-origin']);
	});

	it('입장 확정이 거부되면 서버의 안내를 담은 ApiError다', async () => {
		const err = await enterClassroom('t', () => json(401, { detail: '입장 인증이 끝나지 않았습니다. 이메일과 코드로 먼저 인증해 주세요.' })).catch((e) => e);
		expect([err.status, err.message]).toEqual([401, '입장 인증이 끝나지 않았습니다. 이메일과 코드로 먼저 인증해 주세요.']);
	});
});

describe('빼기와 로그인 끊기 API', () => {
	it('removeStudent는 그 학생의 명단 항목을 DELETE로 뺀다', async () => {
		const fetch = vi.fn((..._a: unknown[]) => json(200, { id: 3, removed: true }));
		expect(await removeStudent(7, 3, fetch)).toEqual({ id: 3, removed: true });
		const [url, init] = fetch.mock.calls[0] as [string, RequestInit];
		expect([url, init.method, init.credentials]).toEqual(['/api/classrooms/7/roster/3', 'DELETE', 'same-origin']);
	});

	it('revokeStudentLogin은 로그인 끊기를 POST로 보낸다', async () => {
		const fetch = vi.fn((..._a: unknown[]) => json(200, { id: 3, revoked: true }));
		expect(await revokeStudentLogin(7, 3, fetch)).toEqual({ id: 3, revoked: true });
		const [url, init] = fetch.mock.calls[0] as [string, RequestInit];
		expect([url, init.method]).toEqual(['/api/classrooms/7/roster/3/revoke-login', 'POST']);
	});

	it('거부되면 서버의 안내를 담은 ApiError다', async () => {
		const err = await removeStudent(7, 3, () => json(404, { detail: { field: null, message: '명단에서 찾을 수 없는 학생입니다.' } })).catch((e) => e);
		expect([err.status, err.message]).toEqual([404, '명단에서 찾을 수 없는 학생입니다.']);
	});
});

describe('회차 API (002 AC1~AC4)', () => {
	const SESSION = { id: 3, title: '1회차', status: 'scheduled', sort_order: 1, created_at: 'x', can_delete: true, deck: null };

	it('회차 목록을 받는다', async () => {
		const fetch = vi.fn(() => json(200, { items: [SESSION] }));
		expect(await fetchSessions(7, fetch)).toEqual([SESSION]);
		expect((fetch.mock.calls[0] as unknown as [string])[0]).toBe('/api/classrooms/7/sessions');
	});

	it('만들기는 이름을 보내고 만든 회차를 돌려준다', async () => {
		const fetch = vi.fn(() => json(201, SESSION));
		expect(await createSession(7, '1회차', fetch)).toEqual(SESSION);
		const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
		expect(url).toBe('/api/classrooms/7/sessions');
		expect(init.method).toBe('POST');
		expect(JSON.parse(init.body as string)).toEqual({ title: '1회차' });
	});

	it('이름 바꾸기는 PATCH로 보낸다', async () => {
		const fetch = vi.fn(() => json(200, { ...SESSION, title: '새 이름' }));
		expect((await renameSession(7, 3, '새 이름', fetch)).title).toBe('새 이름');
		const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
		expect(url).toBe('/api/classrooms/7/sessions/3');
		expect(init.method).toBe('PATCH');
		expect(JSON.parse(init.body as string)).toEqual({ title: '새 이름' });
	});

	it('삭제는 DELETE로 보내고 거절되면 서버 안내를 담는다', async () => {
		const ok = vi.fn(() => Promise.resolve(new Response(null, { status: 204 })));
		await deleteSession(7, 3, ok);
		const [url, init] = ok.mock.calls[0] as unknown as [string, RequestInit];
		expect(url).toBe('/api/classrooms/7/sessions/3');
		expect(init.method).toBe('DELETE');
		const err = await deleteSession(7, 3, () => json(409, { detail: '한 번이라도 시작한 회차는 삭제할 수 없습니다.' })).catch((e) => e);
		expect(err).toBeInstanceOf(ApiError);
		expect(err.message).toBe('한 번이라도 시작한 회차는 삭제할 수 없습니다.');
	});
});

describe('슬라이드 묶음과 수업 시작 API (002 AC5~AC10, AC40)', () => {
	const DECK = { id: 9, original_name: '3주차.zip', slide_count: 12, size_bytes: 100, uploaded_at: 'x', available: true };

	it('묶음은 zip 본문 그대로 PUT하고 파일 이름은 주소에 붙인다', async () => {
		const fetch = vi.fn(() => json(200, { deck: DECK }));
		const file = new File(['zip'], '3주차 슬라이드.zip', { type: 'application/zip' });
		expect(await uploadDeck(7, 3, file, fetch)).toEqual(DECK);
		const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
		expect(url).toBe('/api/classrooms/7/sessions/3/deck?filename=3%EC%A3%BC%EC%B0%A8%20%EC%8A%AC%EB%9D%BC%EC%9D%B4%EB%93%9C.zip');
		expect(init.method).toBe('PUT');
		expect(init.body).toBe(file);
		expect((init.headers as Record<string, string>)['Content-Type']).toBe('application/zip');
	});

	it('거절되면 서버 안내를 담은 ApiError다 (AC6)', async () => {
		const file = new File(['x'], 'a.zip');
		const bad = await uploadDeck(7, 3, file, () => json(422, { detail: '슬라이드 묶음을 읽을 수 없습니다.' })).catch((e) => e);
		expect(bad).toBeInstanceOf(ApiError);
		expect(bad.message).toBe('슬라이드 묶음을 읽을 수 없습니다.');
		const big = await uploadDeck(7, 3, file, () => json(413, { detail: '파일이 너무 큽니다. 100MB 이하로 올려 주세요.' })).catch((e) => e);
		expect(big.status).toBe(413);
	});

	it('지우기는 DELETE다', async () => {
		const fetch = vi.fn(() => Promise.resolve(new Response(null, { status: 204 })));
		await removeDeck(7, 3, fetch);
		const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
		expect(url).toBe('/api/classrooms/7/sessions/3/deck');
		expect(init.method).toBe('DELETE');
	});

	it('수업 시작과 이어서 하기는 POST이고, 다른 회차가 진행 중이면 그 회차 번호를 담는다 (AC10)', async () => {
		const fetch = vi.fn(() => json(200, { id: 3, status: 'live', version: 1 }));
		expect((await startSession(7, 3, fetch)).status).toBe('live');
		expect((fetch.mock.calls[0] as unknown as [string, RequestInit])[0]).toBe('/api/classrooms/7/sessions/3/start');
		await resumeSession(7, 3, fetch);
		expect((fetch.mock.calls[1] as unknown as [string, RequestInit])[0]).toBe('/api/classrooms/7/sessions/3/resume');
		expect((fetch.mock.calls[1] as unknown as [string, RequestInit])[1].method).toBe('POST');
		const busy = await startSession(7, 3, () => json(409, { detail: '1회차 수업이 진행 중입니다. 먼저 끝내 주세요.', live_session_id: 2 })).catch((e) => e);
		expect(busy.message).toBe('1회차 수업이 진행 중입니다. 먼저 끝내 주세요.');
		expect(busy.data).toEqual({ live_session_id: 2 });
	});
});

describe('발표자 노트 API (002 AC13, AC30)', () => {
	it('교수 전용 노트 주소에서 받는다', async () => {
		const NOTES = { deck_id: 9, slide_count: 2, slides: [{ no: 1, title: '인사', note: '노트 1' }, { no: 2, title: '', note: '' }] };
		const fetch = vi.fn(() => json(200, NOTES));
		expect(await fetchDeckNotes(7, 3, fetch)).toEqual(NOTES);
		expect((fetch.mock.calls[0] as unknown as [string])[0]).toBe('/api/classrooms/7/sessions/3/deck/notes');
	});
});

describe('보내기·거두기 API (002 AC31, AC35)', () => {
	const ITEM_SENT = { id: 4, body: '과제', url: null, created_at: 'x', retracted_at: null };

	it('보내기는 글·링크·client_key를 보내고 저장된 항목을 돌려준다', async () => {
		const fetch = vi.fn(() => json(201, { item: ITEM_SENT, version: 5 }));
		expect(await sendItem(7, 3, { body: '과제', url: null, client_key: 'k1' }, fetch)).toEqual(ITEM_SENT);
		const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
		expect(url).toBe('/api/classrooms/7/sessions/3/items');
		expect(init.method).toBe('POST');
		expect(JSON.parse(init.body as string)).toEqual({ body: '과제', url: null, client_key: 'k1' });
	});

	it('칸 오류는 그 칸 이름과 안내를 담는다', async () => {
		const err = await sendItem(7, 3, { body: null, url: 'x', client_key: 'k' }, () =>
			json(422, { detail: { field: 'url', message: '링크는 http:// 또는 https://로 시작해야 합니다.' } })
		).catch((e) => e);
		expect(err).toBeInstanceOf(ApiError);
		expect(err.field).toBe('url');
		expect(err.message).toBe('링크는 http:// 또는 https://로 시작해야 합니다.');
	});

	it('거두기는 그 항목 주소로 POST한다', async () => {
		const fetch = vi.fn(() => json(200, { item: { ...ITEM_SENT, retracted_at: 'y' }, version: 6 }));
		expect((await retractItem(7, 3, 4, fetch)).retracted_at).toBe('y');
		const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
		expect(url).toBe('/api/classrooms/7/sessions/3/items/4/retract');
		expect(init.method).toBe('POST');
	});
});

describe('수업 종료 API (002 AC37)', () => {
	it('종료 주소로 POST하고 끝난 회차를 돌려준다', async () => {
		const fetch = vi.fn(() => json(200, { id: 3, status: 'ended', version: 7 }));
		expect((await endSession(7, 3, fetch)).status).toBe('ended');
		const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
		expect(url).toBe('/api/classrooms/7/sessions/3/end');
		expect(init.method).toBe('POST');
	});
});

describe('회차 상태 API (002 AC39)', () => {
	it('그 회차의 상태를 받는다', async () => {
		const fetch = vi.fn(() => json(200, { session: { id: 4 } }));
		expect((await fetchClassLive(7, 4, fetch)).session.id).toBe(4);
		expect((fetch.mock.calls[0] as unknown as [string])[0]).toBe('/api/class/7/sessions/4/live');
	});
});
