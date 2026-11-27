<script lang="ts">
	import { onMount, tick, untrack } from 'svelte';
	import { SvelteMap } from 'svelte/reactivity';
	import { ApiError, fetchClassLive } from '#lib/api.js';
	import type { LiveState } from '#lib/classLive.js';
	import ErrorNotice from '#lib/components/ErrorNotice.svelte';
	import MaterialsPanel from '#lib/components/MaterialsPanel.svelte';
	import { connectDeck, type DeckBridge, type DeckSnapshot, type Direction, type Position } from '#lib/deckBridge.js';
	import { nextPosition, prevPosition } from '#lib/slides.js';

	// 지난 회차 다시 보기(002 AC38, AC39, AC41). 끝난 회차라 바뀌지 않으므로 상태를 한 번 받는다.
	// 공개 묶음이면 슬라이드를 처음부터(또는 수업이 끝나 이어 볼 때는 보던 곳에서) 끝까지 넘겨 볼 수 있다. 비공개 묶음이면
	// 슬라이드를 얹지 않는다(AC50). 거두지 않은 자료가 보인다. 넘기기 규칙은 수업 중 직접 넘겨 보기와 같다
	let {
		classroomId,
		sessionId,
		start = 'first',
		ended = false,
		takeFocus = false,
		refresh = 0,
		preview = false,
		onAnnounce = () => {},
		onBack
	}: {
		classroomId: number;
		sessionId: number;
		start?: 'first' | 'last';
		ended?: boolean;
		takeFocus?: boolean;
		/** 바뀌면 상태를 다시 받는다(그 회차의 묶음이나 공개 여부가 바뀜, AC41). */
		refresh?: number;
		/** 미리 보기(공개 묶음이 있는 예정 회차, AC49). 이름과 돌아가기 글이 다르고, 수업 전이라 자료가 없다. */
		preview?: boolean;
		/** 화면 낭독기에 알릴 글(학생 수업 화면의 늘 있는 알림 자리로 간다). 공개·비공개가 바뀔 때 쓴다. */
		onAnnounce?: (text: string) => void;
		onBack: () => void;
	} = $props();

	const EMPTY_DECK: DeckSnapshot = { ready: false, total: null, position: null, clicksTotal: null };

	let replayState = $state<LiveState | null>(null);
	let problem = $state<string | null>(null);
	let problemHint = $state('목록으로 돌아가 다시 열어 주세요.');
	const kind = $derived(preview ? '미리 보기' : '다시 보기');
	let frame = $state<HTMLIFrameElement | null>(null);
	let heading = $state<HTMLElement | null>(null);
	let backButton = $state<HTMLButtonElement | null>(null);
	let send: DeckBridge | null = null;
	let lastSent = '';
	let mainDeck = $state<DeckSnapshot>(EMPTY_DECK);

	// 슬라이드가 오래 준비되지 않으면(파일을 받지 못함, 애드온 문제) 불러오는 중에 머물지 않고 열 수 없다고 알린다
	const SLOW_MS = 15_000;
	let stalled = $state(false);
	$effect(() => {
		const f = frame;
		const ready = mainDeck.ready;
		untrack(() => (stalled = false));
		if (!f || ready) return;
		const timer = setTimeout(() => (stalled = true), SLOW_MS);
		return () => clearTimeout(timer);
	});
	let mine = $state<Position | null>(null);
	const seenClicks = new SvelteMap<number, number>();

	const deck = $derived(replayState?.deck ?? null);
	const settled = $derived(
		!!mine && mainDeck.position?.slide === mine.slide && mainDeck.position.click === mine.click
	);
	const clicksTotal = $derived(settled ? mainDeck.clicksTotal : null);
	const total = $derived(mainDeck.total ?? deck?.slide_count ?? null);
	const next = $derived(mine ? nextPosition(mine, clicksTotal, total) : null);
	const prev = $derived(mine ? prevPosition(mine, seenClicks) : null);
	const atStart = $derived(settled && !prev);
	const atEnd = $derived(settled && !next);
	const canMove = $derived(!!deck?.available && deck.public && settled);

	$effect(() => {
		if (mainDeck.position && mainDeck.clicksTotal !== null) seenClicks.set(mainDeck.position.slide, mainDeck.clicksTotal);
	});

	// 묶음이 바뀌면 예전 묶음의 단계 수를 버린다(이전 슬라이드의 마지막 단계를 새 묶음으로 계산한다)
	let deckId: number | null = null;
	$effect(() => {
		const id = deck?.id ?? null;
		if (id === deckId) return;
		deckId = id;
		untrack(() => seenClicks.clear());
	});

	// 넘긴 위치를 슬라이드에 보낸다. 같으면 다시 보내지 않는다
	$effect(() => {
		const key = mine ? JSON.stringify(mine) : '';
		if (!send || !mine || key === lastSent) return;
		lastSent = key;
		send.goto(mine);
	});

	$effect(() => {
		if (!frame) return;
		const win = frame;
		const bridge = connectDeck(() => win.contentWindow, { onIntent: (direction) => turn(direction) });
		const unsubscribe = bridge.subscribe((s) => (mainDeck = s));
		bridge.setMode('browse');
		send = bridge;
		untrack(() => {
			if (mine) bridge.goto(mine);
			lastSent = mine ? JSON.stringify(mine) : '';
		});
		return () => {
			unsubscribe();
			send = null;
			lastSent = '';
			mainDeck = EMPTY_DECK;
			bridge.stop();
		};
	});

	// 보던 곳(교수의 마지막 위치)에서 이어 본다. 묶음 밖이면(끝난 뒤 더 짧은 묶음으로 바꿈) 마지막 슬라이드에서
	function startAt(s: LiveState): Position {
		const at: Position = { ...s.current };
		if (s.deck && at.slide > s.deck.slide_count) return { slide: Math.max(1, s.deck.slide_count), click: 0 };
		return at;
	}

	function turn(direction: Direction) {
		if (!canMove) return;
		const target = direction === 'next' ? next : prev;
		if (target) mine = target; // 범위 밖이면 움직이지 않는다
	}

	function onKey(event: KeyboardEvent) {
		if (!replayState || event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey) return;
		const el = event.target as HTMLElement | null;
		if (el && (el.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName))) return;
		if (event.key === 'ArrowRight') turn('next');
		else if (event.key === 'ArrowLeft') turn('prev');
	}

	// 상태 받기. 처음 받기와 다시 받기(refresh)가 같은 길을 지나고, 늦게 온 예전 응답은 버린다(요청마다 번호).
	// - 처음 보이는 응답(먼저 온 다시 받기 포함): 시작 위치를 정하고, 받으라고 했으면 제목으로 초점을 옮긴다
	// - 같은 묶음: 보던 곳을 지키되 묶음 밖이면 마지막 슬라이드로 당긴다. 다른 묶음: 처음부터 본다(AC41)
	// - 공개·비공개가 바뀌면 알리고, 슬라이드가 사라져 초점을 잃었으면 제목으로 옮긴다
	// - 받지 못하면: 보던 화면이 있으면 그대로 두고, 없으면 이유와 할 일을 보인다
	const SHOWN = '슬라이드가 공개되었습니다.';
	const PREVIEW_GONE = '이 회차는 이제 미리 볼 수 없습니다.';
	const HIDDEN = '이 회차의 슬라이드는 공개되지 않았습니다.';
	let request = 0;
	let alive = true;
	let gone = false; // 미리 볼 수 없게 됐다. 목록으로 돌아가 다시 연다(다시 받아도 바꾸지 않는다)

	function load() {
		const ticket = ++request;
		fetchClassLive(classroomId, sessionId)
			.then((s) => {
				if (!alive || ticket !== request || gone) return;
				const before = replayState;
				replayState = s;
				problem = null;
				if (!before) {
					// 일부러 연 회차는 처음부터, 수업이 끝나 이어 보면 보던 곳(교수의 마지막 위치)에서
					mine = start === 'last' ? startAt(s) : { slide: 1, click: 0 };
					if (takeFocus) tick().then(() => heading?.focus()); // 누른 버튼이나 보던 수업 화면이 사라졌다
					return;
				}
				if (before.deck?.id !== s.deck?.id) mine = { slide: 1, click: 0 };
				else if (mine && s.deck && mine.slide > s.deck.slide_count)
					mine = { slide: Math.max(1, s.deck.slide_count), click: 0 };
				const wasShown = showsSlides(before);
				const nowShown = showsSlides(s);
				if (wasShown !== nowShown && s.deck) onAnnounce(nowShown ? SHOWN : HIDDEN);
				if (wasShown && !nowShown)
					tick().then(() => {
						if (!document.activeElement || document.activeElement === document.body) heading?.focus();
					});
			})
			.catch((e) => {
				if (!alive || ticket !== request || gone) return;
				// 미리 볼 회차가 비공개가 되거나 묶음이 지워졌다(학생에게는 없는 회차가 된다). 처음 열 때도 같다.
				// 경고(role=alert)로 읽히므로 알림 자리로는 다시 알리지 않는다
				if (preview && e instanceof ApiError && e.status === 404) {
					gone = true;
					const wasShowing = !!replayState;
					replayState = null;
					problem = PREVIEW_GONE;
					problemHint = '목록으로 돌아가 주세요.';
					if (!wasShowing) {
						if (takeFocus) tick().then(() => backButton?.focus());
						return;
					}
					tick().then(() => {
						if (!document.activeElement || document.activeElement === document.body) backButton?.focus();
					});
					return;
				}
				if (replayState) return; // 보던 화면은 그대로 둔다
				problem = e instanceof ApiError ? e.message : '회차를 불러오지 못했습니다.';
				if (takeFocus) tick().then(() => backButton?.focus());
			});
	}

	function showsSlides(s: LiveState): boolean {
		return !!s.deck?.available && s.deck.public;
	}

	let lastRefresh = untrack(() => refresh);
	$effect(() => {
		const now = refresh;
		if (now === lastRefresh) return;
		lastRefresh = now;
		untrack(load);
	});

	onMount(() => {
		load();
		return () => {
			alive = false;
		};
	});
