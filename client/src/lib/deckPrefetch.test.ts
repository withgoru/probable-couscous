import { describe, expect, it, vi } from 'vitest';
import { firstScreenFiles, prefetchDeck } from './deckPrefetch';

const INDEX = `<!doctype html><html><head>
<script type="module" crossorigin src="/decks/8/assets/index-AbCdEfGh.js"></script>
<link rel="modulepreload" crossorigin href="/decks/8/assets/modules/vue-ZYXWVUts.js">
<link rel="stylesheet" crossorigin href="/decks/8/assets/index-QwErTyUi.css">
<link rel="icon" href="/decks/8/favicon.svg">
<script src="/decks/9/assets/other-12345678.js"></script>
</head></html>`;

describe('묶음 첫 화면 파일 (T038)', () => {
	it('index.html이 바로 부르는 그 묶음의 JS·CSS만 고른다', () => {
		expect(firstScreenFiles(INDEX, 8)).toEqual([
			'/decks/8/assets/index-AbCdEfGh.js',
			'/decks/8/assets/index-QwErTyUi.css',
			'/decks/8/assets/modules/vue-ZYXWVUts.js'
		]);
	});
});

describe('미리 받기 (T038)', () => {
	it('첫 화면과 그 파일들을 같은 출처 쿠키로 받는다', async () => {
		const fetchFn = vi.fn(async (url: string, _init?: RequestInit) => new Response(url.endsWith('index.html') ? INDEX : 'x', { status: 200 }));
		expect(await prefetchDeck(8, fetchFn as unknown as typeof fetch)).toBe(true);
		const urls = fetchFn.mock.calls.map(([u]) => u);
		expect(urls[0]).toBe('/decks/8/index.html');
		expect(urls.slice(1).sort()).toEqual(firstScreenFiles(INDEX, 8).sort());
		expect(fetchFn.mock.calls.every(([, init]) => init?.credentials === 'same-origin')).toBe(true);
	});

	it('받지 못하면(비공개, 연결 문제) 조용히 그만둔다', async () => {
		const refused = vi.fn(async () => new Response('{}', { status: 404 }));
		expect(await prefetchDeck(8, refused as unknown as typeof fetch)).toBe(false);
		expect(refused).toHaveBeenCalledTimes(1); // 첫 화면이 막히면 파일은 받지 않는다
		const offline = vi.fn(async () => {
			throw new TypeError('Failed to fetch');
		});
		expect(await prefetchDeck(8, offline as unknown as typeof fetch)).toBe(false);
	});

	it('파일 하나를 받지 못해도 실패로 알리고 던지지 않는다', async () => {
		const fetchFn = vi.fn(async (url: string) =>
			url.endsWith('index.html') ? new Response(INDEX) : url.includes('vue') ? new Response('', { status: 500 }) : new Response('x')
		);
		expect(await prefetchDeck(8, fetchFn as unknown as typeof fetch)).toBe(false);
	});
});

describe('미리 받기: 검증 뒤 추가', () => {
	it('파일 내용을 끝까지 읽는다(다 받아야 캐시에 남는다)', async () => {
		const bodies: Response[] = [];
		const fetchFn = vi.fn(async (url: string) => {
			const r = new Response(url.endsWith('index.html') ? INDEX : 'x');
			if (!url.endsWith('index.html')) bodies.push(r);
			return r;
		});
		await prefetchDeck(8, fetchFn as unknown as typeof fetch);
		expect(bodies).toHaveLength(3);
		expect(bodies.every((r) => r.bodyUsed)).toBe(true);
	});
});
