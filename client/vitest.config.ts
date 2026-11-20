import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vitest/config';

// 컴포넌트 테스트는 파일 맨 위의 `// @vitest-environment jsdom`으로 jsdom을 쓴다. 나머지는 node 환경이다.
export default defineConfig({
	plugins: [sveltekit()],
	resolve: process.env.VITEST ? { conditions: ['browser'] } : undefined,
	test: {
		environment: 'node',
		include: ['src/**/*.test.ts']
	}
});
