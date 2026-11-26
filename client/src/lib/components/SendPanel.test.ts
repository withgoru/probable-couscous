// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({ sendItem: vi.fn(), retractItem: vi.fn() }));
vi.mock('#lib/api.js', async (original) => ({ ...(await original<object>()), sendItem: api.sendItem, retractItem: api.retractItem }));

import { ApiError } from '#lib/api.js';
import type { LiveItem } from '#lib/classLive.js';
import SendPanel from './SendPanel.svelte';

const item = (id: number, body: string | null, url: string | null, retracted_at: string | null = null): LiveItem => ({
	id,
	body,
	url,
	created_at: `2026-03-04T05:${String(id).padStart(2, '0')}:00+00:00`,
	retracted_at
});

function setup(items: LiveItem[] = [], offline = false) {
	const onChanged = vi.fn();
	const view = render(SendPanel, { classroomId: 7, sessionId: 3, items, offline, onChanged });
	return { onChanged, view };
}
const text = () => screen.getByLabelText('글') as HTMLTextAreaElement;
const link = () => screen.getByLabelText('링크(선택)') as HTMLInputElement;
const sendButton = () => screen.getByRole('button', { name: '학생에게 보내기' }) as HTMLButtonElement;

beforeEach(() => {
	api.sendItem.mockReset();
	api.retractItem.mockReset();
});
afterEach(cleanup);

describe('보내기 칸 (AC31, AC32)', () => {
	it('글 칸과 링크 칸이 있고 글은 2000자까지다', () => {
		setup();
		expect(screen.getByRole('heading', { name: '메시지·자료 보내기' })).toBeTruthy();
		expect(text().getAttribute('maxlength')).toBe('2000');
		expect(link().type).toBe('url');
	});

	it('글과 링크가 모두 비면 보내기가 흐려지고 이유가 보인다', async () => {
		setup();
		expect(sendButton().disabled).toBe(true);
		const reason = screen.getByText('글이나 링크를 입력해 주세요.');
		expect(sendButton().getAttribute('aria-describedby')).toContain(reason.id);
		await fireEvent.input(text(), { target: { value: '   ' } });
		expect(sendButton().disabled).toBe(true);
		await fireEvent.input(link(), { target: { value: 'https://example.com' } });
		expect(sendButton().disabled).toBe(false);
	});

	it('링크가 http:// 또는 https://로 시작하지 않으면 보내지 않고 이유를 링크 칸과 잇고 그 칸으로 초점을 옮긴다', async () => {
		setup();
		for (const bad of ['example.com', 'see https://x.kr', 'https://a b']) {
			await fireEvent.input(link(), { target: { value: bad } });
			await fireEvent.click(sendButton());
		}
		expect(api.sendItem).not.toHaveBeenCalled();
		const message = screen.getByText('링크는 http:// 또는 https://로 시작해야 합니다.');
		expect(link().getAttribute('aria-invalid')).toBe('true');
		expect(link().getAttribute('aria-describedby')).toContain(message.id);
		await waitFor(() => expect(document.activeElement).toBe(link()));
	});

	it('고쳐서 보내면 칸 오류가 사라진다', async () => {
		api.sendItem.mockResolvedValue(item(9, null, 'https://example.com'));
		setup();
		await fireEvent.input(link(), { target: { value: 'example.com' } });
		await fireEvent.click(sendButton());
		await fireEvent.input(link(), { target: { value: 'https://example.com' } });
		await fireEvent.click(sendButton());
		await waitFor(() => expect(api.sendItem).toHaveBeenCalled());
		await waitFor(() => expect(screen.queryByText('링크는 http:// 또는 https://로 시작해야 합니다.')).toBeNull());
		expect(link().getAttribute('aria-invalid')).toBeNull();
	});
});

