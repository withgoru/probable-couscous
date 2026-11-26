import AxeBuilder from '@axe-core/playwright';
import { expect, type Locator, type Page } from '@playwright/test';

/** 전환 효과를 끈다. 포커스 링(box-shadow)이 전환 중일 때 읽으면 아직 그려지지 않은 값이 나온다. */
export async function noTransitions(page: Page) {
	await page.addStyleTag({ content: '*,*::before,*::after{transition:none!important;animation:none!important}' });
}

export type FocusIssue = { element: string; problem: string };

/**
 * 지금 키보드 포커스를 받은 요소를 점검한다(AC50, C14).
 * - 포커스 링: 불투명 2px 이상(링 색 #0a2463의 box-shadow 또는 outline)
 * - 크기: 버튼·입력·버튼 모양 링크는 높이 44px 이상. 체크 상자와 스위치는 눌리는 범위(label)가 44px 이상
 */
export async function checkFocused(page: Page): Promise<FocusIssue[]> {
	return page.evaluate(() => {
		const el = document.activeElement as HTMLElement | null;
		if (!el || el === document.body) return [];
		const issues: { element: string; problem: string }[] = [];
		const name = (el.getAttribute('aria-label') || el.textContent || (el as HTMLInputElement).placeholder || el.id || '')
			.replace(/\s+/g, ' ')
			.trim()
			.slice(0, 40);
		const element = `<${el.tagName.toLowerCase()}${el.getAttribute('type') ? ` type=${el.getAttribute('type')}` : ''}> ${name}`;
		const style = getComputedStyle(el);

		// 링: box-shadow 중 링 색이고 퍼짐이 2px 이상인 것, 또는 2px 이상 실선 outline
		const RING = 'rgb(10, 36, 99)';
		const shadows = style.boxShadow === 'none' ? [] : style.boxShadow.split(/,(?![^(]*\))/);
		const ringShadow = shadows.some((s) => {
			const color = s.match(/rgba?\([^)]*\)/)?.[0] ?? '';
			const lengths = s.replace(/rgba?\([^)]*\)/, '').trim().split(/\s+/).map((v) => parseFloat(v));
			const spread = lengths[3] ?? 0;
			return color.replace(/\s/g, '') === RING.replace(/\s/g, '') && spread >= 2;
		});
		const outline = style.outlineStyle !== 'none' && parseFloat(style.outlineWidth) >= 2 && !/rgba\([^)]*,\s*0\)/.test(style.outlineColor);
		if (!ringShadow && !outline) issues.push({ element, problem: `포커스 링이 보이지 않음 (box-shadow: ${style.boxShadow}, outline: ${style.outlineStyle} ${style.outlineWidth})` });

		// 크기
		const tag = el.tagName.toLowerCase();
		const type = (el.getAttribute('type') || '').toLowerCase();
		const isTarget = tag === 'button' || tag === 'input' || tag === 'select' || tag === 'textarea' || el.classList.contains('btn') || el.getAttribute('role') === 'tab' || el.getAttribute('role') === 'menuitem';
		if (isTarget) {
			const labelled = type === 'checkbox' || type === 'radio' || el.getAttribute('role') === 'switch';
			const box = (labelled ? (el.closest('label') ?? el) : el).getBoundingClientRect();
			if (box.height < 44 - 0.5) issues.push({ element, problem: `높이 ${box.height.toFixed(1)}px (44px 미만)` });
		}
		return issues;
	});
}

/**
 * Tab만 눌러 target에 포커스가 갈 때까지 이동한다. 지나가는 모든 요소를 점검해 issues에 모은다.
 * max번 안에 닿지 못하면 실패한다(키보드로 닿을 수 없다).
 */
export async function tabTo(page: Page, target: Locator, issues: FocusIssue[], max = 60) {
	for (let i = 0; i < max; i++) {
		await page.keyboard.press('Tab');
		issues.push(...(await checkFocused(page)));
		if (await target.evaluate((el) => el === document.activeElement).catch(() => false)) return;
	}
	throw new Error(`Tab을 ${max}번 눌러도 닿지 않았습니다: ${target}`);
}

/** 같은 문제를 한 번만 보이게 정리한다. */
export function unique(issues: FocusIssue[]) {
	return [...new Map(issues.map((i) => [`${i.element}|${i.problem}`, i])).values()];
}

/** axe로 WCAG 2.2 AA까지 자동 점검한다. 위반이 있으면 규칙, 영향, 대상 요소를 읽기 쉽게 보인다. */
export async function expectNoAxeViolations(page: Page, screen: string) {
	// SPA라 그리기 전에 점검하면 빈 화면을 통과시킨다. 화면 제목이 보일 때까지 기다린다
	await expect(page.locator('h1').first(), `${screen}: 화면이 그려지지 않았다`).toBeVisible();
	const result = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']).analyze();
	const report = result.violations.map(
		(v) => `[${v.impact}] ${v.id}: ${v.help}\n    ${v.nodes.map((n) => n.target.join(' ')).slice(0, 5).join('\n    ')}`
	);
	expect(report, `${screen}의 접근성 위반`).toEqual([]);
}

/** 문서 전체가 가로로 넘치지 않는다(가로 스크롤 없음). */
export async function expectNoHorizontalScroll(page: Page, screen: string) {
	await expect(page.locator('h1').first(), `${screen}: 화면이 그려지지 않았다`).toBeVisible();
	const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
	expect(overflow, `${screen}: 가로로 ${overflow}px 넘침`).toBeLessThanOrEqual(0);
}
