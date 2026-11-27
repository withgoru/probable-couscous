import type { Page } from '@playwright/test';

/** 페이지의 WebSocket을 끊고, 풀어 줄 때까지 다시 붙지 못하게 한다(로컬 연결은 오프라인 흉내로 끊기지 않는다). */
export async function controlSockets(page: Page) {
	await page.addInitScript(() => {
		const Real = window.WebSocket;
		const w = window as unknown as { __sockets: WebSocket[]; __blocked: boolean };
		w.__sockets = [];
		w.__blocked = false;
		class Controlled extends Real {
			constructor(url: string | URL, protocols?: string | string[]) {
				super(url, protocols);
				w.__sockets.push(this);
				if (w.__blocked) queueMicrotask(() => this.close()); // 막힌 동안에는 열리자마자 닫는다(서버가 받지 않은 것처럼)
			}
		}
		window.WebSocket = Controlled as typeof WebSocket;
	});
	return {
		drop: () =>
			page.evaluate(() => {
				const w = window as unknown as { __sockets: WebSocket[]; __blocked: boolean };
				w.__blocked = true;
				for (const s of w.__sockets) s.close();
			}),
		restore: () =>
			page.evaluate(() => {
				(window as unknown as { __blocked: boolean }).__blocked = false;
			})
	};
}