describe('보내기 (AC31)', () => {
	it('보내면 칸을 비우고 목록을 다시 불러온다. 보낸 항목은 바로 목록 맨 위에 시각과 함께 보인다', async () => {
		api.sendItem.mockResolvedValue(item(9, '과제 안내', 'https://example.com/hw'));
		const { onChanged } = setup([item(1, '먼저 보낸 것', null)]);
		await fireEvent.input(text(), { target: { value: '과제 안내' } });
		await fireEvent.input(link(), { target: { value: ' https://example.com/hw ' } });
		await fireEvent.click(sendButton());
		await waitFor(() => expect(text().value).toBe(''));
		expect(link().value).toBe('');
		expect(onChanged).toHaveBeenCalled();
		expect(api.sendItem.mock.calls[0][0]).toBe(7);
		expect(api.sendItem.mock.calls[0][1]).toBe(3);
		expect(api.sendItem.mock.calls[0][2]).toMatchObject({ body: '과제 안내', url: 'https://example.com/hw' });
		const rows = within(screen.getByRole('list', { name: '보낸 항목' })).getAllByRole('listitem');
		expect(rows[0].textContent).toContain('과제 안내');
		expect(rows[0].textContent).toMatch(/\d{2}:\d{2}/);
		expect(rows[1].textContent).toContain('먼저 보낸 것');
	});

	it('글은 쓴 그대로 보낸다(줄바꿈과 들여쓰기)', async () => {
		api.sendItem.mockResolvedValue(item(9, 'a', null));
		setup();
		await fireEvent.input(text(), { target: { value: '  def f():\n      return 1' } });
		await fireEvent.click(sendButton());
		await waitFor(() => expect(api.sendItem).toHaveBeenCalled());
		expect(api.sendItem.mock.calls[0][2]).toMatchObject({ body: '  def f():\n      return 1', url: null });
	});

	it('실패하면 목록에 넣지 않고 글을 칸에 남긴 채 이유를 보인다', async () => {
		api.sendItem.mockRejectedValue(new TypeError('Failed to fetch'));
		setup();
		await fireEvent.input(text(), { target: { value: '남아야 할 글' } });
		await fireEvent.click(sendButton());
		expect((await screen.findByRole('alert')).textContent).toContain('보내지 못했습니다. 연결을 확인하고 다시 보내 주세요.');
		expect(text().value).toBe('남아야 할 글');
		expect(screen.queryByRole('list', { name: '보낸 항목' })).toBeNull();
	});

	it('실패한 뒤 다시 누르면 같은 client_key로 보내 두 번 저장되지 않는다', async () => {
		api.sendItem.mockRejectedValueOnce(new TypeError('x')).mockResolvedValueOnce(item(9, '한 번만', null));
		setup();
		await fireEvent.input(text(), { target: { value: '한 번만' } });
		await fireEvent.click(sendButton());
		await screen.findByRole('alert');
		await fireEvent.click(sendButton());
		await waitFor(() => expect(api.sendItem).toHaveBeenCalledTimes(2));
		const [first, second] = api.sendItem.mock.calls.map((c) => c[2].client_key);
		expect(first).toMatch(/^[A-Za-z0-9_-]{1,64}$/);
		expect(second).toBe(first);
	});

	it('보낸 뒤 새 글은 새 client_key로 보낸다', async () => {
		api.sendItem.mockResolvedValueOnce(item(9, '첫째', null)).mockResolvedValueOnce(item(10, '둘째', null));
		setup();
		await fireEvent.input(text(), { target: { value: '첫째' } });
		await fireEvent.click(sendButton());
		await waitFor(() => expect(text().value).toBe(''));
		await fireEvent.input(text(), { target: { value: '둘째' } });
		await fireEvent.click(sendButton());
		await waitFor(() => expect(api.sendItem).toHaveBeenCalledTimes(2));
		expect(api.sendItem.mock.calls[1][2].client_key).not.toBe(api.sendItem.mock.calls[0][2].client_key);
	});

	it('보내는 동안에는 다시 보내지 않는다', async () => {
		api.sendItem.mockReturnValue(new Promise(() => {}));
		setup();
		await fireEvent.input(text(), { target: { value: '글' } });
		await fireEvent.click(sendButton());
		await fireEvent.click(screen.getByRole('button', { name: '보내는 중…' }));
		expect(api.sendItem).toHaveBeenCalledTimes(1);
	});

	it('서버가 칸 오류로 거절하면 그 칸 옆에 안내를 보이고 그 칸으로 초점을 옮긴다', async () => {
		api.sendItem.mockRejectedValueOnce(new ApiError(422, '글은 2000자 이하로 입력해 주세요.', 'body'));
		setup();
		await fireEvent.input(text(), { target: { value: '글' } });
		await fireEvent.click(sendButton());
		const message = await screen.findByText('글은 2000자 이하로 입력해 주세요.');
		expect(text().getAttribute('aria-describedby')).toContain(message.id);
		await waitFor(() => expect(document.activeElement).toBe(text()));
		cleanup();
		api.sendItem.mockRejectedValueOnce(new ApiError(422, '링크는 2000자 이하로 입력해 주세요.', 'url'));
		setup();
		await fireEvent.input(link(), { target: { value: 'https://example.com/long' } });
		await fireEvent.click(sendButton());
		const linkMessage = await screen.findByText('링크는 2000자 이하로 입력해 주세요.');
		expect(link().getAttribute('aria-describedby')).toContain(linkMessage.id);
	});

	it('서버 오류(5xx)는 서버 문구 대신 다시 보내라는 안내를 보인다', async () => {
		api.sendItem.mockRejectedValue(new ApiError(500, '요청을 처리하지 못했습니다 (500)'));
		setup();
		await fireEvent.input(text(), { target: { value: '글' } });
		await fireEvent.click(sendButton());
		const alert = await screen.findByRole('alert');
		expect(alert.textContent).toContain('보내지 못했습니다. 연결을 확인하고 다시 보내 주세요.');
		expect(alert.textContent).not.toContain('(500)');
	});

	it('실패한 뒤 글을 고쳐서 보내면 새 client_key로 보낸다(고친 글이 예전 저장분으로 바뀌지 않게)', async () => {
		api.sendItem.mockRejectedValueOnce(new TypeError('x')).mockResolvedValueOnce(item(9, '과제 토요일', null));
		setup();
		await fireEvent.input(text(), { target: { value: '과제 금요일' } });
		await fireEvent.click(sendButton());
		await screen.findByRole('alert');
		await fireEvent.input(text(), { target: { value: '과제 토요일' } });
		await fireEvent.click(sendButton());
		await waitFor(() => expect(api.sendItem).toHaveBeenCalledTimes(2));
		expect(api.sendItem.mock.calls[1][2].client_key).not.toBe(api.sendItem.mock.calls[0][2].client_key);
	});

	it('client_key는 보안 연결이 아니어도 만들 수 있는 난수다', async () => {
		api.sendItem.mockResolvedValue(item(9, '글', null));
		const original = crypto.randomUUID;
		Object.defineProperty(crypto, 'randomUUID', { value: undefined, configurable: true });
		try {
			setup();
			await fireEvent.input(text(), { target: { value: '글' } });
			await fireEvent.click(sendButton());
			await waitFor(() => expect(api.sendItem).toHaveBeenCalled());
			expect(api.sendItem.mock.calls[0][2].client_key).toMatch(/^[0-9a-f]{32}$/);
		} finally {
			Object.defineProperty(crypto, 'randomUUID', { value: original, configurable: true });
		}
	});

	it('보내는 동안에는 칸을 고칠 수 없어서 쓰던 글이 지워지지 않는다', async () => {
		api.sendItem.mockReturnValue(new Promise(() => {}));
		setup();
		await fireEvent.input(text(), { target: { value: '글' } });
		await fireEvent.click(sendButton());
		expect(text().readOnly).toBe(true);
		expect(link().readOnly).toBe(true);
	});

	it('보내면 화면 낭독기에도 보냈다고 알린다', async () => {
		api.sendItem.mockResolvedValue(item(9, '글', null));
		setup();
		const status = document.querySelector('[data-send-status]') as HTMLElement;
		expect(status.getAttribute('role')).toBe('status');
		expect(status.textContent?.trim()).toBe('');
		await fireEvent.input(text(), { target: { value: '글' } });
		await fireEvent.click(sendButton());
		await waitFor(() => expect(status.textContent).toContain('학생에게 보냈습니다.'));
	});

	it('수업이 끝나 거절되면 서버 안내를 보인다', async () => {
		api.sendItem.mockRejectedValue(new ApiError(409, '진행 중인 수업에만 보낼 수 있습니다.', null));
		setup();
		await fireEvent.input(text(), { target: { value: '글' } });
		await fireEvent.click(sendButton());
		expect((await screen.findByRole('alert')).textContent).toContain('진행 중인 수업에만 보낼 수 있습니다.');
	});

	it('연결이 끊긴 동안에는 보내기가 흐려지고 끊김 안내와 이어진다(C12)', async () => {
		setup([], true);
		await fireEvent.input(text(), { target: { value: '글' } });
		expect(sendButton().getAttribute('aria-disabled')).toBe('true');
		expect(sendButton().getAttribute('aria-describedby')).toContain('offline-notice');
		await fireEvent.click(sendButton());
		expect(api.sendItem).not.toHaveBeenCalled();
		expect(text().disabled).toBe(false); // 끊긴 동안에도 미리 써 둘 수 있다
	});
});

