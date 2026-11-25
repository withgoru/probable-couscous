import { ApiError, fetchClassroom } from '#lib/api.js';
import type { PageLoad } from './$types';

// 교수 수업 화면(002 T018). 강좌 이름만 여기서 받고, 수업 상태는 화면이 수업 연결(classLive)로 받는다.
// 다른 교수의 강좌(403)나 없는 강좌(404)는 이유를 보여 주는 안내로 돌려준다(관리 페이지와 같다)
export const load: PageLoad = async ({ fetch, params }) => {
	if (!/^\d+$/.test(params.id)) {
		return { classroom: null, notice: { status: 404, message: '찾을 수 없는 강좌입니다.' } };
	}
	try {
		return { classroom: await fetchClassroom(Number(params.id), fetch), notice: null };
	} catch (e) {
		if (e instanceof ApiError && (e.status === 403 || e.status === 404)) {
			return { classroom: null, notice: { status: e.status, message: e.message } };
		}
		throw e;
	}
};
