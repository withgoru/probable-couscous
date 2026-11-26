<script lang="ts">
	import { onMount, tick, untrack } from 'svelte';
	import { SvelteMap } from 'svelte/reactivity';
	import { ApiError, fetchClassLive } from '#lib/api.js';
	import type { LiveState } from '#lib/classLive.js';
	import ErrorNotice from '#lib/components/ErrorNotice.svelte';
	import MaterialsPanel from '#lib/components/MaterialsPanel.svelte';
	import { connectDeck, type DeckBridge, type DeckSnapshot, type Direction, type Position } from '#lib/deckBridge.js';
	import { isAfter, nextPosition, prevPosition } from '#lib/slides.js';

	// 지난 회차 다시 보기(002 AC38, AC39, AC41). 끝난 회차라 바뀌지 않으므로 상태를 한 번 받는다.
	// 슬라이드는 처음부터(또는 수업이 끝나 이어 볼 때는 보던 곳에서) 가장 멀리 간 위치까지 넘겨 볼 수 있고,
	// 거두지 않은 자료가 보인다. 넘기기 규칙은 수업 중 직접 넘겨 보기(T024)와 같다
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

	const ALL_CLICKS = 9999; // 끝의 단계를 모르면(묶음을 바꾼 회차) 그 슬라이드의 단계 전부(AC41)
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
	const limit = $derived(replayState ? { slide: replayState.limit.slide, click: replayState.limit.click ?? ALL_CLICKS } : null);
	const settled = $derived(
		!!mine && mainDeck.position?.slide === mine.slide && mainDeck.position.click === mine.click
	);
	const clicksTotal = $derived(settled ? mainDeck.clicksTotal : null);
	const total = $derived(mainDeck.total ?? deck?.slide_count ?? null);
	const nextRaw = $derived(mine ? nextPosition(mine, clicksTotal, total) : null);
	const next = $derived(nextRaw && limit && !isAfter(nextRaw, limit) ? nextRaw : null);
	const prev = $derived(mine ? prevPosition(mine, seenClicks) : null);
	const atStart = $derived(settled && !prev);
	const atEnd = $derived(settled && !next);
	const notShownYet = $derived(settled && !!nextRaw && !next);
	const canMove = $derived(!!deck?.available && settled);

	$effect(() => {
		if (mainDeck.position && mainDeck.clicksTotal !== null) seenClicks.set(mainDeck.position.slide, mainDeck.clicksTotal);
	});

	// 볼 수 있는 끝을 먼저 보내고 위치를 보낸다(애드온이 끝에서 멈추므로). 같으면 다시 보내지 않는다
	$effect(() => {
		const key = limit && mine ? JSON.stringify([limit, mine]) : '';
		if (!send || !limit || !mine || key === lastSent) return;
		lastSent = key;
		send.setLimit(limit);
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
			if (limit) bridge.setLimit(limit);
			if (mine) bridge.goto(mine);
			lastSent = limit && mine ? JSON.stringify([limit, mine]) : '';
		});
		return () => {
			unsubscribe();
			send = null;
			lastSent = '';
			mainDeck = EMPTY_DECK;
			bridge.stop();
		};
	});

	// 보던 곳(교수의 마지막 위치)에서 이어 본다. 볼 수 있는 끝이나 묶음 밖이면(수업 중에 더 짧은 묶음으로 바꿈) 끝으로
	// 당긴다. 그대로 두면 애드온이 끝에서 멈춰 슬라이드가 그 위치를 그리지 못하고 넘기기가 멈춘다
	function startAt(s: LiveState): Position {
		let at: Position = { ...s.current };
		const end = { slide: s.limit.slide, click: s.limit.click ?? ALL_CLICKS };
		if (isAfter(at, end)) at = { slide: s.limit.slide, click: s.limit.click ?? 0 };
		if (s.deck && at.slide > s.deck.slide_count) at = { slide: Math.max(1, s.deck.slide_count), click: 0 };
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
		{:else}
			{#key deck.id}
				<div class="-mx-6 aspect-video overflow-hidden bg-foreground">
					<iframe bind:this={frame} title="다시 보는 슬라이드" src="/decks/{deck.id}/" class="h-full w-full border-0"></iframe>
				</div>
			{/key}
		{/if}
		<h1 bind:this={heading} tabindex="-1" class="text-lg leading-tight font-bold break-all outline-none">{replayState.session.title} 다시 보기</h1>
		{#if deck?.available}
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
					aria-describedby={notShownYet ? 'replay-not-shown' : undefined}
					onclick={() => turn('next')}>다음</button
				>
				<span class="text-sm text-muted-foreground" aria-live="polite">{mine?.slide} / {total ?? '?'} 슬라이드</span>
			</div>
			{#if notShownYet}
				<p id="replay-not-shown" class="text-sm text-muted-foreground">수업에서 보여 주지 않은 슬라이드입니다.</p>
			{/if}
		{/if}
		<MaterialsPanel items={replayState.items} />
	{/if}
	<button bind:this={backButton} type="button" class="btn btn-outline self-start" onclick={onBack}>지난 회차 목록으로</button>
</div>
