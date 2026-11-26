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
	/** 한 번이라도 시작한 회차 수(002 AC8). */
	session_count: number;
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
export type JoinState =
	| { state: 'login' }
	| { state: 'notice'; nickname: string; classroom: string }
	/** 입장했으면 수업 화면이 쓰는 강좌 번호도 온다(002). */
	| { state: 'entered'; nickname: string; classroom: string; classroom_id: number };

/** 로그인 유지 중인 기기면 이메일 없이 안내나 입장 완료로 간다(AC35, AC37). 링크를 연 뒤(기기 쿠키를 받은 뒤)에 부른다. */
export function fetchJoinState(token: string, fetchFn: FetchFn = fetch): Promise<JoinState> {
	return getJson<JoinState>(fetchFn, joinUrl(token, '/me'));
}

export type Entered = { next: 'entered'; nickname: string; classroom: string; classroom_id: number };

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

// --- 회차(002) ---------------------------------------------------------------------------

export type SessionDeck = {
	id: number;
	original_name: string;
	slide_count: number;
	size_bytes: number;
	uploaded_at: string;
	available: boolean;
};
export type ClassSession = {
	id: number;
	title: string;
	status: 'scheduled' | 'live' | 'ended';
	sort_order: number;
	created_at: string;
	can_delete: boolean;
	deck: SessionDeck | null;
};

async function sendSession(fetchFn: FetchFn, url: string, method: string, title: string): Promise<ClassSession> {
	const res = await fetchFn(url, {
		method,
		credentials: 'same-origin',
		headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
		body: JSON.stringify({ title })
	});
	if (!res.ok) throw await failure(res);
	return (await res.json()) as ClassSession;
}

/** 강좌의 회차 목록(관리 페이지, 교수만). 순서대로 온다. */
export async function fetchSessions(classroomId: number, fetchFn: FetchFn = fetch): Promise<ClassSession[]> {
	return (await getJson<{ items: ClassSession[] }>(fetchFn, `/api/classrooms/${classroomId}/sessions`)).items;
}

/** 회차 만들기(AC2). '예정'으로 목록 끝에 생긴다. 이름이 잘못되면 서버 안내를 담은 ApiError(422). */
export function createSession(classroomId: number, title: string, fetchFn: FetchFn = fetch): Promise<ClassSession> {
	return sendSession(fetchFn, `/api/classrooms/${classroomId}/sessions`, 'POST', title);
}

/** 회차 이름 바꾸기(AC4). 어느 상태든 된다. */
export function renameSession(
	classroomId: number,
	sessionId: number,
	title: string,
	fetchFn: FetchFn = fetch
): Promise<ClassSession> {
	return sendSession(fetchFn, `/api/classrooms/${classroomId}/sessions/${sessionId}`, 'PATCH', title);
}

/** 회차 삭제(AC4). 한 번이라도 시작한 회차면 ApiError(409). */
export async function deleteSession(classroomId: number, sessionId: number, fetchFn: FetchFn = fetch): Promise<void> {
	const res = await fetchFn(`/api/classrooms/${classroomId}/sessions/${sessionId}`, {
		method: 'DELETE',
		credentials: 'same-origin',
		headers: { Accept: 'application/json' }
	});
	if (!res.ok) throw await failure(res);
}

/** 슬라이드 묶음 올리기·바꾸기(AC5, AC6). zip을 본문 그대로 보낸다. 거절되면 서버 안내를 담은 ApiError(422, 413, 409). */
export async function uploadDeck(
	classroomId: number,
	sessionId: number,
	file: File,
	fetchFn: FetchFn = fetch
): Promise<SessionDeck> {
	const url = `/api/classrooms/${classroomId}/sessions/${sessionId}/deck?filename=${encodeURIComponent(file.name)}`;
	const res = await fetchFn(url, {
		method: 'PUT',
		credentials: 'same-origin',
		headers: { 'Content-Type': 'application/zip', Accept: 'application/json' },
		body: file
	});
	if (!res.ok) throw await failure(res);
	return ((await res.json()) as { deck: SessionDeck }).deck;
}

/** 슬라이드 묶음 지우기(AC7). 수업 중이면 ApiError(409). */
export async function removeDeck(classroomId: number, sessionId: number, fetchFn: FetchFn = fetch): Promise<void> {
	const res = await fetchFn(`/api/classrooms/${classroomId}/sessions/${sessionId}/deck`, {
		method: 'DELETE',
		credentials: 'same-origin',
		headers: { Accept: 'application/json' }
	});
	if (!res.ok) throw await failure(res);
}

export type StartedSession = ClassSession & { version: number };

