import { redirect } from '@sveltejs/kit';

// 루트 주소는 내 강좌로 보낸다. 로그인하지 않았다면 레이아웃의 가드가 먼저 로그인 화면으로 보낸다
export function load() {
	redirect(302, '/courses');
}
