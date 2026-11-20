import { fetchClassrooms } from '#lib/api.js';
import type { PageLoad } from './$types';

export const load: PageLoad = ({ fetch, depends }) => {
	depends('app:classrooms'); // 새 강좌를 만든 뒤 invalidate('app:classrooms')로 다시 불러온다
	return fetchClassrooms(fetch);
};