async function postSession(fetchFn: FetchFn, url: string): Promise<StartedSession> {
	const res = await fetchFn(url, { method: 'POST', credentials: 'same-origin', headers: { Accept: 'application/json' } });
	if (!res.ok) throw await failure(res);
	return (await res.json()) as StartedSession;
}

/** 수업 시작(AC9). 다른 회차가 진행 중이면 ApiError(409, data.live_session_id), 보관된 강좌면 ApiError(409). */
export function startSession(classroomId: number, sessionId: number, fetchFn: FetchFn = fetch): Promise<StartedSession> {
	return postSession(fetchFn, `/api/classrooms/${classroomId}/sessions/${sessionId}/start`);
}

/** 이어서 수업하기(AC40). 거절은 수업 시작과 같다. */
export function resumeSession(classroomId: number, sessionId: number, fetchFn: FetchFn = fetch): Promise<StartedSession> {
	return postSession(fetchFn, `/api/classrooms/${classroomId}/sessions/${sessionId}/resume`);
}

export type DeckNotes = { deck_id: number; slide_count: number; slides: { no: number; title: string; note: string }[] };

/** 슬라이드 묶음의 발표자 노트(교수 전용, AC13·AC30). 파일이 사라졌으면 ApiError(410). */
export function fetchDeckNotes(classroomId: number, sessionId: number, fetchFn: FetchFn = fetch): Promise<DeckNotes> {
	return getJson<DeckNotes>(fetchFn, `/api/classrooms/${classroomId}/sessions/${sessionId}/deck/notes`);
}

// --- 메시지·자료 보내기(002 AC31~AC35) ---------------------------------------------------------

export type SentItem = { id: number; body: string | null; url: string | null; created_at: string; retracted_at: string | null };
export type NewItem = { body: string | null; url: string | null; client_key: string };

/** 진행 중인 회차에 글·링크를 보낸다. 같은 client_key로 다시 보내면 처음 저장한 항목을 돌려준다(두 번 저장되지 않음). */
export async function sendItem(
	classroomId: number,
	sessionId: number,
	input: NewItem,
	fetchFn: FetchFn = fetch
): Promise<SentItem> {
	const res = await fetchFn(`/api/classrooms/${classroomId}/sessions/${sessionId}/items`, {
		method: 'POST',
		credentials: 'same-origin',
		headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
		body: JSON.stringify(input)
	});
	if (!res.ok) throw await failure(res);
	return ((await res.json()) as { item: SentItem }).item;
}

/** 보낸 항목 거두기(AC35). 학생 화면에서 사라지고 되살리지 않는다. */
export async function retractItem(
	classroomId: number,
	sessionId: number,
	itemId: number,
	fetchFn: FetchFn = fetch
): Promise<SentItem> {
	const res = await fetchFn(`/api/classrooms/${classroomId}/sessions/${sessionId}/items/${itemId}/retract`, {
		method: 'POST',
		credentials: 'same-origin',
		headers: { Accept: 'application/json' }
	});
	if (!res.ok) throw await failure(res);
	return ((await res.json()) as { item: SentItem }).item;
}

/** 수업 종료(AC37). 회차가 '종료'가 된다. 이미 끝났으면 그대로 돌려준다. */
export function endSession(classroomId: number, sessionId: number, fetchFn: FetchFn = fetch): Promise<StartedSession> {
	return postSession(fetchFn, `/api/classrooms/${classroomId}/sessions/${sessionId}/end`);
}

// --- 학생 수업 화면(002) ---------------------------------------------------------------------

export type ClassSessionSummary = {
	id: number;
	title: string;
	status: 'scheduled' | 'live' | 'ended';
	started_at: string | null;
	ended_at: string | null;
	deck: { id: number; slide_count: number; available: boolean } | null;
};

/** 강좌의 회차 목록(class.view). 학생에게는 진행 중과 종료 회차만, 진행 중이 먼저, 그다음 최근에 끝난 것부터 온다. */
export function fetchClassSessions(
	classroomId: number,
	fetchFn: FetchFn = fetch
): Promise<{ items: ClassSessionSummary[]; live_session_id: number | null }> {
	return getJson(fetchFn, `/api/class/${classroomId}/sessions`);
}

/** 회차 하나의 상태(class.view). 학생 다시 보기(AC39)가 쓴다. 학생에게는 거둔 항목이 없다. */
export function fetchClassLive(
	classroomId: number,
	sessionId: number,
	fetchFn: FetchFn = fetch
): Promise<import('./classLive').LiveState> {
	return getJson(fetchFn, `/api/class/${classroomId}/sessions/${sessionId}/live`);
}
