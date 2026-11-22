// @vitest-environment jsdom
import { cleanup, render, screen, within } from '@testing-library/svelte';
import { afterEach, describe, expect, it } from 'vitest';
import PendingAuthSection from './PendingAuthSection.svelte';

const NOW = new Date('2026-03-02T05:06:00+00:00');
const waiting = { id: 11, student_no: '1', name: '김철수', notified_at: '2026-03-02T05:05:00+00:00', status: 'waiting' as const, code: '349498', expires_at: '2026-03-02T05:14:00+00:00' };
const used = { id: 12, student_no: '2', name: '이영희', notified_at: '2026-03-02T05:01:00+00:00', status: 'used' as const, used_at: '2026-03-02T05:03:00+00:00' };
const expired = { id: 13, student_no: '3', name: '박민수', notified_at: '2026-03-02T04:40:00+00:00', status: 'expired' as const };

afterEach(cleanup);

const rowOf = (name: string) => screen.getByRole('cell', { name }).closest('tr') as HTMLElement;
const cells = (name: string) => within(rowOf(name)).getAllByRole('cell').map((c) => c.textContent?.replace(/\s+/g, ' ').trim());

describe('대기 중인 인증 (AC45, AC47)', () => {
	it('제목과 코드를 볼 때마다 기록된다는 안내가 있다 (C6)', () => {
		render(PendingAuthSection, { items: [], now: NOW });
		expect(screen.getByRole('region', { name: /대기 중인 인증/ })).toBeTruthy();
		expect(document.body.textContent).toContain('코드를 볼 때마다 기록됩니다');
	});

	it('표의 열은 학번, 이름, 요청 시각, 코드다', () => {
		render(PendingAuthSection, { items: [waiting], now: NOW });
		expect(screen.getAllByRole('columnheader').map((h) => h.textContent?.trim())).toEqual(['학번', '이름', '요청 시각', '코드']);
	});

	it('기다리는 학생은 학번, 이름, 요청 시각, 6자리 코드와 만료 시각이 보인다', () => {
		render(PendingAuthSection, { items: [waiting], now: NOW });
		const [no, name, at, code] = cells('김철수');
		expect([no, name]).toEqual(['1', '김철수']);
		expect(within(rowOf('김철수')).getAllByRole('cell')[2].querySelector('time')?.getAttribute('datetime')).toBe(waiting.notified_at);
		expect(at).toMatch(/\d{2}:\d{2}/);
		expect(code).toContain('349498');
		expect(code).toMatch(/\d{2}:\d{2}까지/);
	});

	it('사용된 코드는 코드 없이 "사용됨 (시각)"으로 보인다 (AC47)', () => {
		render(PendingAuthSection, { items: [used], now: NOW });
		const code = cells('이영희')[3];
		expect(code).toMatch(/^사용됨 \(\d{2}:\d{2}\)$/);
	});

	it('만료된 코드는 "만료됨"으로 보인다', () => {
		render(PendingAuthSection, { items: [expired], now: NOW });
		expect(cells('박민수')[3]).toBe('만료됨');
	});

	it('기다리던 코드도 만료 시각이 지나면 서버에 묻지 않고 "만료됨"으로 바뀐다', async () => {
		const { rerender } = render(PendingAuthSection, { items: [waiting], now: NOW });
		expect(cells('김철수')[3]).toContain('349498');
		await rerender({ items: [waiting], now: new Date('2026-03-02T05:14:00+00:00') });
		expect(cells('김철수')[3]).toBe('만료됨');
		expect(document.body.textContent).not.toContain('349498');
	});

	it('상태는 색만이 아니라 글로 전달한다 (C14)', () => {
		render(PendingAuthSection, { items: [used, expired], now: NOW });
		expect(screen.getByText(/사용됨/)).toBeTruthy();
		expect(screen.getByText('만료됨')).toBeTruthy();
	});

	it('없으면 그렇다고 알려 준다', () => {
		render(PendingAuthSection, { items: [], now: NOW });
		expect(screen.getByText(/대기 중인 인증이 없습니다/)).toBeTruthy();
		expect(screen.queryByRole('table')).toBeNull();
	});

	it('불러오기 전에는 불러오는 중이라고 보인다', () => {
		render(PendingAuthSection, { items: null, now: NOW });
		expect(screen.getByText('불러오는 중…')).toBeTruthy();
	});

	it('닉네임과 이메일은 어디에도 없다 (C9)', () => {
		render(PendingAuthSection, { items: [waiting, used, expired], now: NOW });
		expect(document.body.textContent).not.toMatch(/닉네임|@/);
	});
});