describe('보낸 항목과 거두기 (AC35, AC36)', () => {
	it('보낸 항목이 최근 것부터 글과 링크로 보이고, 목록 아래에 안내가 있다', () => {
		setup([item(1, '첫째', null), item(2, null, 'https://example.com/b')]);
		const rows = within(screen.getByRole('list', { name: '보낸 항목' })).getAllByRole('listitem');
		expect(rows[0].textContent).toContain('https://example.com/b');
		expect(within(rows[0]).getByRole('link').getAttribute('href')).toBe('https://example.com/b');
		expect(within(rows[0]).getByRole('link').getAttribute('target')).toBe('_blank');
		expect(within(rows[0]).getByRole('link').getAttribute('rel')).toContain('noopener');
		expect(rows[1].textContent).toContain('첫째');
		expect(screen.getByText('보낸 항목은 수업이 끝난 뒤 공개할 목록으로 정리됩니다.')).toBeTruthy();
	});

	it('아직 보낸 항목이 없으면 그렇게 알린다', () => {
		setup();
		expect(screen.getByText('아직 보낸 항목이 없습니다.')).toBeTruthy();
		expect(screen.getByText('보낸 항목은 수업이 끝난 뒤 공개할 목록으로 정리됩니다.')).toBeTruthy();
	});

	it('거두기는 확인한 뒤에 하고 목록을 다시 불러온다', async () => {
		api.retractItem.mockResolvedValue(item(2, '잘못 보냄', null, 'z'));
		const { onChanged } = setup([item(2, '잘못 보냄', null)]);
		await fireEvent.click(screen.getByRole('button', { name: '거두기: 잘못 보냄' }));
		const dialog = await screen.findByRole('alertdialog');
		expect(dialog.textContent).toContain('이 항목을 거둘까요?');
		expect(dialog.textContent).toContain('학생 화면에서 바로 사라지고 되살릴 수 없습니다.');
		expect(api.retractItem).not.toHaveBeenCalled();
		await fireEvent.click(within(dialog).getByRole('button', { name: '거두기' }));
		await waitFor(() => expect(onChanged).toHaveBeenCalled());
		expect(api.retractItem).toHaveBeenCalledWith(7, 3, 2);
	});

	it('거둔 항목은 목록에 남아 그렇게 표시되고 다시 거둘 수 없다', () => {
		setup([item(2, '잘못 보냄', null, '2026-03-04T05:10:00+00:00')]);
		const row = within(screen.getByRole('list', { name: '보낸 항목' })).getByRole('listitem');
		expect(row.textContent).toContain('거둔 항목 · 학생에게 보이지 않습니다.');
		expect(row.textContent).toContain('잘못 보냄');
		expect(within(row).queryByRole('button')).toBeNull();
	});

	it('거두기에 실패하면 확인 창 안에 이유를 보인다', async () => {
		api.retractItem.mockRejectedValue(new TypeError('x'));
		setup([item(2, '잘못 보냄', null)]);
		await fireEvent.click(screen.getByRole('button', { name: '거두기: 잘못 보냄' }));
		const dialog = await screen.findByRole('alertdialog');
		await fireEvent.click(within(dialog).getByRole('button', { name: '거두기' }));
		expect((await within(dialog).findByRole('alert')).textContent).toContain('거두지 못했습니다.');
	});

	it('링크만 보낸 항목의 거두기 버튼 이름에는 링크가 들어간다', () => {
		setup([item(3, null, 'https://example.com/x')]);
		expect(screen.getByRole('button', { name: '거두기: https://example.com/x' })).toBeTruthy();
	});

	it('긴 글의 거두기 버튼 이름은 앞부분 40자로 줄인다', () => {
		setup([item(3, '가'.repeat(100), null)]);
		expect(screen.getByRole('button', { name: `거두기: ${'가'.repeat(40)}…` })).toBeTruthy();
	});

	it('방금 보낸 항목을 거두면 목록이 다시 오기 전에도 거둔 항목으로 보인다', async () => {
		api.sendItem.mockResolvedValue(item(9, '방금 보냄', null));
		api.retractItem.mockResolvedValue(item(9, '방금 보냄', null, '2026-03-04T05:20:00+00:00'));
		setup();
		await fireEvent.input(text(), { target: { value: '방금 보냄' } });
		await fireEvent.click(sendButton());
		await fireEvent.click(await screen.findByRole('button', { name: '거두기: 방금 보냄' }));
		await fireEvent.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: '거두기' }));
		const row = await waitFor(() => within(screen.getByRole('list', { name: '보낸 항목' })).getByRole('listitem'));
		await waitFor(() => expect(row.textContent).toContain('거둔 항목 · 학생에게 보이지 않습니다.'));
	});
});
