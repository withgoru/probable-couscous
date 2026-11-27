// @vitest-environment jsdom
import { afterEach, describe, expect, it } from 'vitest';
import { frameFocus } from './frameFocus';

afterEach(() => {
	document.body.innerHTML = '';
});

// 브라우저는 초점이 iframe 안에 있을 때 바깥의 iframe 요소에 :focus를 걸지 않는다. 슬라이드는 같은 출처라
// 슬라이드 창 안의 focus·blur·pointerdown을 듣고 표시(data-focused)를 붙인다. 링은 그 표시로 그린다
function setup() {
	const frame = document.createElement('iframe');
	document.body.append(frame);
	const action = frameFocus(frame);
	const inner = frame.contentWindow!;
	frame.dispatchEvent(new Event('load')); // 슬라이드가 떴다
	return { frame, inner, action };
}
const marked = (frame: HTMLIFrameElement) => frame.hasAttribute('data-focused');

describe('슬라이드 iframe의 초점 표시 (C14)', () => {
	it('키보드(Tab)로 슬라이드에 들어가면 표시를 붙이고, 나오면 뗀다', () => {
		const { frame, inner } = setup();
		document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab' }));
		inner.dispatchEvent(new Event('focus'));
		expect(marked(frame)).toBe(true);
		inner.dispatchEvent(new Event('blur'));
		expect(marked(frame)).toBe(false);
	});

	it('손가락이나 마우스로 슬라이드를 누르면 표시를 붙이지 않는다(누를 때마다 링이 남지 않게)', () => {
		const { frame, inner } = setup();
		inner.document.dispatchEvent(new Event('pointerdown'));
		inner.dispatchEvent(new Event('focus'));
		expect(marked(frame)).toBe(false);
	});

	it('누른 뒤라도 다시 키보드로 들어오면 표시를 붙인다', () => {
		const { frame, inner } = setup();
		inner.document.dispatchEvent(new Event('pointerdown'));
		inner.dispatchEvent(new Event('focus'));
		inner.dispatchEvent(new Event('blur'));
		document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true }));
		inner.dispatchEvent(new Event('focus'));
		expect(marked(frame)).toBe(true);
	});

	it('키보드로 들어와 있다가 슬라이드를 누르면 표시를 뗀다', () => {
		const { frame, inner } = setup();
		document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab' }));
		inner.dispatchEvent(new Event('focus'));
		inner.document.dispatchEvent(new Event('pointerdown'));
		expect(marked(frame)).toBe(false);
	});

	it('슬라이드가 다시 뜨면(새 문서) 그 창에 다시 붙는다', () => {
		const { frame, inner } = setup();
		frame.dispatchEvent(new Event('load'));
		document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab' }));
		inner.dispatchEvent(new Event('focus'));
		expect(marked(frame)).toBe(true);
	});

	it('그만 쓰면 듣기를 멈추고 표시를 뗀다', () => {
		const { frame, inner, action } = setup();
		document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab' }));
		inner.dispatchEvent(new Event('focus'));
		action.destroy();
		expect(marked(frame)).toBe(false);
		inner.dispatchEvent(new Event('focus'));
		expect(marked(frame)).toBe(false);
	});
});
