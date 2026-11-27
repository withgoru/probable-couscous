/**
 * 슬라이드 iframe의 초점 표시(C14, WCAG 2.4.7).
 *
 * 키보드로 슬라이드 안에 들어가면 어디에 초점이 있는지 보여야 한다. 그런데 브라우저는 초점이 iframe 안의 문서에 있을 때
 * 바깥의 iframe 요소에 `:focus`도 `:focus-within`도 걸지 않고, 바깥 창의 blur·focusout도 늘 오지는 않는다.
 * 슬라이드 묶음은 같은 출처(`/decks/{id}/`)라 슬라이드 창 안의 focus·blur를 직접 듣고 `data-focused`를 붙인다.
 * 링은 이 표시로 그린다(iframe 옆의 `[data-frame-ring]`).
 *
 * `:focus-visible`처럼 키보드로 들어왔을 때만 표시한다. 손가락이나 마우스로 슬라이드를 누르면 떼고, 다시 Tab으로
 * 들어오면 붙인다(누를 때마다 링이 남지 않게).
 *
 * 한 화면에 초점을 받는 슬라이드 iframe은 하나다(교수 화면의 다음 슬라이드 미리보기와 프로젝터는 초점을 받지 않는다).
 */
export function frameFocus(node: HTMLIFrameElement) {
	let pointer = false; // 마지막으로 슬라이드를 누른 뒤 아직 키보드로 옮기지 않았다
	let inner: Window | null = null;

	const mark = (on: boolean) => node.toggleAttribute('data-focused', on);
	const onFocus = () => mark(!pointer);
	const onBlur = () => mark(false);
	const onPointer = () => {
		pointer = true;
		mark(false);
	};
	// 바깥에서 Tab(또는 Shift+Tab)을 누르면 다음에 슬라이드로 들어가는 것은 키보드다
	const onKey = (event: KeyboardEvent) => {
		if (event.key === 'Tab') pointer = false;
	};

	function detach() {
		if (!inner) return;
		inner.removeEventListener('focus', onFocus);
		inner.removeEventListener('blur', onBlur);
		inner.document?.removeEventListener('pointerdown', onPointer, true);
		inner = null;
	}

	// 슬라이드가 뜰 때마다(새 문서) 그 창에 붙는다. 다른 출처라 열 수 없으면 표시하지 않는다
	function attach() {
		detach();
		try {
			const win = node.contentWindow;
			if (!win) return;
			win.addEventListener('focus', onFocus);
			win.addEventListener('blur', onBlur);
			win.document.addEventListener('pointerdown', onPointer, true);
			inner = win;
		} catch {
			inner = null;
		}
	}

	node.addEventListener('load', attach);
	document.addEventListener('keydown', onKey, true);
	attach();
	return {
		destroy() {
			detach();
			node.removeEventListener('load', attach);
			document.removeEventListener('keydown', onKey, true);
			mark(false);
		}
	};
}
