export type Me = { github_id: number; login: string };

type FetchFn = typeof fetch;

/** 로그인한 교수의 정보. 로그인하지 않았으면(401) null. 서버 오류와 연결 실패는 오류로 올린다. */
export async function fetchMe(fetchFn: FetchFn): Promise<Me | null> {
	const res = await fetchFn('/api/me', {
		credentials: 'same-origin',
		headers: { Accept: 'application/json' }
	});
	if (res.status === 401) return null;
	if (!res.ok) throw new Error(`내 정보를 불러오지 못했습니다 (${res.status})`);
	return (await res.json()) as Me;
}

/** 서버의 로그인 상태를 지운다. 브라우저가 같은 출처의 POST에 Origin 헤더를 붙인다. */
export async function logout(fetchFn: FetchFn = fetch): Promise<void> {
	const res = await fetchFn('/api/auth/logout', { method: 'POST', credentials: 'same-origin' });
	if (!res.ok) throw new Error(`로그아웃하지 못했습니다 (${res.status})`);
}

export type Classroom = {
	id: number;
	name: string;
	section_name: string | null;
	status: 'active' | 'archived';
	student_count: number;
	created_at: string;
};
export type ClassroomList = {
	classrooms: Classroom[];
	counts: { active: number; archived: number };
};

/** 서버가 오류로 답했을 때. message는 서버가 준 한국어 안내라서 화면에 그대로 보여 줄 수 있다. */
export class ApiError extends Error {
	status: number;
	constructor(status: number, message: string) {
		super(message);
		this.name = 'ApiError';
		this.status = status;
	}
}

async function failure(res: Response): Promise<ApiError> {
	let detail: unknown;
	try {
		detail = ((await res.json()) as { detail?: unknown }).detail;
	} catch {
		// 본문이 JSON이 아니면 안내 없이 상태 번호만 쓴다
	}
	return new ApiError(
		res.status,
		typeof detail === 'string' ? detail : `요청을 처리하지 못했습니다 (${res.status})`
	);
}

async function getJson<T>(fetchFn: FetchFn, url: string): Promise<T> {
	const res = await fetchFn(url, { credentials: 'same-origin', headers: { Accept: 'application/json' } });
	if (!res.ok) throw await failure(res);
	return (await res.json()) as T;
}

export function fetchClassrooms(fetchFn: FetchFn): Promise<ClassroomList> {
	return getJson<ClassroomList>(fetchFn, '/api/classrooms');
}

export function fetchClassroom(id: number, fetchFn: FetchFn): Promise<Classroom> {
	return getJson<Classroom>(fetchFn, `/api/classrooms/${id}`);
}

export async function createClassroom(
	input: { name: string; section_name?: string | null },
	fetchFn: FetchFn = fetch
): Promise<Classroom> {
	const res = await fetchFn('/api/classrooms', {
		method: 'POST',
		credentials: 'same-origin',
		headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
		body: JSON.stringify(input)
	});
	if (!res.ok) throw await failure(res);
	return (await res.json()) as Classroom;
}
