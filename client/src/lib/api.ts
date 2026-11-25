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
	/** 입력 칸에 대한 오류면 그 칸 이름, 칸과 무관한 오류(예: 200명 초과)면 null, 칸 개념이 없는 오류면 undefined. */
	field?: string | null;
	/** 안내 말고 서버가 함께 준 값(예: 코드 확인의 outcome·remaining, 다시 받기의 wait_seconds). */
	data?: Record<string, unknown>;
	constructor(status: number, message: string, field?: string | null, data?: Record<string, unknown>) {
		super(message);
		this.name = 'ApiError';
		this.status = status;
		this.field = field;
		this.data = data;
	}
}

async function failure(res: Response): Promise<ApiError> {
	let detail: unknown;
	let extra: Record<string, unknown> = {};
	try {
		({ detail, ...extra } = (await res.json()) as { detail?: unknown });
	} catch {
		// 본문이 JSON이 아니면 안내 없이 상태 번호만 쓴다
	}
	// 안내 옆에 서버가 함께 준 값(예: 보관 거절의 live_session_id)은 data에 담는다
	if (typeof detail === 'string') return new ApiError(res.status, detail, undefined, Object.keys(extra).length ? extra : undefined);
	// 명단 API는 {field, message}로 어느 입력 칸의 오류인지 알려 준다
	if (detail && typeof detail === 'object' && typeof (detail as { message?: unknown }).message === 'string') {
		const { field, message, ...rest } = detail as { field?: string | null; message: string };
		return new ApiError(res.status, message, field ?? null, Object.keys(rest).length ? rest : undefined);
	}
	return new ApiError(res.status, `요청을 처리하지 못했습니다 (${res.status})`);
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

type ClassroomInput = { name: string; section_name?: string | null };

async function postClassroom(fetchFn: FetchFn, url: string, input: ClassroomInput): Promise<Classroom> {
	const res = await fetchFn(url, {
		method: 'POST',
		credentials: 'same-origin',
		headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
		body: JSON.stringify(input)
	});
	if (!res.ok) throw await failure(res);
	return (await res.json()) as Classroom;
}

export function createClassroom(input: ClassroomInput, fetchFn: FetchFn = fetch): Promise<Classroom> {
	return postClassroom(fetchFn, '/api/classrooms', input);
}

/** 분반 만들기, 새 학기로 복제. 이름과 분반만 가져오고 명단과 기록은 새로 시작한다. */
export function cloneClassroom(
	sourceId: number,
	input: ClassroomInput,
	fetchFn: FetchFn = fetch
): Promise<Classroom> {
	return postClassroom(fetchFn, `/api/classrooms/${sourceId}/clone`, input);
}

/** 강좌 보관(AC9). 학생 입장을 닫는다. 수업 중이면 409(data.live_session_id, 002 AC46). */
export async function archiveClassroom(id: number, fetchFn: FetchFn = fetch): Promise<Classroom> {
	const res = await fetchFn(`/api/classrooms/${id}/archive`, {
		method: 'POST',
		credentials: 'same-origin',
		headers: { Accept: 'application/json' }
	});
	if (!res.ok) throw await failure(res);
	return (await res.json()) as Classroom;
}

export type MySummary = {
	github_id: number;
	login: string;
	counts: { active: number; archived: number };
	active_students: number;
	active_classrooms: Classroom[];
};

export function fetchMySummary(fetchFn: FetchFn): Promise<MySummary> {
	return getJson<MySummary>(fetchFn, '/api/me/summary');
}

export type RosterEntry = { id: number; student_no: string; name: string; email: string; entered: boolean };
export type Roster = { entries: RosterEntry[]; count: number; limit: number };
export type NewStudent = { student_no: string; name: string; email: string };
export type ImportResult = { added: number; skipped: number; skipped_lines: { line: number; reason: string }[] };

export function fetchRoster(classroomId: number, fetchFn: FetchFn): Promise<Roster> {
	return getJson<Roster>(fetchFn, `/api/classrooms/${classroomId}/roster`);
}

/** 학생 한 명 추가. 실패하면 ApiError(field가 있으면 그 입력 칸의 오류). */
export async function addStudent(
	classroomId: number,
	input: NewStudent,
	fetchFn: FetchFn = fetch
): Promise<Omit<RosterEntry, 'entered'>> {
	const res = await fetchFn(`/api/classrooms/${classroomId}/roster`, {
		method: 'POST',
		credentials: 'same-origin',
		headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
		body: JSON.stringify(input)
	});
	if (!res.ok) throw await failure(res);
	return (await res.json()) as Omit<RosterEntry, 'entered'>;
}

/** CSV 올리기. 파일 내용을 그대로 본문으로 보낸다(서버가 1MB까지 받는다). */
export async function importRoster(classroomId: number, file: File, fetchFn: FetchFn = fetch): Promise<ImportResult> {
	const res = await fetchFn(`/api/classrooms/${classroomId}/roster/import`, {
		method: 'POST',
		credentials: 'same-origin',
		headers: { 'Content-Type': 'text/csv', Accept: 'application/json' },
		body: file
	});
	if (!res.ok) throw await failure(res);
	return (await res.json()) as ImportResult;
}

export type Invite = { token: string; url: string };

export function fetchInvite(classroomId: number, fetchFn: FetchFn): Promise<Invite> {
	return getJson<Invite>(fetchFn, `/api/classrooms/${classroomId}/invite`);
}

/** 링크를 새로 만든다. 이전 링크는 바로 쓸 수 없게 된다. */
export async function regenerateInvite(classroomId: number, fetchFn: FetchFn = fetch): Promise<Invite> {
	const res = await fetchFn(`/api/classrooms/${classroomId}/invite/regenerate`, {
		method: 'POST',
		credentials: 'same-origin',
		headers: { Accept: 'application/json' }
	});
	if (!res.ok) throw await failure(res);
	return (await res.json()) as Invite;
}

// --- 학생 입장 (초대 링크) -------------------------------------------------------------------------------------------

export type InviteClassroom = { name: string; section_name: string | null };

/** 서버가 알려 주는 다음 단계. code면 코드 입력, 나머지는 안내 문구(message)를 보여 준다. */
export type JoinAnswer =
	| { next: 'code'; wait_seconds: number }
	| { next: 'request_access' | 'already_requested' | 'rejected' | 'requested' | 'already_on_roster'; message: string };

const joinUrl = (token: string, rest = '') => `/api/join/${encodeURIComponent(token)}${rest}`;

/** 초대 링크를 연다. 강좌 이름만 받고, 이 기기의 기기 쿠키를 받는다. 폐기(404)·보관(403)은 서버의 안내를 담은 ApiError. */
export function openInvite(token: string, fetchFn: FetchFn = fetch): Promise<InviteClassroom> {
	return getJson<InviteClassroom>(fetchFn, joinUrl(token));
}

async function postJoin<T = JoinAnswer>(fetchFn: FetchFn, url: string, body: unknown): Promise<T> {
	const res = await fetchFn(url, {
		method: 'POST',
		credentials: 'same-origin',
		headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
		body: JSON.stringify(body)
	});
	if (!res.ok) throw await failure(res);
	return (await res.json()) as T;
}

/** 이메일을 확인한다. 명단에 있으면 코드 메일을 요청하고(next: code), 없으면 입장 요청 안내를 받는다. */
export function submitJoinEmail(token: string, email: string, fetchFn: FetchFn = fetch): Promise<JoinAnswer> {
	return postJoin(fetchFn, joinUrl(token, '/email'), { email });
}

export type AccessRequest = { email: string; name: string; student_no: string };

/** 명단에 없는 이메일로 입장 요청을 보낸다. 새 요청이면 requested, 그 밖에는 지금 상태의 안내를 받는다. */
export function requestAccess(token: string, input: AccessRequest, fetchFn: FetchFn = fetch): Promise<JoinAnswer> {
	return postJoin(fetchFn, joinUrl(token, '/request-access'), input);
}

export type CodeInput = { email: string; code: string; keep_login: boolean };
/** 코드가 맞으면 닉네임(notice), 코드를 받은 뒤 명단에서 빠졌으면 명단 밖 안내. */
export type CodeAnswer = { next: 'notice'; nickname: string } | { next: 'request_access'; message: string };

/** 코드를 확인한다. 맞으면 서버가 이 기기에 로그인 쿠키를 심는다. 틀리면 ApiError(422, data: outcome·remaining). */
export function verifyCode(token: string, input: CodeInput, fetchFn: FetchFn = fetch): Promise<CodeAnswer> {
	return postJoin<CodeAnswer>(fetchFn, joinUrl(token, '/code'), input);
}

/** 코드 다시 받기(직전 요청 60초 뒤부터). 너무 빠르면 ApiError(429, data: wait_seconds). */
export function resendCode(token: string, email: string, fetchFn: FetchFn = fetch): Promise<JoinAnswer> {
	return postJoin(fetchFn, joinUrl(token, '/resend'), { email });
}

/** '교수님께 알리기'. 교수의 대기 중인 인증 목록에 이 학생의 코드가 오른다. */
export function notifyProfessor(
	token: string,
	email: string,
	fetchFn: FetchFn = fetch
): Promise<{ next: 'notified'; message: string }> {
	return postJoin(fetchFn, joinUrl(token, '/notify-professor'), { email });
}

/** 이 기기의 이 강좌 상태. login: 이메일 인증 필요, notice: 인증됨·안내 확인 전, entered: 입장함. */
export type JoinState = { state: 'login' } | { state: 'notice' | 'entered'; nickname: string; classroom: string };

/** 로그인 유지 중인 기기면 이메일 없이 안내나 입장 완료로 간다(AC35, AC37). 링크를 연 뒤(기기 쿠키를 받은 뒤)에 부른다. */
export function fetchJoinState(token: string, fetchFn: FetchFn = fetch): Promise<JoinState> {
	return getJson<JoinState>(fetchFn, joinUrl(token, '/me'));
}

export type Entered = { next: 'entered'; nickname: string; classroom: string };

/** '확인하고 입장'(AC28). 채팅 이용 안내를 확인했다고 기록하고 이 기기를 이 강좌에 입장한 기기로 남긴다. */
export function enterClassroom(token: string, fetchFn: FetchFn = fetch): Promise<Entered> {
	return postJoin<Entered>(fetchFn, joinUrl(token, '/enter'), {});
}

// --- 교수 관리 화면: 입장 요청과 대기 중인 인증 ------------------------------------------------------------------------

export type JoinRequest = { id: number; name: string; student_no: string; email: string; created_at: string };

/** 처리 전 입장 요청(오래된 것부터). 이름, 학번, 이메일, 요청 시각만 온다(AC40). */
export async function fetchJoinRequests(classroomId: number, fetchFn: FetchFn = fetch): Promise<JoinRequest[]> {
	return (await getJson<{ requests: JoinRequest[] }>(fetchFn, `/api/classrooms/${classroomId}/join-requests`)).requests;
}

async function decide(fetchFn: FetchFn, classroomId: number, requestId: number, action: 'approve' | 'reject') {
	const res = await fetchFn(`/api/classrooms/${classroomId}/join-requests/${requestId}/${action}`, {
		method: 'POST',
		credentials: 'same-origin',
		headers: { Accept: 'application/json' }
	});
	if (!res.ok) throw await failure(res);
	return (await res.json()) as { id: number; status: 'approved' | 'rejected' };
}

/** 승인: 명단에 추가한다. 입장은 되지 않고 학생은 이메일 인증부터 한다(AC41). 명단 규칙에 걸리면 ApiError(409). */
export function approveJoinRequest(classroomId: number, requestId: number, fetchFn: FetchFn = fetch) {
	return decide(fetchFn, classroomId, requestId, 'approve');
}

/** 거절: 학생이 다시 열면 거절 안내가 보인다(AC42). */
export function rejectJoinRequest(classroomId: number, requestId: number, fetchFn: FetchFn = fetch) {
	return decide(fetchFn, classroomId, requestId, 'reject');
}

export type PendingAuth = {
	id: number;
	student_no: string;
	name: string;
	notified_at: string;
} & (
	| { status: 'waiting'; code: string; expires_at: string }
	| { status: 'used'; used_at: string }
	| { status: 'expired' }
);

/** '교수님께 알리기'를 누른 학생의 코드(AC45). **부를 때마다 서버가 코드 열람을 기록한다**(AC48). 꼭 필요할 때만 부른다. */
export async function fetchPendingAuth(classroomId: number, fetchFn: FetchFn = fetch): Promise<PendingAuth[]> {
	return (await getJson<{ items: PendingAuth[] }>(fetchFn, `/api/classrooms/${classroomId}/pending-auth`)).items;
}

// --- 명단에서 빼기와 로그인 끊기 (AC19, AC20) ---------------------------------------------------------------------------

/** 명단에서 뺀다. 그 학생은 이 강좌에 입장할 수 없고 이 강좌의 로그인 유지도 끝난다(AC19). */
export async function removeStudent(classroomId: number, entryId: number, fetchFn: FetchFn = fetch) {
	const res = await fetchFn(`/api/classrooms/${classroomId}/roster/${entryId}`, {
		method: 'DELETE',
		credentials: 'same-origin',
		headers: { Accept: 'application/json' }
	});
	if (!res.ok) throw await failure(res);
	return (await res.json()) as { id: number; removed: true };
}

/** 로그인 끊기. 그 학생의 모든 기기가 이 강좌에서 로그아웃된다(AC20). 입장한 적 없으면 ApiError(409). */
export async function revokeStudentLogin(classroomId: number, entryId: number, fetchFn: FetchFn = fetch) {
	const res = await fetchFn(`/api/classrooms/${classroomId}/roster/${entryId}/revoke-login`, {
		method: 'POST',
		credentials: 'same-origin',
		headers: { Accept: 'application/json' }
	});
	if (!res.ok) throw await failure(res);
	return (await res.json()) as { id: number; revoked: true };
}
