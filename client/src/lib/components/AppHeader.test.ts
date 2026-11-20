// @vitest-environment jsdom
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const nav = vi.hoisted(() => ({ goto: vi.fn(() => Promise.resolve()) }));
const api = vi.hoisted(() => ({ logout: vi.fn(() => Promise.resolve()) }));
vi.mock('$app/navigation', () => nav);
vi.mock('#lib/api.js', () => api);

import AppHeader from './AppHeader.svelte';

const me = { github_id: 101, login: 'kim' };

beforeEach(() => {
	nav.goto.mockClear();
	api.logout.mockReset();
	api.logout.mockImplementation(() => Promise.resolve());
});
afterEach(cleanup);

async function openMenu() {
	const trigger = screen.getByRole('button', { name: /@kim/ });
	await fireEvent.keyDown(trigger, { key: 'Enter' });
	await screen.findByRole('menu');
	return trigger;
}

describe('공통 메뉴바 (AC4)', () => {
	it('상단 메뉴바에 서비스 이름 링크와 계정 버튼이 있다', () => {
		render(AppHeader, { me });
		expect(screen.getByRole('banner')).toBeTruthy();
		const brand = screen.getByRole('link', { name: '강의 상호작용 도구' });
		expect(brand.getAttribute('href')).toBe('/courses');
		expect(screen.getByRole('button', { name: /@kim/ })).toBeTruthy();
	});

	it('계정 버튼은 처음에는 닫혀 있고 열면 expanded가 된다', async () => {
		render(AppHeader, { me });
		const trigger = screen.getByRole('button', { name: /@kim/ });
		expect(trigger.getAttribute('aria-expanded')).toBe('false');
		expect(screen.queryByRole('menu')).toBeNull();
		await openMenu();
		expect(trigger.getAttribute('aria-expanded')).toBe('true');
	});

	it('메뉴에는 @GitHub 계정, 마이페이지, 로그아웃이 있고 설정은 없다', async () => {
		render(AppHeader, { me });
		await openMenu();
		const menu = screen.getByRole('menu');
		expect(menu.textContent).toContain('@kim');
		expect(menu.textContent).toContain('GitHub 계정');
		const items = screen.getAllByRole('menuitem');
		expect(items.map((i) => i.textContent?.trim())).toEqual(['마이페이지', '로그아웃']);
		expect(screen.queryByRole('menuitem', { name: /설정/ })).toBeNull();
	});

	it('마이페이지는 실제 링크다', async () => {
		render(AppHeader, { me });
		await openMenu();
		const item = screen.getByRole('menuitem', { name: '마이페이지' });
		expect(item.tagName).toBe('A');
		expect(item.getAttribute('href')).toBe('/mypage');
	});

	it('메뉴 항목과 계정 버튼은 높이 44px 이상을 정의한 디자인 시스템 클래스를 쓴다 (C14)', async () => {
		render(AppHeader, { me });
		await openMenu();
		// jsdom은 CSS를 계산하지 못한다. 컴포넌트가 쓰는 클래스가 44px(min-h-11, h-11)를 정의하는지 확인하고,
		// 실제 높이는 브라우저에서 측정한다
		const theme = readFileSync(resolve(__dirname, '../../theme.css'), 'utf8');
		expect(theme).toMatch(/\.menu-item\s*\{[^}]*min-h-11/);
		expect(theme).toMatch(/\.btn\s*\{[^}]*h-11/);
		for (const item of screen.getAllByRole('menuitem')) expect(item.className).toContain('menu-item');
		expect(screen.getByRole('button', { name: /@kim/ }).className).toMatch(/\bbtn\b/);
	});

	it('Esc로 메뉴를 닫는다', async () => {
		render(AppHeader, { me });
		await openMenu();
		await fireEvent.keyDown(screen.getByRole('menu'), { key: 'Escape' });
		await waitFor(() => expect(screen.queryByRole('menu')).toBeNull());
	});
});

describe('로그아웃 (AC4)', () => {
	it('로그아웃 요청이 끝난 뒤에 로그인 화면으로 이동하고 뒤로 가기 기록을 남기지 않는다', async () => {
		const order: string[] = [];
		api.logout.mockImplementation(async () => {
			order.push('logout');
		});
		nav.goto.mockImplementation(async () => {
			order.push('goto');
		});
		render(AppHeader, { me });
		await openMenu();
		await fireEvent.click(screen.getByRole('menuitem', { name: '로그아웃' }));
		await waitFor(() => expect(nav.goto).toHaveBeenCalled());
		expect(order).toEqual(['logout', 'goto']);
		expect(nav.goto).toHaveBeenCalledWith('/login', { replace: true, refreshAll: true });
	});

	it('로그아웃 요청이 실패하면 이동하지 않고 이유와 해결 방법을 알려 준다', async () => {
		api.logout.mockImplementation(() => Promise.reject(new Error('network')));
		render(AppHeader, { me });
		await openMenu();
		await fireEvent.click(screen.getByRole('menuitem', { name: '로그아웃' }));
		const alert = await screen.findByRole('alert');
		expect(alert.textContent).toContain('로그아웃하지 못했습니다');
		expect(alert.textContent).toContain('다시 시도');
		expect(nav.goto).not.toHaveBeenCalled();
	});
});
