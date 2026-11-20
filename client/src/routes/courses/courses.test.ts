// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const nav = vi.hoisted(() => ({ invalidate: vi.fn(() => Promise.resolve()), goto: vi.fn(() => Promise.resolve()) }));
const api = vi.hoisted(() => ({ createClassroom: vi.fn() }));
vi.mock('$app/navigation', () => nav);
vi.mock('#lib/api.js', async (original) => ({ ...(await original<object>()), createClassroom: api.createClassroom }));

import { ApiError } from '#lib/api.js';
import CoursesPage from './+page.svelte';

const item = (id: number, name: string, section: string | null, status: 'active' | 'archived', students: number) => ({
	id, name, section_name: section, status, student_count: students, created_at: '2026-03-01T09:00:00+00:00'
});
const DATA = {
	classrooms: [
		item(3, '데이터베이스', '수요반', 'active', 55),
		item(2, '웹 프로그래밍', null, 'active', 38),
		item(1, '웹 프로그래밍', '월수반', 'archived', 40)
	],
	counts: { active: 2, archived: 1 }
};

beforeEach(() => {
	nav.invalidate.mockClear();
	api.createClassroom.mockReset();
});
afterEach(cleanup);

const cardTitles = () => screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent?.trim());
const tab = (name: RegExp) => screen.getByRole('tab', { name });
async function openTab(name: RegExp) {
	const t = tab(name);
	await fireEvent.mouseDown(t);
	await fireEvent.click(t);
	await waitFor(() => expect(t.getAttribute('aria-selected')).toBe('true'));
}

describe('내 강좌 목록 (AC7)', () => {
	it('제목과 새 강좌 만들기 버튼이 있고 페이지 제목이 있다', () => {
		render(CoursesPage, { params: {}, data: { ...DATA, me: null } });
		expect(screen.getByRole('heading', { level: 1, name: '내 강좌' })).toBeTruthy();
		expect(screen.getByRole('button', { name: '새 강좌 만들기' })).toBeTruthy();
		expect(document.title).toContain('내 강좌');
	});

	it("탭에 '진행 중 N / 보관됨 N' 개수가 보이고 처음에는 진행 중이 선택된다", () => {
		render(CoursesPage, { params: {}, data: { ...DATA, me: null } });
		expect(screen.getByRole('tablist')).toBeTruthy();
		const active = tab(/진행 중/);
		const archived = tab(/보관됨/);
		expect(active.textContent).toContain('2');
		expect(archived.textContent).toContain('1');
		expect(active.getAttribute('aria-selected')).toBe('true');
		expect(archived.getAttribute('aria-selected')).toBe('false');
	});

	it('진행 중 탭에는 진행 중 강좌만 카드로 보인다', () => {
		render(CoursesPage, { params: {}, data: { ...DATA, me: null } });
		expect(cardTitles()).toEqual(['데이터베이스', '웹 프로그래밍']);
		expect(screen.getAllByRole('link', { name: '열기' }).map((a) => a.getAttribute('href'))).toEqual([
			'/courses/3/admin',
			'/courses/2/admin'
		]);
		expect(screen.queryByRole('link', { name: '기록 보기' })).toBeNull();
	});

	it('카드에는 이름, 분반, 상태 배지(문구), 수강생 수, 열기 버튼이 있다', () => {
		render(CoursesPage, { params: {}, data: { ...DATA, me: null } });
		const card = screen.getByRole('heading', { level: 2, name: '데이터베이스' }).closest('li') as HTMLElement;
		expect(within(card).getByText('수요반')).toBeTruthy();
		expect(within(card).getByText('진행 중').className).toContain('badge-success');
		expect(within(card).getByText('수강생 55명')).toBeTruthy();
		expect(within(card).getByRole('link', { name: '열기' })).toBeTruthy();
	});

	it('분반이 없으면 "분반 없음"이라고 보여 준다', () => {
		render(CoursesPage, { params: {}, data: { ...DATA, me: null } });
		const card = screen.getAllByRole('heading', { level: 2, name: '웹 프로그래밍' })[0].closest('li') as HTMLElement;
		expect(within(card).getByText('분반 없음')).toBeTruthy();
	});

	it('보관됨 탭에는 보관된 강좌가 "기록 보기" 버튼과 함께 보인다', async () => {
		render(CoursesPage, { params: {}, data: { ...DATA, me: null } });
		await openTab(/보관됨/);
		expect(cardTitles()).toEqual(['웹 프로그래밍']);
		const card = screen.getByRole('heading', { level: 2, name: '웹 프로그래밍' }).closest('li') as HTMLElement;
		expect(within(card).getByText('월수반')).toBeTruthy();
		expect(within(card).getByText('보관됨').className).toContain('badge-secondary');
		expect(within(card).getByRole('link', { name: '기록 보기' }).getAttribute('href')).toBe('/courses/1/admin');
		expect(screen.queryByRole('link', { name: '열기' })).toBeNull();
	});

	it('탭 목록 아래에 내용이 세로로 쌓인다(가로로 나란히 놓이면 내용이 좁게 깨진다)', () => {
		render(CoursesPage, { params: {}, data: { ...DATA, me: null } });
		const root = screen.getByRole('tablist').parentElement as HTMLElement;
		expect(root.className).toContain('flex-col');
		expect(root.className).not.toContain('data-horizontal'); // bits-ui는 이 속성을 붙이지 않아 조건부 클래스가 적용되지 않는다
	});

	it('탭의 포커스 링은 불투명 2px에 간격 2px이다 (C14)', () => {
		render(CoursesPage, { params: {}, data: { ...DATA, me: null } });
		for (const t of screen.getAllByRole('tab')) {
			expect(t.className).toContain('tabs-line-trigger'); // 2px 불투명 링(theme.css)
			expect(t.className).toContain('focus-visible:ring-offset-2'); // 간격 2px
		}
	});

	it('탭은 방향키로도 옮겨진다', async () => {
		render(CoursesPage, { params: {}, data: { ...DATA, me: null } });
		const active = tab(/진행 중/);
		active.focus();
		await fireEvent.keyDown(active, { key: 'ArrowRight' });
		await waitFor(() => expect(tab(/보관됨/).getAttribute('aria-selected')).toBe('true'));
	});

	it('강좌가 없으면 빈 화면이 아니라 다음에 할 일을 알려 준다', async () => {
		render(CoursesPage, { params: {}, data: { me: null, classrooms: [], counts: { active: 0, archived: 0 } } });
		expect(screen.getByText(/진행 중인 강좌가 없습니다/)).toBeTruthy();
		expect(screen.getByText(/새 강좌 만들기/, { selector: 'p *, p' })).toBeTruthy();
		await openTab(/보관됨/);
		expect(screen.getByText('보관된 강좌가 없습니다.')).toBeTruthy();
	});
});

