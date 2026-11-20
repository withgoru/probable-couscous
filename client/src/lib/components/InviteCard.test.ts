// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({ regenerateInvite: vi.fn() }));
vi.mock('#lib/api.js', async (original) => ({ ...(await original<object>()), regenerateInvite: api.regenerateInvite }));

import { ApiError } from '#lib/api.js';
import InviteCard from './InviteCard.svelte';

const INVITE = { token: 'abc', url: 'http://localhost:8000/join/abc' };
const clipboard = { writeText: vi.fn() };

beforeEach(() => {
	api.regenerateInvite.mockReset();
	clipboard.writeText.mockReset();
	Object.defineProperty(navigator, 'clipboard', { value: clipboard, configurable: true });
});
afterEach(cleanup);

const show = (invite = INVITE, onChanged = vi.fn()) => {
	render(InviteCard, { classroomId: 7, invite, onChanged });
	return onChanged;
};
const link = () => screen.getByLabelText('초대 링크 주소') as HTMLInputElement;
const status = () => screen.getByRole('status');

describe('초대 링크 (AC21)', () => {
	it('제목과 이 강좌의 링크가 읽기 전용 칸에 보인다', () => {
		show();
		expect(screen.getByRole('heading', { level: 2, name: '초대 링크' })).toBeTruthy();
		expect(link().value).toBe(INVITE.url);
		expect(link().readOnly).toBe(true);
	});

	it('링크를 열어도 입장되지 않고 이메일 인증이 필요하다고 알려 준다(AC23)', () => {
		show();
		expect(screen.getByText(/링크를 열어도 입장되지 않습니다/)).toBeTruthy();
		expect(screen.getByText(/수강생 명단에 있는 이메일/)).toBeTruthy();
	});

	it('복사를 누르면 링크를 클립보드에 넣고 "복사했습니다"가 보인다', async () => {
		clipboard.writeText.mockResolvedValue(undefined);
		show();
		await fireEvent.click(screen.getByRole('button', { name: '복사' }));
		await waitFor(() => expect(status().textContent).toContain('복사했습니다'));
		expect(clipboard.writeText).toHaveBeenCalledWith(INVITE.url);
	});

	it('복사하기 전에는 알림 문구가 비어 있다', () => {
		show();
		expect(status().textContent?.trim()).toBe('');
	});

	it('클립보드를 쓸 수 없으면 복사했다고 거짓말하지 않고 직접 복사하도록 안내하며 링크를 선택해 둔다', async () => {
		clipboard.writeText.mockRejectedValue(new Error('denied'));
		show();
		await fireEvent.click(screen.getByRole('button', { name: '복사' }));
		const alert = await screen.findByRole('alert');
		expect(alert.textContent).toContain('복사하지 못했습니다');
		expect(alert.textContent).toContain('직접 복사');
		expect(status().textContent).not.toContain('복사했습니다');
		expect(link().selectionStart).toBe(0);
		expect(link().selectionEnd).toBe(INVITE.url.length);
	});

	it('클립보드 기능이 아예 없는 브라우저도 같은 안내를 한다', async () => {
		Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true });
		show();
		await fireEvent.click(screen.getByRole('button', { name: '복사' }));
		expect((await screen.findByRole('alert')).textContent).toContain('복사하지 못했습니다');
	});

	it('복사 성공 뒤 다시 실패하면 이전의 "복사했습니다"는 사라진다', async () => {
		clipboard.writeText.mockResolvedValueOnce(undefined);
		clipboard.writeText.mockRejectedValueOnce(new Error('denied'));
		show();
		await fireEvent.click(screen.getByRole('button', { name: '복사' }));
		await waitFor(() => expect(status().textContent).toContain('복사했습니다'));
		await fireEvent.click(screen.getByRole('button', { name: '복사' }));
		await screen.findByRole('alert');
		expect(status().textContent).not.toContain('복사했습니다');
	});
});

describe('링크 다시 만들기 (AC22)', () => {
	it('이전 링크가 바로 쓸 수 없게 된다는 경고가 누르기 전에 보인다', () => {
		show();
		expect(screen.getByText(/이전 링크는 바로 사용할 수 없게 됩니다/)).toBeTruthy();
	});

	it('누르면 새 링크를 만들고 명단을 다시 불러오듯 화면을 새로 고친다', async () => {
		api.regenerateInvite.mockResolvedValue({ token: 'new', url: 'http://localhost:8000/join/new' });
		const onChanged = show();
		await fireEvent.click(screen.getByRole('button', { name: '링크 다시 만들기' }));
		await waitFor(() => expect(onChanged).toHaveBeenCalled());
		expect(api.regenerateInvite).toHaveBeenCalledWith(7);
		expect(status().textContent).toContain('새 링크를 만들었습니다');
		expect(status().textContent).toContain('이전 링크는 더 이상 사용할 수 없습니다');
	});

	it('실패하면 이유와 해결 방법을 알림으로 보이고 새로 고치지 않는다', async () => {
		api.regenerateInvite.mockRejectedValue(new ApiError(503, '링크를 만들지 못했습니다. 잠시 뒤 다시 시도해 주세요.'));
		const onChanged = show();
		await fireEvent.click(screen.getByRole('button', { name: '링크 다시 만들기' }));
		expect((await screen.findByRole('alert')).textContent).toContain('잠시 뒤 다시 시도해 주세요');
		expect(onChanged).not.toHaveBeenCalled();
		expect(status().textContent).not.toContain('새 링크를 만들었습니다');
	});

	it('연결 문제는 해결 방법과 함께 알려 준다', async () => {
		api.regenerateInvite.mockRejectedValue(new TypeError('network'));
		show();
		await fireEvent.click(screen.getByRole('button', { name: '링크 다시 만들기' }));
		expect((await screen.findByRole('alert')).textContent).toMatch(/네트워크 연결을 확인하고 다시 시도/);
	});

	it('만드는 동안 버튼이 막혀 두 번 만들지 않는다', async () => {
		let release: (v: unknown) => void = () => {};
		api.regenerateInvite.mockReturnValue(new Promise((r) => (release = r)));
		show();
		await fireEvent.click(screen.getByRole('button', { name: '링크 다시 만들기' }));
		const button = screen.getByRole('button', { name: /만드는 중/ }) as HTMLButtonElement;
		expect(button.disabled).toBe(true);
		await fireEvent.click(button);
		expect(api.regenerateInvite).toHaveBeenCalledTimes(1);
		release({ token: 'n', url: 'http://localhost:8000/join/n' });
		await waitFor(() => expect(status().textContent).toContain('새 링크'));
	});

	it('새 링크로 바뀌면 칸에 새 링크가 보이고 이전의 복사 알림은 지워진다', async () => {
		clipboard.writeText.mockResolvedValue(undefined);
		api.regenerateInvite.mockResolvedValue({ token: 'new', url: 'http://localhost:8000/join/new' });
		const { rerender } = render(InviteCard, { classroomId: 7, invite: INVITE, onChanged: vi.fn() });
		await fireEvent.click(screen.getByRole('button', { name: '복사' }));
		await waitFor(() => expect(status().textContent).toContain('복사했습니다'));
		await fireEvent.click(screen.getByRole('button', { name: '링크 다시 만들기' }));
		await waitFor(() => expect(status().textContent).toContain('새 링크를 만들었습니다'));
		expect(status().textContent).not.toContain('복사했습니다');
		await rerender({ classroomId: 7, invite: { token: 'new', url: 'http://localhost:8000/join/new' }, onChanged: vi.fn() });
		expect(link().value).toBe('http://localhost:8000/join/new');
	});
});
