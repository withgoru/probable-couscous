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
