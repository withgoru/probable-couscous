// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const state = vi.hoisted(() => ({ url: new URL('http://localhost:8000/login') }));
vi.mock('$app/state', () => ({ page: state }));

import LoginPage from './+page.svelte';

afterEach(cleanup);
beforeEach(() => {
	state.url = new URL('http://localhost:8000/login');
});

const withError = (code: string) => {
	state.url = new URL(`http://localhost:8000/login?error=${code}`);
};

describe('로그인 화면 (AC1)', () => {
	it('제목과 설명이 있다', () => {
		render(LoginPage);
		expect(screen.getByRole('heading', { level: 1, name: '교수 로그인' })).toBeTruthy();
		expect(screen.getByText(/허용된 계정만 강좌를 만들고 관리할 수 있습니다/)).toBeTruthy();
	});

	it("'GitHub로 로그인' 버튼은 로그인 시작 주소로 가고 화면 전환 없이 서버로 이동한다", () => {
		render(LoginPage);
		const button = screen.getByRole('link', { name: 'GitHub로 로그인' });
		expect(button.getAttribute('href')).toBe('/api/auth/github/login');
		expect(button.hasAttribute('data-sveltekit-reload')).toBe(true); // 서버가 GitHub로 보내므로 SPA 이동이 아니다
		expect(button.className).toContain('btn-lg'); // 높이 48px
	});

	it('학생을 위한 안내가 있다', () => {
		render(LoginPage);
		expect(screen.getByText(/학생이신가요\?.*초대 링크를 열어 이메일로 입장합니다/)).toBeTruthy();
	});

	it('페이지 제목에 화면 이름이 있다', () => {
		render(LoginPage);
		expect(document.title).toContain('교수 로그인');
	});

	it('오류가 없으면 알림을 보이지 않는다', () => {
		render(LoginPage);
		expect(screen.queryByRole('alert')).toBeNull();
	});
});

describe('허용 목록 밖 계정 (AC2)', () => {
	it('AC2의 문구를 그대로 보여 준다', () => {
		withError('not_allowed');
		render(LoginPage);
		const alert = screen.getByRole('alert');
		expect(alert.textContent).toContain('이 GitHub 계정은 사용할 수 없습니다');
		expect(alert.textContent).toContain('허용 목록에 없는 계정입니다. 허용된 계정으로 다시 로그인해 주세요.');
	});

	it('오류가 있어도 다시 로그인할 수 있는 버튼이 그대로 있다', () => {
		withError('not_allowed');
		render(LoginPage);
		expect(screen.getByRole('link', { name: 'GitHub로 로그인' })).toBeTruthy();
	});

	it('오류는 색만이 아니라 아이콘과 문구로 전달한다 (C14)', () => {
		withError('not_allowed');
		render(LoginPage);
		const alert = screen.getByRole('alert');
		expect(alert.querySelector('svg')).not.toBeNull();
		expect(alert.className).toContain('alert-destructive');
	});
});

describe('그 밖의 로그인 실패', () => {
	it.each([
		['state', '로그인을 완료하지 못했습니다', '다시 로그인해 주세요'],
		['cancelled', 'GitHub 로그인을 취소했습니다', '계속하려면 GitHub로 로그인해 주세요'],
		['github', 'GitHub와 통신하지 못했습니다', '잠시 뒤 다시 시도해 주세요']
	])('%s: 무엇이 잘못됐고 어떻게 하면 되는지 알려 준다', (code, title, hint) => {
		withError(code);
		render(LoginPage);
		const alert = screen.getByRole('alert');
		expect(alert.textContent).toContain(title);
		expect(alert.textContent).toContain(hint);
	});

	it('알 수 없는 오류 코드도 빈 화면이 아니라 일반 안내를 보여 준다', () => {
		withError('whatever');
		render(LoginPage);
		expect(screen.getByRole('alert').textContent).toContain('로그인하지 못했습니다');
	});

	it('오류 코드에 HTML이 들어 있어도 그대로 글자로만 쓴다', () => {
		withError('<img src=x onerror=alert(1)>');
		render(LoginPage);
		expect(document.querySelector('img')).toBeNull();
	});
});
