import { describe, expect, it } from 'vitest';
import { isAfter, nextPosition, prevPosition } from './slides';

describe('다음 위치 (AC14)', () => {
	it('현재 슬라이드에 남은 단계가 있으면 다음 단계다', () => {
		expect(nextPosition({ slide: 2, click: 0 }, 3, 4)).toEqual({ slide: 2, click: 1 });
		expect(nextPosition({ slide: 2, click: 2 }, 3, 4)).toEqual({ slide: 2, click: 3 });
	});

	it('남은 단계가 없으면 다음 슬라이드의 첫 단계다', () => {
		expect(nextPosition({ slide: 2, click: 3 }, 3, 4)).toEqual({ slide: 3, click: 0 });
		expect(nextPosition({ slide: 1, click: 0 }, 0, 4)).toEqual({ slide: 2, click: 0 });
	});

	it('마지막 슬라이드의 마지막 단계면 없다', () => {
		expect(nextPosition({ slide: 4, click: 1 }, 1, 4)).toBeNull();
		expect(nextPosition({ slide: 4, click: 0 }, 0, 4)).toBeNull();
	});

	it('단계 수를 아직 모르면 단계가 없다고 본다', () => {
		expect(nextPosition({ slide: 2, click: 0 }, null, 4)).toEqual({ slide: 3, click: 0 });
	});

	it('슬라이드 수를 모르면(묶음 없음) 없다', () => {
		expect(nextPosition({ slide: 1, click: 0 }, 0, null)).toBeNull();
	});
});

describe('이전 위치', () => {
	it('현재 슬라이드의 앞 단계로 간다', () => {
		expect(prevPosition({ slide: 2, click: 2 }, new Map())).toEqual({ slide: 2, click: 1 });
		expect(prevPosition({ slide: 2, click: 1 }, new Map())).toEqual({ slide: 2, click: 0 });
	});

	it('첫 단계면 이전 슬라이드의 마지막 단계(본 적이 있으면)로 간다', () => {
		expect(prevPosition({ slide: 3, click: 0 }, new Map([[2, 3]]))).toEqual({ slide: 2, click: 3 });
	});

	it('이전 슬라이드의 단계 수를 모르면 그 슬라이드의 처음으로 간다', () => {
		expect(prevPosition({ slide: 3, click: 0 }, new Map())).toEqual({ slide: 2, click: 0 });
	});

	it('첫 슬라이드의 첫 단계면 없다', () => {
		expect(prevPosition({ slide: 1, click: 0 }, new Map([[1, 2]]))).toBeNull();
	});
});

describe('위치 비교', () => {
	it('슬라이드, 그다음 단계로 비교한다', () => {
		expect(isAfter({ slide: 2, click: 0 }, { slide: 1, click: 5 })).toBe(true);
		expect(isAfter({ slide: 2, click: 1 }, { slide: 2, click: 0 })).toBe(true);
		expect(isAfter({ slide: 2, click: 0 }, { slide: 2, click: 0 })).toBe(false);
		expect(isAfter({ slide: 1, click: 9 }, { slide: 2, click: 0 })).toBe(false);
	});
});
