// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const nav = vi.hoisted(() => ({ invalidate: vi.fn(() => Promise.resolve()), goto: vi.fn(() => Promise.resolve()) }));
const api = vi.hoisted(() => ({ createClassroom: vi.fn(), cloneClassroom: vi.fn(), archiveClassroom: vi.fn() }));
vi.mock('$app/navigation', () => nav);
vi.mock('#lib/api.js', async (original) => ({
	...(await original<object>()),
	createClassroom: api.createClassroom,
	cloneClassroom: api.cloneClassroom,
	archiveClassroom: api.archiveClassroom
}));

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
	api.cloneClassroom.mockReset();
	api.archiveClassroom.mockReset();
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

describe('분반 만들기·새 학기로 복제 (AC11)', () => {
	const card = (title: string, section?: string) =>
		screen
			.getAllByRole('heading', { level: 2, name: title })
			.map((h) => h.closest('li') as HTMLElement)
			.find((li) => !section || within(li).queryByText(section)) as HTMLElement;

	it('진행 중 카드에는 "분반 만들기", 보관됨 카드에는 "새 학기로 복제" 버튼이 있다', async () => {
		render(CoursesPage, { params: {}, data: { ...DATA, me: null } });
		for (const li of [card('데이터베이스'), card('웹 프로그래밍', '분반 없음')]) {
			expect(within(li).getByRole('button', { name: /^분반 만들기/ })).toBeTruthy();
			expect(within(li).queryByRole('button', { name: /새 학기로 복제/ })).toBeNull();
		}
		await openTab(/보관됨/);
		const archived = card('웹 프로그래밍');
		expect(within(archived).getByRole('button', { name: /^새 학기로 복제/ })).toBeTruthy();
		expect(within(archived).queryByRole('button', { name: /분반 만들기/ })).toBeNull();
	});

	it('같은 이름의 버튼이 여러 개여도 어느 강좌의 것인지 이름으로 구분된다', () => {
		render(CoursesPage, { params: {}, data: { ...DATA, me: null } });
		const names = screen.getAllByRole('button', { name: /^분반 만들기/ }).map((b) => b.getAttribute('aria-label'));
		expect(names).toEqual(['분반 만들기: 데이터베이스 (수요반)', '분반 만들기: 웹 프로그래밍']);
	});

	it('누르면 그 강좌의 이름과 분반이 채워진 폼이 열리고 이름 칸에 포커스가 간다', async () => {
		render(CoursesPage, { params: {}, data: { ...DATA, me: null } });
		await fireEvent.click(within(card('데이터베이스')).getByRole('button', { name: /^분반 만들기/ }));
		const name = (await screen.findByLabelText('강좌 이름')) as HTMLInputElement;
		expect(name.value).toBe('데이터베이스');
		expect((screen.getByLabelText(/분반 이름/) as HTMLInputElement).value).toBe('수요반');
		expect(screen.getByRole('heading', { level: 2, name: '분반 만들기' })).toBeTruthy();
		expect(document.activeElement).toBe(name);
		expect((screen.getByRole('button', { name: '만들기' }) as HTMLButtonElement).disabled).toBe(false);
		expect(screen.getByText(/수강생 명단과 기록은 새로 시작합니다/)).toBeTruthy();
	});

	it('채워진 이름은 선택되어 있어서 바로 타자를 쳐서 고칠 수 있다', async () => {
		render(CoursesPage, { params: {}, data: { ...DATA, me: null } });
		await fireEvent.click(within(card('데이터베이스')).getByRole('button', { name: /^분반 만들기/ }));
		const name = (await screen.findByLabelText('강좌 이름')) as HTMLInputElement;
		expect([name.selectionStart, name.selectionEnd]).toEqual([0, name.value.length]);
	});

	it('분반이 없는 강좌는 분반 칸이 비어 있다', async () => {
		render(CoursesPage, { params: {}, data: { ...DATA, me: null } });
		await fireEvent.click(within(card('웹 프로그래밍', '분반 없음')).getByRole('button', { name: /^분반 만들기/ }));
		await screen.findByLabelText('강좌 이름');
		expect((screen.getByLabelText(/분반 이름/) as HTMLInputElement).value).toBe('');
	});

	it('이름과 분반을 고쳐서 만들면 그 값으로 복제하고 목록을 다시 불러오고 폼을 닫는다', async () => {
		api.cloneClassroom.mockResolvedValue(item(9, '데이터베이스 2반', '목요반', 'active', 0));
		render(CoursesPage, { params: {}, data: { ...DATA, me: null } });
		await fireEvent.click(within(card('데이터베이스')).getByRole('button', { name: /^분반 만들기/ }));
		const name = (await screen.findByLabelText('강좌 이름')) as HTMLInputElement;
		await fireEvent.input(name, { target: { value: '  데이터베이스 2반  ' } });
		await fireEvent.input(screen.getByLabelText(/분반 이름/), { target: { value: '목요반' } });
		await fireEvent.click(screen.getByRole('button', { name: '만들기' }));
		await waitFor(() => expect(nav.invalidate).toHaveBeenCalledWith('app:classrooms'));
		expect(api.cloneClassroom).toHaveBeenCalledWith(3, { name: '데이터베이스 2반', section_name: '목요반' });
		expect(api.createClassroom).not.toHaveBeenCalled(); // 새로 만들기가 아니라 복제다
		await waitFor(() => expect(screen.queryByLabelText('강좌 이름')).toBeNull());
		expect(tab(/진행 중/).getAttribute('aria-selected')).toBe('true');
		expect(screen.getByRole('status').textContent).toContain('데이터베이스 2반');
	});

	it('보관된 강좌의 "새 학기로 복제"는 폼 제목이 다르고 보관된 강좌를 원본으로 보낸다', async () => {
		api.cloneClassroom.mockResolvedValue(item(9, '웹 프로그래밍', '월수반', 'active', 0));
		render(CoursesPage, { params: {}, data: { ...DATA, me: null } });
		await openTab(/보관됨/);
		await fireEvent.click(within(card('웹 프로그래밍')).getByRole('button', { name: /^새 학기로 복제/ }));
		await screen.findByLabelText('강좌 이름');
		expect(screen.getByRole('heading', { level: 2, name: '새 학기로 복제' })).toBeTruthy();
		await fireEvent.click(screen.getByRole('button', { name: '만들기' }));
		await waitFor(() => expect(api.cloneClassroom).toHaveBeenCalledWith(1, { name: '웹 프로그래밍', section_name: '월수반' }));
		await waitFor(() => expect(tab(/진행 중/).getAttribute('aria-selected')).toBe('true')); // 새 강좌는 진행 중에 생긴다
	});

	it('보관된 강좌에서 복제 폼을 열어도 보관됨 탭에 머문다(눌렀던 카드가 보여야 포커스를 돌려줄 수 있다)', async () => {
		render(CoursesPage, { params: {}, data: { ...DATA, me: null } });
		await openTab(/보관됨/);
		await fireEvent.click(within(card('웹 프로그래밍')).getByRole('button', { name: /^새 학기로 복제/ }));
		await screen.findByLabelText('강좌 이름');
		expect(tab(/보관됨/).getAttribute('aria-selected')).toBe('true');
		expect(within(card('웹 프로그래밍')).getByRole('button', { name: /^새 학기로 복제/ })).toBeTruthy();
	});

	it('이름을 지우면 만들기를 누를 수 없고 이유가 보인다 (AC6와 같은 규칙)', async () => {
		render(CoursesPage, { params: {}, data: { ...DATA, me: null } });
		await fireEvent.click(within(card('데이터베이스')).getByRole('button', { name: /^분반 만들기/ }));
		await fireEvent.input(await screen.findByLabelText('강좌 이름'), { target: { value: '' } });
		expect((screen.getByRole('button', { name: '만들기' }) as HTMLButtonElement).disabled).toBe(true);
		expect(screen.getByText('강좌 이름을 입력해 주세요.')).toBeTruthy();
	});

	it('서버가 거부하면 이유를 보여 주고 폼을 그대로 둔다', async () => {
		api.cloneClassroom.mockRejectedValue(new ApiError(403, '이 강좌를 볼 권한이 없습니다.'));
		render(CoursesPage, { params: {}, data: { ...DATA, me: null } });
		await fireEvent.click(within(card('데이터베이스')).getByRole('button', { name: /^분반 만들기/ }));
		await fireEvent.click(await screen.findByRole('button', { name: '만들기' }));
		expect((await screen.findByRole('alert')).textContent).toContain('이 강좌를 볼 권한이 없습니다.');
		expect(screen.getByLabelText('강좌 이름')).toBeTruthy();
		expect(nav.invalidate).not.toHaveBeenCalled();
	});

	it('취소하면 서버를 부르지 않고 폼을 닫고 포커스가 눌렀던 카드의 버튼으로 돌아간다', async () => {
		render(CoursesPage, { params: {}, data: { ...DATA, me: null } });
		const opener = within(card('데이터베이스')).getByRole('button', { name: /^분반 만들기/ });
		opener.focus();
		await fireEvent.click(opener);
		await screen.findByLabelText('강좌 이름');
		await fireEvent.click(screen.getByRole('button', { name: '취소' }));
		await waitFor(() => expect(screen.queryByLabelText('강좌 이름')).toBeNull());
		expect(api.cloneClassroom).not.toHaveBeenCalled();
		await waitFor(() => expect(document.activeElement).toBe(opener));
	});

	it('복제 폼이 열려 있을 때 새 강좌 만들기를 누르면 빈 폼으로 바뀐다(폼은 하나만)', async () => {
		render(CoursesPage, { params: {}, data: { ...DATA, me: null } });
		await fireEvent.click(within(card('데이터베이스')).getByRole('button', { name: /^분반 만들기/ }));
		await screen.findByLabelText('강좌 이름');
		await fireEvent.click(screen.getByRole('button', { name: '새 강좌 만들기' }));
		await waitFor(() => expect((screen.getByLabelText('강좌 이름') as HTMLInputElement).value).toBe(''));
		expect(screen.getAllByLabelText('강좌 이름')).toHaveLength(1);
		expect(screen.getByRole('heading', { level: 2, name: '새 강좌 만들기' })).toBeTruthy();
	});

	it('복제 폼 뒤에 새 강좌 만들기를 다시 열어도 이전 값이 남지 않는다', async () => {
		render(CoursesPage, { params: {}, data: { ...DATA, me: null } });
		await fireEvent.click(within(card('데이터베이스')).getByRole('button', { name: /^분반 만들기/ }));
		await screen.findByLabelText('강좌 이름');
		await fireEvent.click(screen.getByRole('button', { name: '취소' }));
		await waitFor(() => expect(screen.queryByLabelText('강좌 이름')).toBeNull());
		await fireEvent.click(screen.getByRole('button', { name: '새 강좌 만들기' }));
		expect(((await screen.findByLabelText('강좌 이름')) as HTMLInputElement).value).toBe('');
	});
});

