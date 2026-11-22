import { ApiError, openInvite, type InviteClassroom } from '#lib/api.js';
import type { PageLoad } from './$types';

export type Invite = { open: true; classroom: InviteClassroom } | { open: false; message: string };

// 폐기된 링크(404)와 보관된 강좌(403)는 오류 화면이 아니라 이유와 다음 행동을 알려 주는 학생 화면으로 보인다(AC10, AC22).
// 그 밖의 실패(서버 오류, 연결 문제)는 오류 화면이 안내한다.
export const load: PageLoad = async ({ fetch, params }) => {
	try {
		const classroom = await openInvite(params.token, fetch);
		return { token: params.token, invite: { open: true, classroom } as Invite };
	} catch (e) {
		if (e instanceof ApiError && (e.status === 404 || e.status === 403)) {
			return { token: params.token, invite: { open: false, message: e.message } as Invite };
		}
		throw e;
	}
};
