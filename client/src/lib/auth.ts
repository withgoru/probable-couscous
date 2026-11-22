import { redirect } from '@sveltejs/kit';
import { fetchMe, type Me } from './api';

/** 로그인하지 않아도 열리는 화면. 나머지는 모두 로그인이 필요하다(없는 주소도 로그인 화면으로 보낸다). */
const PUBLIC_PATHS = new Set(['/login']);

/** 학생이 초대 링크로 여는 화면(/join/{토큰}). 교수 로그인과 무관하고 교수 메뉴도 붙이지 않는다. */
const STUDENT_PATH = /^\/join\/[^/]+$/;

export function isStudentPath(pathname: string): boolean {
	return STUDENT_PATH.test(pathname);
}

export function isPublic(pathname: string): boolean {
	return PUBLIC_PATHS.has(pathname) || isStudentPath(pathname);
}

/** 모든 화면이 열릴 때 부른다. 로그인하지 않았는데 보호된 화면이면 로그인 화면으로 보낸다(AC3). */
export async function loadSession(
	fetchFn: typeof fetch,
	url: URL
): Promise<{ me: Me | null }> {
	if (isStudentPath(url.pathname)) return { me: null }; // 학생 화면은 교수 로그인을 묻지 않는다
	const me = await fetchMe(fetchFn);
	if (!me && !isPublic(url.pathname)) redirect(302, '/login');
	return { me };
}

/**
 * 화면에 보이는 주소(SvelteKit이 아는 주소)와 브라우저 주소창이 다른가.
 * 로그아웃한 뒤 뒤로 가기를 누르면 브라우저는 이전 주소(/courses)로 돌아가고 가드가 로그인 화면으로 보낸다.
 * 이때 SvelteKit은 화면이 이미 로그인 화면이라 주소를 고치지 않으므로 어긋남을 찾아 맞춘다.
 */
type PathAndQuery = { pathname: string; search: string };

export function urlOutOfSync(shown: PathAndQuery, current: PathAndQuery): boolean {
	return shown.pathname + shown.search !== current.pathname + current.search;
}
