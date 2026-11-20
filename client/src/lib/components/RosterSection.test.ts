// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({ addStudent: vi.fn(), importRoster: vi.fn() }));
vi.mock('#lib/api.js', async (original) => ({ ...(await original<object>()), ...api }));

import RosterSection from './RosterSection.svelte';

const entry = (id: number, no: string, name: string, email: string, entered: boolean) => ({
	id, student_no: no, name, email, entered
});
const ROSTER = {
	entries: [entry(1, '20240001', '김철수', 'kim@x.kr', true), entry(2, '20240002', '이영희', 'lee@x.kr', false)],
	count: 2,
	limit: 200
};
const show = (roster = ROSTER, onChanged = vi.fn()) => {
	render(RosterSection, { classroomId: 7, roster, onChanged });
	return onChanged;
};

beforeEach(() => {
	api.addStudent.mockReset();
	api.importRoster.mockReset();
});
afterEach(cleanup);

describe('수강생 명단 (AC17)', () => {
	it('제목과 인원(N / 200명)이 보인다', () => {
		show();
		expect(screen.getByRole('heading', { level: 2, name: '수강생 명단' })).toBeTruthy();
		expect(screen.getByText('2 / 200명')).toBeTruthy();
	});

	it('표에 학번, 이름, 이메일, 입장 상태 열이 있다', () => {
		show();
		const headers = screen.getAllByRole('columnheader').map((h) => h.textContent?.trim());
		expect(headers).toEqual(['학번', '이름', '이메일', '입장 상태']);
	});

	it('학생마다 학번, 이름, 이메일과 입장함/입장 전이 글로 보인다', () => {
		show();
		const rows = screen.getAllByRole('row').slice(1);
		expect(rows).toHaveLength(2);
		expect(within(rows[0]).getAllByRole('cell').map((c) => c.textContent?.trim())).toEqual([
			'20240001', '김철수', 'kim@x.kr', '입장함'
		]);
		expect(within(rows[1]).getAllByRole('cell').map((c) => c.textContent?.trim())).toEqual([
			'20240002', '이영희', 'lee@x.kr', '입장 전'
		]);
	});

	it('닉네임은 어디에도 보이지 않는다(C9)', () => {
		show();
		expect(document.body.textContent).not.toContain('닉네임');
		expect(screen.queryByRole('columnheader', { name: /닉네임/ })).toBeNull();
	});

	it('표는 이름을 가진 영역 안에 있어 좁은 화면에서 가로로 스크롤해도 키보드로 닿는다', () => {
		show();
		const region = screen.getByRole('region', { name: '수강생 명단 표' });
		expect(region.getAttribute('tabindex')).toBe('0');
		expect(within(region).getByRole('table')).toBeTruthy();
	});

	it('학생이 없으면 안내가 나오고 표는 없다', () => {
		show({ entries: [], count: 0, limit: 200 });
		expect(screen.queryByRole('table')).toBeNull();
		expect(screen.getByText(/아직 등록된 학생이 없습니다/)).toBeTruthy();
		expect(screen.getByText('0 / 200명')).toBeTruthy();
	});

	it('200명이면 가득 찼다고 알려 준다', () => {
		const full = { entries: [entry(1, '1', '김', 'a@x.kr', false)], count: 200, limit: 200 };
		show(full);
		expect(screen.getByText('200 / 200명')).toBeTruthy();
		expect(screen.getByText(/가득 찼습니다/)).toBeTruthy();
	});

	it('가득 차지 않았으면 가득 찼다는 말이 없다', () => {
		show();
		expect(screen.queryByText(/가득 찼습니다/)).toBeNull();
	});

	it('학생 추가 폼과 CSV 올리기가 같은 영역에 있다', () => {
		show();
		expect(screen.getByLabelText('학번')).toBeTruthy();
		expect(screen.getByLabelText('CSV 파일')).toBeTruthy();
	});

	it('학생을 추가하면 명단을 다시 불러오고 추가했다고 알린다', async () => {
		api.addStudent.mockResolvedValue({ id: 3, student_no: '3', name: '박민수', email: 'p@x.kr' });
		const onChanged = show();
		await fireEvent.input(screen.getByLabelText('학번'), { target: { value: '3' } });
		await fireEvent.input(screen.getByLabelText('이름'), { target: { value: '박민수' } });
		await fireEvent.input(screen.getByLabelText('이메일'), { target: { value: 'p@x.kr' } });
		await fireEvent.click(screen.getByRole('button', { name: '학생 추가' }));
		await waitFor(() => expect(onChanged).toHaveBeenCalled());
		expect((await screen.findByRole('status')).textContent).toContain('박민수');
	});

	it('CSV를 올리면 명단을 다시 불러온다', async () => {
		api.importRoster.mockResolvedValue({ added: 5, skipped: 0, skipped_lines: [] });
		const onChanged = show();
		const input = screen.getByLabelText('CSV 파일');
		Object.defineProperty(input, 'files', { value: [new File(['x'], 'a.csv')], configurable: true });
		await fireEvent.change(input);
		await fireEvent.click(screen.getByRole('button', { name: '올리기' }));
		await waitFor(() => expect(onChanged).toHaveBeenCalled());
	});

	it('추가에 실패하면 명단을 다시 불러오지 않는다', async () => {
		api.addStudent.mockRejectedValue(new TypeError('network'));
		const onChanged = show();
		for (const [l, v] of [['학번', '3'], ['이름', '박'], ['이메일', 'p@x.kr']]) {
			await fireEvent.input(screen.getByLabelText(l), { target: { value: v } });
		}
		await fireEvent.click(screen.getByRole('button', { name: '학생 추가' }));
		await screen.findByRole('alert');
		expect(onChanged).not.toHaveBeenCalled();
	});
});
