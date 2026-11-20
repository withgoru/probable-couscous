import { loadSession } from '#lib/auth.js';
import type { LayoutLoad } from './$types';

// SPA 모드: 서버 렌더링과 사전 렌더링을 끄고 브라우저에서만 그린다
export const ssr = false;
export const prerender = false;

// 모든 화면이 열릴 때 로그인 상태를 확인한다. 로그인하지 않은 채 보호된 화면이면 로그인 화면으로 보낸다
export const load: LayoutLoad = ({ fetch, url }) => loadSession(fetch, url);
