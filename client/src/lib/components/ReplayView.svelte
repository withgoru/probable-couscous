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
		onBack
	}: {
		classroomId: number;
		sessionId: number;
		start?: 'first' | 'last';
		ended?: boolean;
		takeFocus?: boolean;
		onBack: () => void;
	} = $props();

	const EMPTY_DECK: DeckSnapshot = { ready: false, total: null, position: null, clicksTotal: null };

	let replayState = $state<LiveState | null>(null);
	let problem = $state<string | null>(null);
	let frame = $state<HTMLIFrameElement | null>(null);
	let heading = $state<HTMLElement | null>(null);
	let backButton = $state<HTMLButtonElement | null>(null);
	let send: DeckBridge | null = null;
	let lastSent = '';
	let mainDeck = $state<DeckSnapshot>(EMPTY_DECK);
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

	onMount(() => {
		let alive = true;
		fetchClassLive(classroomId, sessionId)
			.then((s) => {
				if (!alive) return;
				replayState = s;
				// 일부러 연 회차는 처음부터, 수업이 끝나 이어 보면 보던 곳(교수의 마지막 위치)에서
				mine = start === 'last' ? startAt(s) : { slide: 1, click: 0 };
				// 누른 버튼이나 보던 수업 화면이 사라졌다면 초점을 제목으로 옮긴다
				if (takeFocus) tick().then(() => heading?.focus());
			})
			.catch((e) => {
				if (!alive) return;
				problem = e instanceof ApiError ? e.message : '회차를 불러오지 못했습니다.';
				if (takeFocus) tick().then(() => backButton?.focus());
			});
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
		<ErrorNotice title={problem} hint="목록으로 돌아가 다시 열어 주세요." />
	{:else if !replayState}
		<p class="text-sm text-muted-foreground">회차를 불러오는 중…</p>
	{:else}
		{#if !deck}
			<p class="rounded-md bg-foreground p-4 text-background">이 회차는 슬라이드 없이 진행했습니다.</p>
		{:else if !deck.available}
			<p class="rounded-md bg-foreground p-4 text-background">슬라이드를 열 수 없습니다. 자료는 계속 볼 수 있습니다.</p>
		{:else if !deck.public}
			<!-- 비공개 묶음은 서버가 학생에게 내주지 않는다(AC50) -->
			<p class="rounded-md bg-foreground p-4 text-background">이 회차의 슬라이드는 공개되지 않았습니다.</p>
		{:else}
			{#key deck.id}
				<div class="-mx-6 aspect-video overflow-hidden bg-foreground">
					<iframe bind:this={frame} title="다시 보는 슬라이드" src="/decks/{deck.id}/" class="h-full w-full border-0"></iframe>
				</div>
			{/key}
		{/if}
		<h1 bind:this={heading} tabindex="-1" class="text-lg leading-tight font-bold break-all outline-none">{replayState.session.title} 다시 보기</h1>
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
		<MaterialsPanel items={replayState.items} />
	{/if}
	<button bind:this={backButton} type="button" class="btn btn-outline self-start" onclick={onBack}>지난 회차 목록으로</button>
</div>
