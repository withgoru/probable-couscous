// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({ enterClassroom: vi.fn() }));
vi.mock('#lib/api.js', async (original) => ({ ...(await original<object>()), enterClassroom: api.enterClassroom }));

import { ApiError } from '#lib/api.js';
import NoticeStep from './NoticeStep.svelte';

// AC27의 안내 3줄(문장 그대로, 존댓말 끝맺음)
const LINES = [
	'다른 학생에게는 닉네임으로만 보입니다.',
	'교수님은 심각한 사안에 한해 사유를 기록하고 작성자를 확인할 수 있습니다.',
	'채팅 내용은 참여 점수에 반영되지 않고 공개되지 않습니다.'
];
const props = () => ({
	token: 'tok',
	classroom: '웹 프로그래밍 · 월수반',
	nickname: '느긋한 고래',
	onEntered: vi.fn(),
	onClosed: vi.fn(),
	onNeedLogin: vi.fn()
});
const enter = () => fireEvent.click(screen.getByRole('button', { name: '확인하고 입장' }));

beforeEach(() => {
	api.enterClassroom.mockReset(); // 중괄호가 필요하다: 함수를 돌려주면 vitest가 정리 함수로 여겨 테스트 뒤에 부른다
});
afterEach(cleanup);

describe('채팅 이용 안내 (AC27, AC29)', () => {
	it('강좌 이름과 자동으로 정해진 닉네임 카드가 보인다', () => {
		render(NoticeStep, props());
		expect(document.body.textContent).toContain('웹 프로그래밍 · 월수반');
		expect(screen.getByText('이 수업에서 쓰는 닉네임')).toBeTruthy();
		expect(screen.getByText('느긋한 고래')).toBeTruthy();
	});

	it("'채팅 이용 안내'에 안내 3줄이 AC27 문장 그대로 있다", () => {
		render(NoticeStep, props());
		const section = screen.getByRole('region', { name: '채팅 이용 안내' });
		const items = Array.from(section.querySelectorAll('li')).map((li) => li.textContent?.trim());
		expect(items).toEqual(LINES);
	});

	it("'익명'이라는 말은 어디에도 없다", () => {
		render(NoticeStep, props());
		expect(document.body.textContent).not.toContain('익명');
	});

	it('닉네임을 바꾸는 칸이나 버튼이 없다 (AC29)', () => {
		render(NoticeStep, props());
		expect(screen.queryByRole('textbox')).toBeNull();
		expect(screen.getAllByRole('button').map((b) => b.textContent?.trim())).toEqual(['확인하고 입장']);
	});

	it('제목이 있어 화면이 바뀌면 읽어 주는 도구가 알 수 있다', () => {
		render(NoticeStep, props());
		expect(screen.getByRole('heading', { level: 1 })).toBeTruthy();
	});
});

describe('확인하고 입장 (AC28)', () => {
	it('누르면 입장을 확정하고 강좌 이름과 닉네임을 넘겨준다', async () => {
		api.enterClassroom.mockResolvedValue({ next: 'entered', nickname: '느긋한 고래', classroom: '웹 프로그래밍' });
		const p = props();
		render(NoticeStep, p);
		await enter();
		await waitFor(() => expect(p.onEntered).toHaveBeenCalledWith({ nickname: '느긋한 고래', classroom: '웹 프로그래밍' }));
		expect(api.enterClassroom).toHaveBeenCalledWith('tok');
	});

	it('입장하는 동안에는 다시 누를 수 없다', async () => {
		let finish: (v: unknown) => void = () => {};
		api.enterClassroom.mockReturnValue(new Promise((r) => (finish = r)));
		render(NoticeStep, props());
		await enter();
		const busy = screen.getByRole('button', { name: '입장하는 중…' }) as HTMLButtonElement;
		expect(busy.disabled).toBe(true);
		await fireEvent.click(busy);
		expect(api.enterClassroom).toHaveBeenCalledTimes(1);
		finish({ next: 'entered', nickname: 'n', classroom: 'c' });
	});

	it('인증이 끝났으면(로그인이 끊김·만료) 이메일 인증으로 돌려보낸다', async () => {
		const message = '입장 인증이 끝나지 않았습니다. 이메일과 코드로 먼저 인증해 주세요.';
		api.enterClassroom.mockRejectedValue(new ApiError(401, message));
		const p = props();
		render(NoticeStep, p);
		await enter();
		await waitFor(() => expect(p.onNeedLogin).toHaveBeenCalledWith(message));
	});

	it.each([
		[403, '이 강좌는 보관되었습니다. 교수님께 문의해 주세요.'],
		[403, '이 강좌의 수강생 명단에 없습니다. 교수님께 문의해 주세요.'],
		[404, '이 링크는 더 이상 사용할 수 없습니다. 교수님께 새 링크를 받으세요.']
	])('입장할 수 없게 됐으면(%i) 서버의 안내로 닫힌 화면을 보인다', async (status, message) => {
		api.enterClassroom.mockRejectedValue(new ApiError(status, message));
		const p = props();
		render(NoticeStep, p);
		await enter();
		await waitFor(() => expect(p.onClosed).toHaveBeenCalledWith(message));
	});

	it('연결이 안 되면 무엇을 하면 되는지 알려 주고 다시 누를 수 있다', async () => {
		api.enterClassroom.mockRejectedValue(new TypeError('Failed to fetch'));
		render(NoticeStep, props());
		await enter();
		const alert = await screen.findByRole('alert');
		expect(alert.textContent).toContain('입장하지 못했습니다.');
		expect(alert.textContent).toContain('네트워크 연결을 확인하고 다시 시도해 주세요.');
		expect((screen.getByRole('button', { name: '확인하고 입장' }) as HTMLButtonElement).disabled).toBe(false);
	});

	it('버튼은 큰 크기로 화면 폭을 채운다 (C14)', () => {
		render(NoticeStep, props());
		const b = screen.getByRole('button', { name: '확인하고 입장' });
		expect(b.className).toContain('btn-lg');
		expect(b.className).toContain('w-full');
	});
});
