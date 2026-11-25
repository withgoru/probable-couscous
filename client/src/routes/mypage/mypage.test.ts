// @vitest-environment jsdom
import { cleanup, render, screen, within } from '@testing-library/svelte';
import { afterEach, describe, expect, it } from 'vitest';
import MyPage from './+page.svelte';

const item = (id: number, name: string, section: string | null, students: number) => ({
	id, name, section_name: section, status: 'active' as const, student_count: students, session_count: 0,
	created_at: '2026-03-01T09:00:00+00:00'
});
const DATA = {
	github_id: 101,
	login: 'kim',
	counts: { active: 2, archived: 3 },
	active_students: 93,
	active_classrooms: [item(3, '데이터베이스', '수요반', 55), item(2, '웹 프로그래밍', null, 38)]
};
const show = (data = DATA) => render(MyPage, { params: {}, data: { ...data, me: null } });
afterEach(cleanup);

// 통계 카드는 이름표와 숫자가 한 카드 안에 있어야 한다(다른 카드의 숫자와 헷갈리지 않게)
const stat = (label: string) => {
	const cards = Array.from(document.querySelectorAll<HTMLElement>('[data-stat]'));
	const el = cards.find((c) => c.textContent?.includes(label));
	expect(el, `${label} 통계 카드`).toBeTruthy();
	return within(el!);
};

describe('마이페이지 (AC49)', () => {
	it('제목과 페이지 제목이 있다', () => {
		show();
		expect(screen.getByRole('heading', { level: 1, name: '마이페이지' })).toBeTruthy();
		expect(document.title).toContain('마이페이지');
	});

	it('@GitHub 계정과 로그인 방식이 보인다', () => {
		show();
		expect(screen.getByText('@kim')).toBeTruthy();
		expect(screen.getByText('GitHub 계정으로 로그인됨')).toBeTruthy();
	});

	it('진행 중 강좌 수, 보관된 강좌 수, 진행 중 수강생 합계가 보인다', () => {
		show();
		expect(stat('진행 중 강좌').getByText('2')).toBeTruthy();
		expect(stat('보관된 강좌').getByText('3')).toBeTruthy();
		expect(stat('진행 중 수강생').getByText('93')).toBeTruthy();
	});

	it('0도 0으로 보인다', () => {
		show({ ...DATA, counts: { active: 0, archived: 0 }, active_students: 0, active_classrooms: [] });
		expect(stat('진행 중 강좌').getByText('0')).toBeTruthy();
		expect(stat('보관된 강좌').getByText('0')).toBeTruthy();
		expect(stat('진행 중 수강생').getByText('0')).toBeTruthy();
	});

	it('진행 중 강좌마다 이름, 분반, 수강생 수, 열기가 있고 열기는 그 강좌로 간다', () => {
		show();
		const items = screen.getAllByRole('listitem');
		expect(items).toHaveLength(2);
		const first = within(items[0]);
		expect(first.getByText('데이터베이스')).toBeTruthy();
		expect(first.getByText('수요반')).toBeTruthy();
		expect(first.getByText(/55명/)).toBeTruthy();
		expect(first.getByRole('link', { name: /^열기/ }).getAttribute('href')).toBe('/courses/3/admin');
		const second = within(items[1]);
		expect(second.getByText('분반 없음')).toBeTruthy();
		expect(second.getByRole('link', { name: /^열기/ }).getAttribute('href')).toBe('/courses/2/admin');
	});

	it('열기 링크는 어느 강좌의 것인지 이름에 들어 있다', () => {
		show();
		const names = screen.getAllByRole('link', { name: /^열기/ }).map((a) => a.getAttribute('aria-label'));
		expect(names).toEqual(['열기: 데이터베이스 (수요반)', '열기: 웹 프로그래밍']);
	});

	it('진행 중 강좌가 없으면 안내와 내 강좌 링크가 있다', () => {
		show({ ...DATA, counts: { active: 0, archived: 3 }, active_students: 0, active_classrooms: [] });
		expect(screen.queryAllByRole('listitem')).toHaveLength(0);
		expect(screen.getByText(/진행 중인 강좌가 없습니다/)).toBeTruthy();
		expect(screen.getByRole('link', { name: '내 강좌에서 만들기' }).getAttribute('href')).toBe('/courses');
	});
});