</script>

<svelte:window onkeydown={onKey} />

<div class="flex flex-col gap-4">
	<!-- 화면 낭독기에는 학생 수업 화면의 알림 자리가 알린다(이 글은 처음부터 있어 읽히지 않는다) -->
	{#if ended}<p class="font-semibold">수업이 끝났습니다.</p>{/if}
	{#if problem}
		<ErrorNotice title={problem} hint={problemHint} />
	{:else if !replayState}
		<p class="text-sm text-muted-foreground">회차를 불러오는 중…</p>
	{:else}
		{#if !deck}
			<p class="rounded-md bg-foreground p-4 text-background">이 회차는 슬라이드 없이 진행했습니다.</p>
		{:else if !deck.available}
			<p class="rounded-md bg-foreground p-4 text-background">
				{preview ? '슬라이드를 열 수 없습니다. 목록으로 돌아가 주세요.' : '슬라이드를 열 수 없습니다. 자료는 계속 볼 수 있습니다.'}
			</p>
		{:else if !deck.public}
			<!-- 비공개 묶음은 서버가 학생에게 내주지 않는다(AC50) -->
			<p class="rounded-md bg-foreground p-4 text-background">{HIDDEN}</p>
		{:else}
			{#key deck.id}
				<div class="relative -mx-6 aspect-video overflow-hidden bg-foreground">
					<iframe bind:this={frame} title={preview ? '미리 보는 슬라이드' : '다시 보는 슬라이드'} src="/decks/{deck.id}/" class="h-full w-full border-0"></iframe>
					{#if !mainDeck.ready}
						<!-- 느린 휴대폰: 슬라이드를 받는 동안. 그 사이에도 자료는 쓸 수 있다(오류 동작 "학생 휴대폰이 느림").
						     슬라이드 위를 가려 글자가 겹치지 않게 한다. 끝내 준비되지 않으면 열 수 없다고 알린다 -->
						<p class="absolute inset-0 flex items-center justify-center bg-foreground p-4 text-center text-sm text-background">
							{stalled ? '슬라이드를 열 수 없습니다. 자료는 계속 볼 수 있습니다.' : '슬라이드를 불러오는 중…'}
						</p>
					{/if}
				</div>
			{/key}
		{/if}
		<h1 bind:this={heading} tabindex="-1" class="text-lg leading-tight font-bold break-all outline-none">{replayState.session.title} {kind}</h1>
		{#if deck?.available && deck.public}
			<div class="flex flex-wrap items-center gap-2">
				<button
					type="button"
					class="btn btn-outline {atStart ? 'opacity-50' : ''}"
					aria-disabled={!canMove || atStart}
					onclick={() => turn('prev')}>이전</button
				>
				<button
					type="button"
					class="btn btn-outline {atEnd ? 'opacity-50' : ''}"
					aria-disabled={!canMove || atEnd}
					onclick={() => turn('next')}>다음</button
				>
				<span class="text-sm text-muted-foreground" aria-live="polite">{mine?.slide} / {total ?? '?'} 슬라이드</span>
			</div>
		{/if}
		{#if !preview}<MaterialsPanel items={replayState.items} />{/if}
	{/if}
	<button bind:this={backButton} type="button" class="btn btn-outline self-start" onclick={onBack}>{preview ? '회차 목록으로' : '지난 회차 목록으로'}</button>
</div>
