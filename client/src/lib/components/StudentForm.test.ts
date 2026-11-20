// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({ addStudent: vi.fn() }));
vi.mock('#lib/api.js', async (original) => ({ ...(await original<object>()), addStudent: api.addStudent }));

import { ApiError } from '#lib/api.js';
import StudentForm from './StudentForm.svelte';

const fieldError = (field: string | null, message: string) => new ApiError(422, message, field);
const box = (label: string) => screen.getByLabelText(label) as HTMLInputElement;

beforeEach(() => {
	api.addStudent.mockReset();
});
afterEach(cleanup);

async function fill(no = '20240001', name = '김철수', email = 'kim@x.kr') {
	await fireEvent.input(box('학번'), { target: { value: no } });
	await fireEvent.input(box('이름'), { target: { value: name } });
	await fireEvent.input(box('이메일'), { target: { value: email } });
}
const submit = () => fireEvent.click(screen.getByRole('button', { name: '학생 추가' }));

describe('학생 추가 폼 (AC15)', () => {
	it('학번, 이름, 이메일 칸에 보이는 이름표가 있다', () => {
		render(StudentForm, { classroomId: 7, onAdded: vi.fn() });
		for (const l of ['학번', '이름', '이메일']) expect(box(l)).toBeTruthy();
	});

	it('입력한 값을 이 강좌로 보내고 성공하면 알려 준다', async () => {
		const added = { id: 1, student_no: '20240001', name: '김철수', email: 'kim@x.kr' };
		api.addStudent.mockResolvedValue(added);
		const onAdded = vi.fn();
		render(StudentForm, { classroomId: 7, onAdded });
		await fill();
		await submit();
		await waitFor(() => expect(onAdded).toHaveBeenCalledWith(added));
		expect(api.addStudent).toHaveBeenCalledWith(7, { student_no: '20240001', name: '김철수', email: 'kim@x.kr' });
	});

	it('성공하면 칸을 비우고 학번 칸으로 포커스를 돌려 다음 학생을 바로 쓸 수 있다', async () => {
		api.addStudent.mockResolvedValue({ id: 1, student_no: '1', name: '김', email: 'a@x.kr' });
		render(StudentForm, { classroomId: 7, onAdded: vi.fn() });
		await fill();
		await submit();
		await waitFor(() => expect(box('학번').value).toBe(''));
		expect(box('이름').value).toBe('');
		expect(box('이메일').value).toBe('');
		expect(document.activeElement).toBe(box('학번'));
	});

	it('Enter로도 제출된다(키보드만으로)', async () => {
		api.addStudent.mockResolvedValue({ id: 1, student_no: '1', name: '김', email: 'a@x.kr' });
		render(StudentForm, { classroomId: 7, onAdded: vi.fn() });
		await fill();
		await fireEvent.submit(box('이메일').closest('form')!);
		await waitFor(() => expect(api.addStudent).toHaveBeenCalled());
	});

	it('이메일 오류는 이메일 칸 옆에 글로 보이고 칸과 연결된다', async () => {
		api.addStudent.mockRejectedValue(fieldError('email', '이메일 형식을 확인해 주세요.'));
		render(StudentForm, { classroomId: 7, onAdded: vi.fn() });
		await fill('1', '김', 'x');
		await submit();
		const msg = await screen.findByText('이메일 형식을 확인해 주세요.');
		const email = box('이메일');
		expect(email.getAttribute('aria-invalid')).toBe('true');
		expect(email.getAttribute('aria-describedby')?.split(' ')).toContain(msg.id);
		expect(email.parentElement!.contains(msg)).toBe(true); // 칸 바로 옆(같은 묶음 안)
		expect(box('학번').getAttribute('aria-invalid')).not.toBe('true');
		expect(box('이름').getAttribute('aria-invalid')).not.toBe('true');
	});

	it.each([
		['student_no', '이미 명단에 있는 학번입니다. 학번을 확인해 주세요.', '학번'],
		['name', '이름을 입력해 주세요.', '이름']
	])('%s 오류는 %s 칸 옆에 보인다', async (field, message, label) => {
		api.addStudent.mockRejectedValue(fieldError(field, message));
		render(StudentForm, { classroomId: 7, onAdded: vi.fn() });
		await fill();
		await submit();
		const msg = await screen.findByText(message);
		expect(box(label).getAttribute('aria-describedby')?.split(' ')).toContain(msg.id);
		expect(box(label).parentElement!.contains(msg)).toBe(true);
	});

	it('오류가 있어도 입력한 값은 지워지지 않는다', async () => {
		api.addStudent.mockRejectedValue(fieldError('email', '이메일 형식을 확인해 주세요.'));
		render(StudentForm, { classroomId: 7, onAdded: vi.fn() });
		await fill('1', '김', 'x');
		await submit();
		await screen.findByText('이메일 형식을 확인해 주세요.');
		expect([box('학번').value, box('이름').value, box('이메일').value]).toEqual(['1', '김', 'x']);
	});

	it('오류가 난 칸으로 포커스를 옮긴다', async () => {
		api.addStudent.mockRejectedValue(fieldError('email', '이메일 형식을 확인해 주세요.'));
		render(StudentForm, { classroomId: 7, onAdded: vi.fn() });
		await fill('1', '김', 'x');
		await submit();
		await screen.findByText('이메일 형식을 확인해 주세요.');
		expect(document.activeElement).toBe(box('이메일'));
	});

	it('칸이 없는 오류(200명 초과)는 폼의 알림으로 보인다', async () => {
		const msg = '명단은 200명까지 등록할 수 있습니다. 다른 학생을 빼고 다시 추가해 주세요.';
		api.addStudent.mockRejectedValue(fieldError(null, msg));
		render(StudentForm, { classroomId: 7, onAdded: vi.fn() });
		await fill();
		await submit();
		expect((await screen.findByRole('alert')).textContent).toContain(msg);
		for (const l of ['학번', '이름', '이메일']) expect(box(l).getAttribute('aria-invalid')).not.toBe('true');
	});

	it('연결 문제는 해결 방법과 함께 알려 준다', async () => {
		api.addStudent.mockRejectedValue(new TypeError('network'));
		render(StudentForm, { classroomId: 7, onAdded: vi.fn() });
		await fill();
		await submit();
		expect((await screen.findByRole('alert')).textContent).toMatch(/네트워크 연결을 확인하고 다시 시도/);
	});

	it('다시 제출하면 이전 오류가 지워진다', async () => {
		api.addStudent.mockRejectedValueOnce(fieldError('email', '이메일 형식을 확인해 주세요.'));
		api.addStudent.mockResolvedValueOnce({ id: 1, student_no: '1', name: '김', email: 'a@x.kr' });
		render(StudentForm, { classroomId: 7, onAdded: vi.fn() });
		await fill('1', '김', 'x');
		await submit();
		await screen.findByText('이메일 형식을 확인해 주세요.');
		await fireEvent.input(box('이메일'), { target: { value: 'a@x.kr' } });
		await submit();
		await waitFor(() => expect(screen.queryByText('이메일 형식을 확인해 주세요.')).toBeNull());
		expect(box('이메일').getAttribute('aria-invalid')).not.toBe('true');
	});

	it('보내는 동안에는 버튼이 막혀 두 번 보내지 않는다', async () => {
		let release: (v: unknown) => void = () => {};
		api.addStudent.mockReturnValue(new Promise((r) => (release = r)));
		render(StudentForm, { classroomId: 7, onAdded: vi.fn() });
		await fill();
		await submit();
		const button = screen.getByRole('button', { name: /추가하는 중/ }) as HTMLButtonElement;
		expect(button.disabled).toBe(true);
		await fireEvent.click(button);
		expect(api.addStudent).toHaveBeenCalledTimes(1);
		release({ id: 1, student_no: '1', name: '김', email: 'a@x.kr' });
	});

	it('보내는 동안 Enter로 다시 제출해도 두 번 보내지 않는다', async () => {
		let release: (v: unknown) => void = () => {};
		api.addStudent.mockReturnValue(new Promise((r) => (release = r)));
		render(StudentForm, { classroomId: 7, onAdded: vi.fn() });
		await fill();
		const form = box('이메일').closest('form')!;
		await fireEvent.submit(form);
		await fireEvent.submit(form);
		expect(api.addStudent).toHaveBeenCalledTimes(1);
		release({ id: 1, student_no: '1', name: '김', email: 'a@x.kr' });
	});
});
