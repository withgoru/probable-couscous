/**
 * 공개 묶음 미리 받기(002 T038, plan 위험 4).
 *
 * 수업이 시작되면 학생 200명이 한꺼번에 슬라이드 묶음을 받아 일부가 받지 못할 수 있다(T030 측정). 학생 대기 화면이
 * 다음 수업의 공개 묶음 첫 화면 파일을 미리 받아 두면, 해시 파일은 브라우저 캐시에 오래 남아(서버가 공개 묶음에 한해
 * 오래 캐시하라고 한다) 수업 시작에는 첫 화면(index.html)만 다시 확인한다. 비공개 묶음은 수업 밖에서 받을 수 없다(AC50).
 */

/** index.html이 바로 부르는 그 묶음의 JS·CSS. 나머지 조각과 그림은 슬라이드를 넘길 때 받는다. */
export function firstScreenFiles(indexHtml: string, deckId: number): string[] {
	const pattern = new RegExp(`(?:src|href)="(/decks/${deckId}/[^"]+\\.(?:js|css))"`, 'g');
	return [...new Set([...indexHtml.matchAll(pattern)].map((m) => m[1]))].sort();
}

/** 첫 화면과 그 파일들을 받는다. 다 받았으면 참. 받지 못해도 던지지 않는다(화면에 알리지 않는다). */
export async function prefetchDeck(deckId: number, fetchFn: typeof fetch = fetch): Promise<boolean> {
	const init: RequestInit = { credentials: 'same-origin' };
	try {
		const index = await fetchFn(`/decks/${deckId}/index.html`, init);
		if (!index.ok) return false;
		const files = firstScreenFiles(await index.text(), deckId);
		const responses = await Promise.all(files.map((file) => fetchFn(file, init)));
		await Promise.all(responses.map((r) => r.arrayBuffer().catch(() => null))); // 끝까지 받아야 캐시에 남는다
		return responses.every((r) => r.ok);
	} catch {
		return false;
	}
}
