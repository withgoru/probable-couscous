import tailwindcss from '@tailwindcss/vite';
import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

// SvelteKit 3은 svelte.config.js 대신 Vite 설정에서 옵션을 받는다.
// SPA 모드: 모든 경로를 index.html로 돌려보내고, 서버가 같은 출처에서 내려준다.
export default defineConfig({
	plugins: [
		tailwindcss(),
		sveltekit({
			adapter: adapter({ pages: 'build', assets: 'build', fallback: 'index.html', strict: true })
		})
	],
	server: {
		// 개발 중에는 /api 요청과 /ws 연결을 로컬 서버로 보낸다
		// 교수 관리 화면의 실시간 연결(/ws)도 같은 서버로 보낸다
		proxy: { '/api': 'http://localhost:8000', '/ws': { target: 'ws://localhost:8000', ws: true } }
	}
});
