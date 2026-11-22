import { ApiError, fetchJoinState, openInvite, type InviteClassroom, type JoinState } from '#lib/api.js';
import type { PageLoad } from './$types';

export type Invite = { open: true; classroom: InviteClassroom; me: JoinState } | { open: false; message: string };

const closed = (e: unknown) => e instanceof ApiError && (e.status === 404 || e.status === 403);

// 폐기된 링크(404)와 보관된 강좌(403)는 오류 화면이 아니라 이유와 다음 행동을 알려 주는 학생 화면으로 보인다(AC10, AC22).
// 그 밖의 실패(서버 오류, 연결 문제)는 오류 화면이 안내한다.
// 열린 강좌면 이 기기의 입장 상태도 묻는다. 링크 열기가 기기 쿠키를 심으므로 그 다음에 묻는다(AC35, AC37).
export const load: PageLoad = async ({ fetch, params }) => {
	const token = params.token;
	try {
		const classroom = await openInvite(token, fetch);
		let me: JoinState;
		try {
			me = await fetchJoinState(token, fetch);
		} catch (e) {
			if (closed(e)) throw e;
			me = { state: 'login' }; // 상태를 모르면 막지 않고 이메일 단계부터 시작한다
		}
		return { token, invite: { open: true, classroom, me } as Invite };
	} catch (e) {
		if (closed(e)) return { token, invite: { open: false, message: (e as ApiError).message } as Invite };
		throw e;
	}
};
