import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const read = (p: string) => readFileSync(resolve(__dirname, p), 'utf8');

describe('디자인 토큰 연결', () => {
	it('client/src/theme.css는 docs/design/theme.css와 같다 (원본은 docs)', () => {
		expect(read('./theme.css')).toBe(read('../../docs/design/theme.css'));
	});

	it('app.css가 theme.css를 불러온다', () => {
		expect(read('./app.css')).toMatch(/@import\s+['"]\.\/theme\.css['"]/);
	});

	it('루트 레이아웃이 app.css를 불러온다', () => {
		expect(read('./routes/+layout.svelte')).toMatch(/import\s+['"]\.\.\/app\.css['"]/);
	});

	it('SPA 모드다: 서버 렌더링을 끈다', () => {
		expect(read('./routes/+layout.ts')).toMatch(/export const ssr = false/);
	});

	it('포커스 링 토큰은 불투명 primary와 같은 값이다 (C14)', () => {
		const css = read('./theme.css');
		const primary = css.match(/--primary:\s*(#[0-9a-f]{6})/i)?.[1];
		const ring = css.match(/--ring:\s*(#[0-9a-f]{6})/i)?.[1];
		expect(primary).toBeDefined();
		expect(ring).toBe(primary);
	});
});
