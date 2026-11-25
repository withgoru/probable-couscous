/**
 * 슬라이드 위치 계산(002 AC13, AC14, AC27). 교수 수업 화면과 학생 화면이 함께 쓴다.
 *
 * 위치는 (슬라이드 번호, 단계)다. 슬라이드는 1부터, 단계는 0부터 센다. 단계 수(clicksTotal)는 슬라이드 묶음 안의
 * 애드온이 그 슬라이드를 그릴 때 알려 준다. 서버는 단계 수를 모른다.
 */

import type { Position } from './deckBridge';

/** a가 b보다 뒤인가. */
export function isAfter(a: Position, b: Position): boolean {
	return a.slide > b.slide || (a.slide === b.slide && a.click > b.click);
}

/**
 * 다음 위치. 현재 슬라이드에 남은 단계가 있으면 다음 단계, 없으면 다음 슬라이드의 첫 단계(AC14).
 * 끝이면 null. 단계 수를 아직 모르면 남은 단계가 없다고 본다.
 */
export function nextPosition(current: Position, clicksTotal: number | null, total: number | null): Position | null {
	if (clicksTotal !== null && current.click < clicksTotal) return { slide: current.slide, click: current.click + 1 };
	if (total !== null && current.slide < total) return { slide: current.slide + 1, click: 0 };
	return null;
}

/**
 * 이전 위치. 현재 슬라이드의 앞 단계, 첫 단계였으면 이전 슬라이드의 마지막 단계.
 * 이전 슬라이드의 단계 수는 본 적이 있을 때만 안다(`seenClicks`). 모르면 그 슬라이드의 처음으로 간다. 처음이면 null.
 */
export function prevPosition(current: Position, seenClicks: ReadonlyMap<number, number>): Position | null {
	if (current.click > 0) return { slide: current.slide, click: current.click - 1 };
	if (current.slide > 1) return { slide: current.slide - 1, click: seenClicks.get(current.slide - 1) ?? 0 };
	return null;
}
