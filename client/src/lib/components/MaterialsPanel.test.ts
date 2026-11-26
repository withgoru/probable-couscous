// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { LiveItem } from '#lib/classLive.js';
import MaterialsPanel from './MaterialsPanel.svelte';

// 자료 구역이 화면에 보이는지는 IntersectionObserver로 안다. 테스트가 보임/안 보임을 일으킨다
class FakeObserver {
	static all: FakeObserver[] = [];
	constructor(public callback: (entries: { isIntersecting: boolean }[]) => void) {
		FakeObserver.all.push(this);
	}
	observe() {}
	disconnect() {}
	unobserve() {}
}
const visible = async (yes: boolean) => {
	await act(() => FakeObserver.all.at(-1)?.callback([{ isIntersecting: yes }]));
};

const item = (id: number, body: string | null, url: string | null = null): LiveItem => ({
	id,
	body,
	url,
	created_at: `2026-03-04T05:${String(id).padStart(2, '0')}:00+00:00`
});
const ARRIVED = '교수님이 자료를 보냈습니다.';

function setup(items: LiveItem[] = [item(1, '첫 자료')]) {
	const view = render(MaterialsPanel, { items });
	return { rerender: (next: LiveItem[]) => view.rerender({ items: next }) };
}
const rows = () => within(screen.getByRole('list', { name: '자료' })).getAllByRole('listitem');

beforeEach(() => {
	FakeObserver.all = [];
	vi.stubGlobal('IntersectionObserver', FakeObserver);
	vi.useFakeTimers();
});
afterEach(() => {
	cleanup();
	vi.useRealTimers();
	vi.unstubAllGlobals();
});

describe('새 자료 (AC33)', () => {
	it('새 항목은 목록 맨 위에 나타난다', async () => {
		const { rerender } = setup([item(1, '첫 자료')]);
		await rerender([item(1, '첫 자료'), item(2, '둘째 자료')]);
		expect(rows()[0].textContent).toContain('둘째 자료');
		expect(rows()[1].textContent).toContain('첫 자료');
	});

	it('새 항목이 오면 "교수님이 자료를 보냈습니다."가 몇 초 보이고 화면 낭독기에도 읽힌다', async () => {
		const { rerender } = setup();
		const region = document.querySelector('[data-arrival]') as HTMLElement;
		expect(region.getAttribute('role')).toBe('status'); // 늘 있는 알림 자리
		expect(region.getAttribute('aria-live')).toBe('polite');
		expect(region.textContent?.trim()).toBe('');
		await rerender([item(1, '첫 자료'), item(2, '둘째')]);
		expect(region.textContent).toContain(ARRIVED);
		await act(() => vi.advanceTimersByTime(4_000));
		expect(region.textContent?.trim()).toBe('');
	});

	it('처음 열 때 이미 있던 항목으로는 알리지 않는다', () => {
		setup([item(1, '첫'), item(2, '둘')]);
		expect(screen.queryByText(ARRIVED)).toBeNull();
	});

	it('끊긴 동안 온 항목도 다시 붙어 나타나면 알린다', async () => {
		const { rerender } = setup([item(1, '첫')]);
		await rerender([item(1, '첫'), item(2, '끊긴 동안 1'), item(3, '끊긴 동안 2')]);
		expect(screen.getByText(ARRIVED)).toBeTruthy();
	});

	it('읽지 않은 수가 보이고, 자료가 화면에 보이면 읽은 것이 된다', async () => {
		const { rerender } = setup([item(1, '첫')]);
		await visible(false);
		await rerender([item(1, '첫'), item(2, '둘')]);
		await rerender([item(1, '첫'), item(2, '둘'), item(3, '셋')]);
		// 수는 제목 안에 있어서 제목으로 옮겨 다닐 때 함께 읽힌다
		expect(screen.getByRole('heading', { level: 2, name: /자료.*새 자료 2/ })).toBeTruthy();
		await visible(true);
		expect(screen.queryByText(/새 자료 \d/)).toBeNull();
	});

	it('자료가 보이는 동안 온 항목은 읽지 않은 수에 넣지 않는다', async () => {
		const { rerender } = setup([item(1, '첫')]);
		await visible(true);
		await rerender([item(1, '첫'), item(2, '둘')]);
		expect(screen.queryByText(/새 자료 \d/)).toBeNull();
		expect(screen.getByText(ARRIVED)).toBeTruthy(); // 알림은 그래도 한다
	});

	it('거둔 항목은 목록에서 사라지고 읽지 않은 수에서도 빠진다 (AC35)', async () => {
		const { rerender } = setup([item(1, '첫')]);
		await visible(false);
		await rerender([item(1, '첫'), item(2, '잘못 보냄')]);
		expect(screen.getByText('새 자료 1')).toBeTruthy();
		await rerender([item(1, '첫')]);
		expect(screen.queryByText('잘못 보냄')).toBeNull();
		expect(screen.queryByText(/새 자료 \d/)).toBeNull();
	});

	it('다른 앱으로 간 동안 온 항목은 자료가 화면에 걸려 있어도 읽지 않은 것이다', async () => {
		let state: DocumentVisibilityState = 'visible';
		vi.spyOn(document, 'visibilityState', 'get').mockImplementation(() => state);
		const { rerender } = setup([item(1, '첫')]);
		await visible(true);
		state = 'hidden';
		document.dispatchEvent(new Event('visibilitychange'));
		await rerender([item(1, '첫'), item(2, '둘')]);
		expect(screen.getByText('새 자료 1')).toBeTruthy();
		state = 'visible';
		await act(() => document.dispatchEvent(new Event('visibilitychange'))); // 돌아와서 자료가 보이면 읽었다
		expect(screen.queryByText(/새 자료 \d/)).toBeNull();
	});

	it('화면에 보이는지 알 수 없는 브라우저에서는 수가 쌓여 남지 않는다', async () => {
		vi.stubGlobal('IntersectionObserver', undefined);
		const { rerender } = setup([item(1, '첫')]);
		await rerender([item(1, '첫'), item(2, '둘')]);
		expect(screen.queryByText(/새 자료 \d/)).toBeNull();
		expect(screen.getByText(ARRIVED)).toBeTruthy();
	});

	it('자료가 없으면 그렇게 알린다', () => {
		setup([]);
		expect(screen.getByText('아직 받은 자료가 없습니다.')).toBeTruthy();
	});
});

