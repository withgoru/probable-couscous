// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({ addStudent: vi.fn(), importRoster: vi.fn(), removeStudent: vi.fn(), revokeStudentLogin: vi.fn() }));
vi.mock('#lib/api.js', async (original) => ({ ...(await original<object>()), ...api }));

import { ApiError } from '#lib/api.js';
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
	api.removeStudent.mockReset();
	api.revokeStudentLogin.mockReset();
});
afterEach(cleanup);

describe('수강생 명단 (AC17)', () => {
	it('제목과 인원(N / 200명)이 보인다', () => {
		show();
		expect(screen.getByRole('heading', { level: 2, name: '수강생 명단' })).toBeTruthy();
		expect(screen.getByText('2 / 200명')).toBeTruthy();
	});

	it('표에 학번, 이름, 이메일, 입장 상태, 관리 열이 있다', () => {
		show();
		const headers = screen.getAllByRole('columnheader').map((h) => h.textContent?.trim());
		expect(headers).toEqual(['학번', '이름', '이메일', '입장 상태', '관리']);
	});

	it('학생마다 학번, 이름, 이메일과 입장함/입장 전이 글로 보인다', () => {
		show();
		const rows = screen.getAllByRole('row').slice(1);
		expect(rows).toHaveLength(2);
		expect(within(rows[0]).getAllByRole('cell').slice(0, 4).map((c) => c.textContent?.trim())).toEqual([
			'20240001', '김철수', 'kim@x.kr', '입장함'
		]);
		expect(within(rows[1]).getAllByRole('cell').slice(0, 4).map((c) => c.textContent?.trim())).toEqual([
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

// --- 빼기와 로그인 끊기 (AC19, AC20) -------------------------------------------------------------------------------------

describe('빼기와 로그인 끊기 (AC19, AC20)', () => {
	const REMOVE_TEXT = '빼면 이 학생은 이 강좌에 입장할 수 없고 로그인 유지도 끝납니다. 다시 추가하면 이메일 인증을 거쳐 같은 닉네임으로 입장합니다.';
	const REVOKE_TEXT = '이 학생의 모든 기기가 이 강좌에서 로그아웃됩니다. 다시 들어오려면 이메일 인증이 필요하고, 닉네임은 같습니다.';
	const removeBtn = (name = '김철수 (20240001)') => screen.getByRole('button', { name: `빼기: ${name}` });
	const revokeBtn = (name = '김철수 (20240001)') => screen.getByRole('button', { name: `로그인 끊기: ${name}` });

	it('학생마다 "빼기"가 있고, 입장한 학생에게만 "로그인 끊기"가 있다', () => {
		show();
		expect(removeBtn().textContent?.trim()).toBe('빼기');
		expect(removeBtn('이영희 (20240002)')).toBeTruthy();
		expect(revokeBtn().textContent?.trim()).toBe('로그인 끊기');
		expect(screen.queryByRole('button', { name: '로그인 끊기: 이영희 (20240002)' })).toBeNull(); // 끊을 로그인이 없다
	});

	it('빼기를 누르면 바로 빼지 않고 확인 문구를 보인다', async () => {
		show();
		await fireEvent.click(removeBtn());
		const dialog = await screen.findByRole('alertdialog');
		expect(within(dialog).getByRole('heading', { name: '김철수 (20240001) 학생을 명단에서 뺄까요?' })).toBeTruthy();
		expect(within(dialog).getByText(REMOVE_TEXT)).toBeTruthy();
		expect(api.removeStudent).not.toHaveBeenCalled();
	});

	it('확인 창이 열리면 포커스는 되돌릴 수 없는 동작이 아니라 취소에 간다', async () => {
		show();
		await fireEvent.click(removeBtn());
		const dialog = await screen.findByRole('alertdialog');
		await waitFor(() => expect(document.activeElement).toBe(within(dialog).getByRole('button', { name: '취소' })));
	});

	it('취소하면 아무것도 하지 않고 포커스가 누른 버튼으로 돌아간다', async () => {
		show();
		const opener = removeBtn();
		await fireEvent.click(opener);
		await fireEvent.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: '취소' }));
		await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
		expect(api.removeStudent).not.toHaveBeenCalled();
		await waitFor(() => expect(document.activeElement).toBe(opener));
	});

	it('확인하면 빼고, 결과를 알리고, 명단을 다시 불러온다 (AC19)', async () => {
		api.removeStudent.mockResolvedValue({ id: 1, removed: true });
		const onChanged = show();
		await fireEvent.click(removeBtn());
		const dialog = await screen.findByRole('alertdialog');
		const confirm = within(dialog).getByRole('button', { name: '빼기' });
		expect(confirm.className).toContain('btn-destructive');
		await fireEvent.click(confirm);
		await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
		expect(api.removeStudent).toHaveBeenCalledWith(7, 1);
		expect(onChanged).toHaveBeenCalled();
		expect(screen.getByRole('status').textContent).toContain('김철수 학생을 명단에서 뺐습니다.');
		// 뺀 줄은 사라지므로 포커스는 표 영역으로 간다
		await waitFor(() => expect(document.activeElement).toBe(screen.getByRole('region', { name: '수강생 명단 표' })));
	});

	it('로그인 끊기를 누르면 확인 문구를 보이고, 확인하면 끊고 알린다 (AC20)', async () => {
		api.revokeStudentLogin.mockResolvedValue({ id: 1, revoked: true });
		const onChanged = show();
		const opener = revokeBtn();
		await fireEvent.click(opener);
		const dialog = await screen.findByRole('alertdialog');
		expect(within(dialog).getByRole('heading', { name: '김철수 (20240001) 학생의 로그인을 끊을까요?' })).toBeTruthy();
		expect(within(dialog).getByText(REVOKE_TEXT)).toBeTruthy();
		await fireEvent.click(within(dialog).getByRole('button', { name: '로그인 끊기' }));
		await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
		expect(api.revokeStudentLogin).toHaveBeenCalledWith(7, 1);
		expect(onChanged).toHaveBeenCalled();
		expect(screen.getByRole('status').textContent).toContain('김철수 학생의 로그인을 끊었습니다.');
		await waitFor(() => expect(document.activeElement).toBe(opener)); // 그 줄은 그대로 있다
	});

	it('처리하는 동안에는 두 버튼 모두 누를 수 없다', async () => {
		let finish: (v: unknown) => void = () => {};
		api.removeStudent.mockReturnValue(new Promise((r) => (finish = r)));
		show();
		await fireEvent.click(removeBtn());
		const dialog = await screen.findByRole('alertdialog');
		await fireEvent.click(within(dialog).getByRole('button', { name: '빼기' }));
		await waitFor(() => expect((within(dialog).getByRole('button', { name: '빼는 중…' }) as HTMLButtonElement).disabled).toBe(true));
		expect((within(dialog).getByRole('button', { name: '취소' }) as HTMLButtonElement).disabled).toBe(true);
		finish({ id: 1, removed: true });
		await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
	});

	it('이미 빠진 학생이면(다른 창에서 뺌) 이유를 보이고 명단을 다시 불러온다', async () => {
		api.removeStudent.mockRejectedValue(new ApiError(404, '명단에서 찾을 수 없는 학생입니다. 명단을 새로 불러와 확인해 주세요.', null));
		const onChanged = show();
		await fireEvent.click(removeBtn());
		const dialog = await screen.findByRole('alertdialog');
		await fireEvent.click(within(dialog).getByRole('button', { name: '빼기' }));
		expect((await within(dialog).findByRole('alert')).textContent).toContain('명단에서 찾을 수 없는 학생입니다.');
		expect(onChanged).toHaveBeenCalled();
	});

	it('입장 전이라 끊을 로그인이 없으면 서버의 이유를 보인다', async () => {
		api.revokeStudentLogin.mockRejectedValue(new ApiError(409, '아직 입장하지 않은 학생입니다. 끊을 로그인이 없습니다.', null));
		show();
		await fireEvent.click(revokeBtn());
		const dialog = await screen.findByRole('alertdialog');
		await fireEvent.click(within(dialog).getByRole('button', { name: '로그인 끊기' }));
		expect((await within(dialog).findByRole('alert')).textContent).toContain('아직 입장하지 않은 학생입니다.');
	});

	it('연결이 안 되면 창 안에 무엇을 하면 되는지 알려 준다', async () => {
		api.removeStudent.mockRejectedValue(new TypeError('Failed to fetch'));
		show();
		await fireEvent.click(removeBtn());
		const dialog = await screen.findByRole('alertdialog');
		await fireEvent.click(within(dialog).getByRole('button', { name: '빼기' }));
		const alert = await within(dialog).findByRole('alert');
		expect(alert.textContent).toContain('처리하지 못했습니다.');
		expect(alert.textContent).toContain('네트워크 연결을 확인하고 다시 시도해 주세요.');
	});

	it('표의 버튼도 44px 이상이다 (C14)', () => {
		show();
		for (const b of [removeBtn(), revokeBtn()]) {
			expect(b.className).toContain('btn');
			expect(b.className).not.toContain('btn-sm');
		}
	});
});