describe('강좌 보관 (AC9)', () => {
	const CONFIRM = '보관하면 학생이 더 이상 입장할 수 없고 모든 학생의 로그인 유지가 끝납니다. 기록은 볼 수 있습니다.';
	const archiveButton = (name = '보관: 데이터베이스 (수요반)') => screen.getByRole('button', { name });
	async function openDialog() {
		render(CoursesPage, { params: {}, data: { ...DATA, me: null } });
		const opener = archiveButton();
		await fireEvent.click(opener);
		const dialog = await screen.findByRole('alertdialog');
		return { opener, dialog };
	}

	it('진행 중 카드에만 "보관" 버튼이 있고, 이름으로 어느 강좌인지 구분된다', async () => {
		render(CoursesPage, { params: {}, data: { ...DATA, me: null } });
		expect(archiveButton().textContent?.trim()).toBe('보관');
		expect(archiveButton('보관: 웹 프로그래밍')).toBeTruthy();
		await openTab(/보관됨/);
		expect(screen.queryByRole('button', { name: /^보관:/ })).toBeNull();
	});

	it('누르면 서버를 부르기 전에 확인 문구가 나온다', async () => {
		const { dialog } = await openDialog();
		expect(within(dialog).getByRole('heading', { name: '데이터베이스 (수요반) 강좌를 보관할까요?' })).toBeTruthy();
		expect(within(dialog).getByText(CONFIRM)).toBeTruthy();
		expect(dialog.getAttribute('aria-describedby')).toBeTruthy();
		expect(api.archiveClassroom).not.toHaveBeenCalled();
	});

	it('확인 창이 열리면 포커스는 되돌릴 수 없는 보관이 아니라 취소에 간다', async () => {
		const { dialog } = await openDialog();
		await waitFor(() => expect(document.activeElement).toBe(within(dialog).getByRole('button', { name: '취소' })));
	});

	it('취소하면 서버를 부르지 않고 창을 닫고 포커스가 보관 버튼으로 돌아간다', async () => {
		const { opener, dialog } = await openDialog();
		await fireEvent.click(within(dialog).getByRole('button', { name: '취소' }));
		await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
		expect(api.archiveClassroom).not.toHaveBeenCalled();
		await waitFor(() => expect(document.activeElement).toBe(opener));
	});

	it('확인하면 보관하고, 목록을 다시 불러오고, 보관됨 탭으로 옮겨 결과를 알린다', async () => {
		api.archiveClassroom.mockResolvedValue(item(3, '데이터베이스', '수요반', 'archived', 55));
		const { dialog } = await openDialog();
		await fireEvent.click(within(dialog).getByRole('button', { name: '보관' }));
		await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
		expect(api.archiveClassroom).toHaveBeenCalledWith(3);
		expect(nav.invalidate).toHaveBeenCalledWith('app:classrooms');
		expect(tab(/보관됨/).getAttribute('aria-selected')).toBe('true');
		expect(screen.getByRole('status').textContent).toContain('강좌를 보관했습니다: 데이터베이스');
		await waitFor(() => expect(document.activeElement).toBe(tab(/보관됨/))); // 눌렀던 카드는 사라졌다
	});

	it('보관 버튼은 되돌릴 수 없는 동작임을 색과 글자로 알린다', async () => {
		const { dialog } = await openDialog();
		expect(within(dialog).getByRole('button', { name: '보관' }).className).toContain('btn-destructive');
	});

	it('보관하는 동안에는 다시 누를 수 없다', async () => {
		let finish: (v: unknown) => void = () => {};
		api.archiveClassroom.mockReturnValue(new Promise((r) => (finish = r)));
		const { dialog } = await openDialog();
		const confirm = within(dialog).getByRole('button', { name: '보관' });
		await fireEvent.click(confirm);
		await waitFor(() => expect((within(dialog).getByRole('button', { name: '보관하는 중…' }) as HTMLButtonElement).disabled).toBe(true));
		expect((within(dialog).getByRole('button', { name: '취소' }) as HTMLButtonElement).disabled).toBe(true);
		await fireEvent.click(within(dialog).getByRole('button', { name: '보관하는 중…' }));
		expect(api.archiveClassroom).toHaveBeenCalledTimes(1);
		finish(item(3, '데이터베이스', '수요반', 'archived', 55));
		await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
	});

	it('서버가 거부하면 이유와 할 일을 창 안에 보여 주고 창을 그대로 둔다', async () => {
		api.archiveClassroom.mockRejectedValue(new ApiError(500, '요청을 처리하지 못했습니다 (500)'));
		const { dialog } = await openDialog();
		await fireEvent.click(within(dialog).getByRole('button', { name: '보관' }));
		const alert = await within(dialog).findByRole('alert');
		expect(alert.textContent).toContain('요청을 처리하지 못했습니다 (500)');
		expect(alert.textContent).toContain('잠시 뒤 다시 시도해 주세요.');
		expect(screen.getByRole('alertdialog')).toBeTruthy();
		expect(tab(/진행 중/).getAttribute('aria-selected')).toBe('true');
	});

	it('이미 보관된 강좌면(다른 창에서 보관) 목록을 다시 불러오고 보관됨 탭에서 확인하라고 알린다', async () => {
		api.archiveClassroom.mockRejectedValue(new ApiError(409, '이미 보관된 강좌입니다.'));
		const { dialog } = await openDialog();
		await fireEvent.click(within(dialog).getByRole('button', { name: '보관' }));
		const alert = await within(dialog).findByRole('alert');
		expect(alert.textContent).toContain('이미 보관된 강좌입니다.');
		expect(alert.textContent).toContain('보관됨 탭에서 확인하세요.');
		expect(nav.invalidate).toHaveBeenCalledWith('app:classrooms');
	});

	it('수업 중이면 보관하지 않고 이유와 수업 화면으로 가는 버튼을 보인다 (002 AC46)', async () => {
		const detail = '1회차 수업이 진행 중입니다. 수업을 끝낸 뒤 보관해 주세요.';
		api.archiveClassroom.mockRejectedValue(new ApiError(409, detail, undefined, { live_session_id: 12 }));
		const { dialog } = await openDialog();
		await fireEvent.click(within(dialog).getByRole('button', { name: '보관' }));
		const alert = await within(dialog).findByRole('alert');
		expect(alert.textContent).toContain(detail);
		const link = within(dialog).getByRole('link', { name: '수업 화면으로' });
		expect(link.getAttribute('href')).toBe('/courses/3/live');
		expect(link.className).toContain('btn btn-default'); // 44px 주 버튼 모양(테마에 있는 클래스)
		expect(nav.invalidate).not.toHaveBeenCalled(); // 아무것도 바뀌지 않았다
		expect(tab(/진행 중/).getAttribute('aria-selected')).toBe('true');
	});

	it('연결이 안 되면 무엇을 하면 되는지 알려 준다', async () => {
		api.archiveClassroom.mockRejectedValue(new TypeError('Failed to fetch'));
		const { dialog } = await openDialog();
		await fireEvent.click(within(dialog).getByRole('button', { name: '보관' }));
		const alert = await within(dialog).findByRole('alert');
		expect(alert.textContent).toContain('강좌를 보관하지 못했습니다.');
		expect(alert.textContent).toContain('네트워크 연결을 확인하고 다시 시도해 주세요.');
	});
});
