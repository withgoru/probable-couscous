// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({ importRoster: vi.fn() }));
vi.mock('#lib/api.js', async (original) => ({ ...(await original<object>()), importRoster: api.importRoster }));

import { ApiError } from '#lib/api.js';
import CsvImport from './CsvImport.svelte';

beforeEach(() => {
	api.importRoster.mockReset();
});
afterEach(cleanup);

const file = (name = 'roster.csv', size?: number) => {
	const f = new File(['학번,이름,이메일\n'], name, { type: 'text/csv' });
	if (size !== undefined) Object.defineProperty(f, 'size', { value: size });
	return f;
};
const picker = () => screen.getByLabelText('CSV 파일') as HTMLInputElement;
async function choose(f: File) {
	Object.defineProperty(picker(), 'files', { value: [f], configurable: true });
	await fireEvent.change(picker());
}
const upload = () => fireEvent.click(screen.getByRole('button', { name: '올리기' }));

describe('CSV 올리기 (AC13, AC14, AC18)', () => {
	it('안내: 첫 줄은 제목, 열 순서, UTF-8', () => {
		render(CsvImport, { classroomId: 7, onImported: vi.fn() });
		const help = screen.getByText(/첫 줄/).textContent!;
		expect(help).toContain('학번');
		expect(help).toContain('이름');
		expect(help).toContain('이메일');
		expect(help).toContain('UTF-8');
	});

	it('파일을 고르기 전에는 올리기를 누를 수 없고, 이유가 글로 있다', () => {
		render(CsvImport, { classroomId: 7, onImported: vi.fn() });
		expect((screen.getByRole('button', { name: '올리기' }) as HTMLButtonElement).disabled).toBe(true);
		expect(picker().getAttribute('aria-describedby')).toBeTruthy();
	});

	it('고른 파일을 이 강좌로 올리고 "N명 추가, M줄 건너뜀"을 보여 준다', async () => {
		api.importRoster.mockResolvedValue({ added: 38, skipped: 2, skipped_lines: [] });
		const onImported = vi.fn();
		render(CsvImport, { classroomId: 7, onImported });
		const f = file();
		await choose(f);
		await upload();
		const status = await screen.findByRole('status');
		expect(status.textContent).toContain('38명 추가, 2줄 건너뜀');
		expect(api.importRoster).toHaveBeenCalledWith(7, f);
		expect(onImported).toHaveBeenCalled();
	});

	it('건너뛴 줄은 줄 번호와 이유 목록으로 보인다', async () => {
		api.importRoster.mockResolvedValue({
			added: 1,
			skipped: 3,
			skipped_lines: [
				{ line: 3, reason: '이메일 형식 오류' },
				{ line: 5, reason: '이메일 중복' },
				{ line: 9, reason: '빈 칸' }
			]
		});
		render(CsvImport, { classroomId: 7, onImported: vi.fn() });
		await choose(file());
		await upload();
		await screen.findByRole('status');
		const items = within(screen.getByRole('list', { name: '건너뛴 줄' })).getAllByRole('listitem');
		expect(items.map((i) => i.textContent?.replace(/\s+/g, ' ').trim())).toEqual([
			'3줄: 이메일 형식 오류',
			'5줄: 이메일 중복',
			'9줄: 빈 칸'
		]);
	});

	it('건너뛴 줄이 없으면 목록을 보이지 않는다', async () => {
		api.importRoster.mockResolvedValue({ added: 2, skipped: 0, skipped_lines: [] });
		render(CsvImport, { classroomId: 7, onImported: vi.fn() });
		await choose(file());
		await upload();
		await screen.findByRole('status');
		expect(screen.queryByRole('list', { name: '건너뛴 줄' })).toBeNull();
	});

	it('200명 초과 오류는 서버의 안내 그대로 알림으로 보이고, 결과는 보이지 않는다', async () => {
		const msg = '명단은 200명까지 등록할 수 있습니다. 3명을 줄여 다시 올려 주세요.';
		api.importRoster.mockRejectedValue(new ApiError(422, msg, null));
		const onImported = vi.fn();
		render(CsvImport, { classroomId: 7, onImported });
		await choose(file());
		await upload();
		expect((await screen.findByRole('alert')).textContent).toContain(msg);
		expect(screen.queryByRole('status')).toBeNull();
		expect(onImported).not.toHaveBeenCalled();
	});

	it('UTF-8이 아닌 파일의 안내가 그대로 보인다', async () => {
		const msg = '파일을 읽을 수 없습니다. UTF-8 CSV로 저장해 다시 올려 주세요.';
		api.importRoster.mockRejectedValue(new ApiError(422, msg, null));
		render(CsvImport, { classroomId: 7, onImported: vi.fn() });
		await choose(file());
		await upload();
		expect((await screen.findByRole('alert')).textContent).toContain(msg);
	});

	it('1MB가 넘는 파일은 서버로 보내지 않고 바로 안내한다', async () => {
		render(CsvImport, { classroomId: 7, onImported: vi.fn() });
		await choose(file('big.csv', 1024 * 1024 + 1));
		await upload();
		expect((await screen.findByRole('alert')).textContent).toContain('1MB 이하로 나눠 올려 주세요');
		expect(api.importRoster).not.toHaveBeenCalled();
	});

	it('연결 문제는 해결 방법과 함께 알려 준다', async () => {
		api.importRoster.mockRejectedValue(new TypeError('network'));
		render(CsvImport, { classroomId: 7, onImported: vi.fn() });
		await choose(file());
		await upload();
		expect((await screen.findByRole('alert')).textContent).toMatch(/네트워크 연결을 확인하고 다시 시도/);
	});

	it('올리는 동안 버튼이 막혀 두 번 올리지 않는다', async () => {
		let release: (v: unknown) => void = () => {};
		api.importRoster.mockReturnValue(new Promise((r) => (release = r)));
		render(CsvImport, { classroomId: 7, onImported: vi.fn() });
		await choose(file());
		await upload();
		const button = screen.getByRole('button', { name: /올리는 중/ }) as HTMLButtonElement;
		expect(button.disabled).toBe(true);
		await fireEvent.click(button);
		expect(api.importRoster).toHaveBeenCalledTimes(1);
		release({ added: 0, skipped: 0, skipped_lines: [] });
		await waitFor(() => screen.getByRole('status'));
	});

	it('다음 올리기를 시작하면 이전 결과와 오류가 지워진다', async () => {
		api.importRoster.mockResolvedValueOnce({ added: 1, skipped: 0, skipped_lines: [] });
		api.importRoster.mockRejectedValueOnce(new ApiError(422, '파일이 비어 있습니다.', null));
		render(CsvImport, { classroomId: 7, onImported: vi.fn() });
		await choose(file());
		await upload();
		await screen.findByRole('status');
		await choose(file('again.csv'));
		expect(screen.queryByRole('status')).toBeNull(); // 새 파일을 고르면 이전 결과는 치운다
		await upload();
		await screen.findByRole('alert');
		expect(screen.queryByRole('status')).toBeNull();
	});

	it('올리는 동안 다시 제출해도 두 번 올리지 않는다', async () => {
		let release: (v: unknown) => void = () => {};
		api.importRoster.mockReturnValue(new Promise((r) => (release = r)));
		render(CsvImport, { classroomId: 7, onImported: vi.fn() });
		await choose(file());
		const form = picker().closest('form')!;
		await fireEvent.submit(form);
		await fireEvent.submit(form);
		expect(api.importRoster).toHaveBeenCalledTimes(1);
		release({ added: 0, skipped: 0, skipped_lines: [] });
	});

	it('파일을 고르지 않고 제출하면 아무것도 보내지 않는다', async () => {
		render(CsvImport, { classroomId: 7, onImported: vi.fn() });
		await fireEvent.submit(picker().closest('form')!);
		expect(api.importRoster).not.toHaveBeenCalled();
	});
});
