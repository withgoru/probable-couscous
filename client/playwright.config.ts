import { defineConfig, devices } from '@playwright/test';

// E2E: 빌드한 클라이언트를 E2E 전용 서버(e2e/server.py)가 내려주고, 실제 브라우저로 학생 입장 전체를 따라간다.
// 서버를 띄울 파이썬은 E2E_PYTHON으로 바꿀 수 있다(CI는 python, 로컬은 server/.venv).
const PORT = 8799;
const PYTHON = process.env.E2E_PYTHON ?? '../server/.venv/bin/python';

export default defineConfig({
	testDir: 'e2e',
	fullyParallel: false,
	workers: 1, // 서버와 DB를 같이 쓴다. 테스트마다 강좌를 새로 만들어 서로 섞이지 않게 한다
	forbidOnly: !!process.env.CI,
	retries: 0,
	reporter: process.env.CI ? 'github' : 'list',
	use: {
		baseURL: `http://127.0.0.1:${PORT}`,
		trace: 'retain-on-failure',
		...devices['Desktop Chrome'],
		viewport: { width: 390, height: 844 } // 학생 화면 기준(AC51)
	},
	projects: [{ name: 'chromium' }],
	webServer: {
		command: `npm run build && ${PYTHON} e2e/server.py ${PORT}`,
		url: `http://127.0.0.1:${PORT}/api/health`,
		env: { PYTHONPATH: '../server' },
		reuseExistingServer: false,
		timeout: 120_000
	}
});