describe('새 강좌 만들기 (AC5, AC6)', () => {
	async function openForm() {
		render(CoursesPage, { params: {}, data: { ...DATA, me: null } });
		await fireEvent.click(screen.getByRole('button', { name: '새 강좌 만들기' }));
		return {
			name: (await screen.findByLabelText('강좌 이름')) as HTMLInputElement,
			section: screen.getByLabelText(/분반 이름/) as HTMLInputElement,
			submit: screen.getByRole('button', { name: '만들기' }) as HTMLButtonElement
		};
	}

	it('폼이 열리면 이름 칸으로 포커스가 간다', async () => {
		const { name } = await openForm();
		expect(document.activeElement).toBe(name);
		expect(screen.getByLabelText(/분반 이름 \(선택\)/)).toBeTruthy();
	});

	it('이름이 비어 있으면 만들기를 누를 수 없고 이유가 글로 보인다 (AC6)', async () => {
		const { name, submit } = await openForm();
		expect(submit.disabled).toBe(true);
		const hint = screen.getByText('강좌 이름을 입력해 주세요.');
		expect(name.getAttribute('aria-describedby')).toContain(hint.id); // 읽어 주는 도구도 이유를 전달한다
		await fireEvent.input(name, { target: { value: '   ' } });
		expect(submit.disabled).toBe(true);
		expect(screen.getByText('강좌 이름을 입력해 주세요.')).toBeTruthy();
	});

	it('이름을 쓰면 만들기가 켜지고 이유 문구가 사라진다', async () => {
		const { name, submit } = await openForm();
		await fireEvent.input(name, { target: { value: '알고리즘' } });
		expect(submit.disabled).toBe(false);
		expect(screen.queryByText('강좌 이름을 입력해 주세요.')).toBeNull();
	});

	it('이름과 분반 칸에 길이 제한이 있다', async () => {
		const { name, section } = await openForm();
		expect(name.maxLength).toBe(100);
		expect(section.maxLength).toBe(50);
	});

	it('만들면 서버에 이름과 분반을 보내고, 목록을 다시 불러오고, 폼을 닫고, 진행 중 탭을 보인다', async () => {
		api.createClassroom.mockResolvedValue(item(9, '알고리즘', '월수반', 'active', 0));
		const { name, section, submit } = await openForm();
		await openTab(/보관됨/).catch(() => {}); // 폼이 열려 있어도 탭은 바꿀 수 있다
		await fireEvent.input(name, { target: { value: '  알고리즘  ' } });
		await fireEvent.input(section, { target: { value: ' 월수반 ' } });
		await fireEvent.click(submit);
		await waitFor(() => expect(nav.invalidate).toHaveBeenCalledWith('app:classrooms'));
		expect(api.createClassroom).toHaveBeenCalledWith({ name: '알고리즘', section_name: '월수반' });
		await waitFor(() => expect(screen.queryByLabelText('강좌 이름')).toBeNull());
		expect(tab(/진행 중/).getAttribute('aria-selected')).toBe('true');
		expect(screen.getByRole('status').textContent).toContain('알고리즘');
	});

	it('분반을 비워 두면 분반 없이 보낸다', async () => {
		api.createClassroom.mockResolvedValue(item(9, '자료구조', null, 'active', 0));
		const { name, submit } = await openForm();
		await fireEvent.input(name, { target: { value: '자료구조' } });
		await fireEvent.click(submit);
		await waitFor(() => expect(api.createClassroom).toHaveBeenCalledWith({ name: '자료구조', section_name: null }));
	});

	it('서버가 거부하면 그 이유를 보여 주고 폼과 입력한 값을 그대로 둔다', async () => {
		api.createClassroom.mockRejectedValue(new ApiError(422, '강좌 이름은 100자 이하로 입력해 주세요.'));
		const { name, submit } = await openForm();
		await fireEvent.input(name, { target: { value: '긴 이름' } });
		await fireEvent.click(submit);
		const alert = await screen.findByRole('alert');
		expect(alert.textContent).toContain('강좌 이름은 100자 이하로 입력해 주세요.');
		expect((screen.getByLabelText('강좌 이름') as HTMLInputElement).value).toBe('긴 이름');
		expect(nav.invalidate).not.toHaveBeenCalled();
	});

	it('연결이 안 되면 무엇을 하면 되는지 알려 준다', async () => {
		api.createClassroom.mockRejectedValue(new TypeError('network'));
		const { name, submit } = await openForm();
		await fireEvent.input(name, { target: { value: '알고리즘' } });
		await fireEvent.click(submit);
		const alert = await screen.findByRole('alert');
		expect(alert.textContent).toContain('강좌를 만들지 못했습니다');
		expect(alert.textContent).toContain('네트워크 연결을 확인하고 다시 시도');
		expect(submit.disabled).toBe(false); // 다시 시도할 수 있다
	});

	it('만드는 동안에는 다시 누를 수 없다(중복 생성 방지)', async () => {
		let release!: () => void;
		api.createClassroom.mockImplementation(() => new Promise((resolve) => (release = () => resolve(item(9, 'x', null, 'active', 0)))));
		const { name, submit } = await openForm();
		await fireEvent.input(name, { target: { value: '알고리즘' } });
		await fireEvent.click(submit);
		await waitFor(() => expect(submit.disabled).toBe(true));
		await fireEvent.click(submit);
		expect(api.createClassroom).toHaveBeenCalledTimes(1);
		release();
		await waitFor(() => expect(nav.invalidate).toHaveBeenCalled());
	});

	it('버튼이 아니라 폼을 직접 제출해도(예: Enter) 만드는 동안에는 한 번만 보낸다', async () => {
		let release!: () => void;
		api.createClassroom.mockImplementation(() => new Promise((resolve) => (release = () => resolve(item(9, 'x', null, 'active', 0)))));
		const { name, submit } = await openForm();
		await fireEvent.input(name, { target: { value: '알고리즘' } });
		await fireEvent.click(submit);
		await waitFor(() => expect(submit.disabled).toBe(true));
		const form = document.querySelector('#create-form') as HTMLFormElement;
		await fireEvent.submit(form); // 비활성 버튼을 거치지 않는 제출
		await fireEvent.submit(form);
		expect(api.createClassroom).toHaveBeenCalledTimes(1);
		release();
		await waitFor(() => expect(nav.invalidate).toHaveBeenCalled());
	});

	it('이름이 비어 있을 때 폼을 직접 제출해도 서버를 부르지 않는다', async () => {
		await openForm();
		await fireEvent.submit(document.querySelector('#create-form') as HTMLFormElement);
		expect(api.createClassroom).not.toHaveBeenCalled();
	});

	it('취소하면 서버를 부르지 않고 폼을 닫고 포커스가 새 강좌 만들기 버튼으로 돌아간다', async () => {
		const { name } = await openForm();
		await fireEvent.input(name, { target: { value: '쓰다 만 이름' } });
		await fireEvent.click(screen.getByRole('button', { name: '취소' }));
		await waitFor(() => expect(screen.queryByLabelText('강좌 이름')).toBeNull());
		expect(api.createClassroom).not.toHaveBeenCalled();
		await waitFor(() => expect(document.activeElement).toBe(screen.getByRole('button', { name: '새 강좌 만들기' })));
		await fireEvent.click(screen.getByRole('button', { name: '새 강좌 만들기' }));
		expect((await screen.findByLabelText('강좌 이름') as HTMLInputElement).value).toBe(''); // 다시 열면 비어 있다
	});
});
