// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

const state = vi.hoisted(() => ({ status: 500, error: { message: 'boom' } as { message: string } | null }));
vi.mock('$app/state', () => ({ page: state }));

import ErrorPage from './+error.svelte';

afterEach(cleanup);

describe('오류 화면', () => {
	it('무엇이 잘못됐고 어떻게 하면 되는지 알려 준다', () => {
		render(ErrorPage);
		const alert = screen.getByRole('alert');
		expect(alert.textContent).toContain('화면을 불러오지 못했습니다');
		expect(alert.textContent).toContain('새로고침');
	});

	it('다시 시도할 수 있는 링크가 있다', () => {
		render(ErrorPage);
		expect(screen.getByRole('link', { name: '처음으로 돌아가기' }).getAttribute('href')).toBe('/');
	});
});
