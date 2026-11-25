import { describe, expect, it } from 'vitest';
import { isClassScreen } from './routes';

describe('수업 중 화면(메뉴바 없음, 002 AC12, AC21)', () => {
	it('교수 수업 화면과 프로젝터 화면이다', () => {
		expect(isClassScreen('/courses/7/live')).toBe(true);
		expect(isClassScreen('/courses/7/live/')).toBe(true);
		expect(isClassScreen('/courses/12/projector')).toBe(true);
	});

	it('그 밖의 화면은 아니다', () => {
		for (const path of ['/courses', '/courses/7/admin', '/courses/live', '/courses/7/live/x', '/mypage', '/join/abc']) {
			expect(isClassScreen(path)).toBe(false);
		}
	});
});
