import { ApiError, fetchClassroom, fetchRoster } from '#lib/api.js';
import type { PageLoad } from './$types';

// 다른 교수의 강좌(403)나 없는 강좌(404)는 오류 화면이 아니라 이유와 돌아갈 길을 보여 주는 안내로 돌려준다(AC8)
export const load: PageLoad = async ({ fetch, params, depends }) => {
	depends('app:roster'); // 학생을 추가하거나 CSV를 올린 뒤 invalidate('app:roster')로 명단을 다시 불러온다
	if (!/^\d+$/.test(params.id)) {
		return { classroom: null, roster: null, notice: { status: 404, message: '찾을 수 없는 강좌입니다.' } };
	}
	const id = Number(params.id);
	try {
		const classroom = await fetchClassroom(id, fetch);
		return { classroom, roster: await fetchRoster(id, fetch), notice: null };
	} catch (e) {
		if (e instanceof ApiError && (e.status === 403 || e.status === 404)) {
			return { classroom: null, roster: null, notice: { status: e.status, message: e.message } };
		}
		throw e;
	}
};