describe('복사와 링크 (AC34)', () => {
	it('글 항목에는 복사 버튼이 있고, 누르면 글 전체가 복사되며 "복사했습니다."가 보인다', async () => {
		const writeText = vi.fn(() => Promise.resolve());
		vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } });
		setup([item(1, '  def f():\n      return 1')]);
		await fireEvent.click(screen.getByRole('button', { name: '복사: def f(): return 1' }));
		expect(writeText).toHaveBeenCalledWith('  def f():\n      return 1');
		const list = screen.getByRole('list', { name: '자료' });
		expect(within(list).getByText('복사했습니다.')).toBeTruthy();
		expect((document.querySelector('[data-copy-status]') as HTMLElement).textContent).toContain('복사했습니다.'); // 읽힌다
		await act(() => vi.advanceTimersByTime(3_000));
		expect(screen.queryAllByText('복사했습니다.')).toHaveLength(0);
	});

	it('복사하지 못하면 거짓으로 알리지 않고 직접 복사하는 방법을 알리며, 그 안내는 사라지지 않는다', async () => {
		vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText: vi.fn(() => Promise.reject(new Error('denied'))) } });
		setup([item(1, '글')]);
		await fireEvent.click(screen.getByRole('button', { name: '복사: 글' }));
		await act(() => Promise.resolve());
		expect(screen.queryAllByText('복사했습니다.')).toHaveLength(0);
		const FAIL = '복사하지 못했습니다. 글을 선택해 직접 복사해 주세요.';
		const list = screen.getByRole('list', { name: '자료' });
		expect(within(list).getByText(FAIL)).toBeTruthy();
		await act(() => vi.advanceTimersByTime(10_000));
		expect(within(list).getByText(FAIL)).toBeTruthy();
	});

	it('복사 결과는 그 항목 안에 보이고, 알림 자리는 목록 전체에 하나다', async () => {
		vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText: vi.fn(() => Promise.resolve()) } });
		setup([item(1, '첫'), item(2, '둘')]);
		const list = screen.getByRole('list', { name: '자료' });
		expect(list.querySelectorAll('[role="status"]')).toHaveLength(0);
		await fireEvent.click(screen.getByRole('button', { name: '복사: 첫' }));
		await act(() => Promise.resolve());
		const row = within(list).getAllByRole('listitem')[1];
		expect(row.textContent).toContain('복사했습니다.');
		expect((document.querySelector('[data-copy-status]') as HTMLElement).textContent).toContain('복사했습니다.');
	});

	it('링크만 있는 항목에는 복사 버튼이 없고, 링크는 새 탭으로 열린다고 알린다', () => {
		setup([item(1, null, 'https://example.com/a')]);
		expect(screen.queryByRole('button', { name: /^복사/ })).toBeNull();
		const link = screen.getByRole('link', { name: /https:\/\/example\.com\/a/ });
		expect(link.getAttribute('target')).toBe('_blank');
		expect(link.getAttribute('rel')).toContain('noopener');
		expect(link.textContent).toContain('새 탭');
	});

	it('긴 글의 복사 버튼 이름은 앞부분만 쓴다', () => {
		setup([item(1, '가'.repeat(100))]);
		expect(screen.getByRole('button', { name: `복사: ${'가'.repeat(30)}…` })).toBeTruthy();
	});
});
