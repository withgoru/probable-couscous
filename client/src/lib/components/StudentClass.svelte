<script lang="ts">
	import { onMount, tick, untrack } from 'svelte';
	import { SvelteMap } from 'svelte/reactivity';
	import { fetchClassSessions, type ClassSessionSummary } from '#lib/api.js';
	import { connectClass, type ClassLive, type ClassSnapshot } from '#lib/classLive.js';
	import ErrorNotice from '#lib/components/ErrorNotice.svelte';
	import MaterialsPanel from '#lib/components/MaterialsPanel.svelte';
	import Icon from '#lib/components/Icon.svelte';
	import NicknameCard from '#lib/components/NicknameCard.svelte';
	import { connectDeck, type DeckBridge, type DeckSnapshot, type Direction, type Position } from '#lib/deckBridge.js';
	import { isAfter, nextPosition, prevPosition } from '#lib/slides.js';
	import { dateTime } from '#lib/time.js';

	// 학생 수업 화면(002 AC23~AC25, AC29, AC30). 입장한 학생이 강좌 링크를 열면 보인다.
	// 진행 중인 회차가 없으면 대기 화면과 지난 회차 목록, 있으면 수업 화면이다. 수업이 시작되면 연결이 상태를 다시 받아
	// 새로 고치지 않아도 바뀐다. 발표자 노트는 받지도 보이지도 않는다(AC30).
	// 따라가는 중에 학생이 넘기면(이전·다음, 슬라이드 밀기, ←·→) 따라가기가 풀리고 직접 넘겨 본다. 범위는 가장 멀리 간
	// 위치까지다. '교수 화면으로'를 눌러야 다시 따라간다(AC26~AC28). 자료 탭의 알림·복사는 T025, 끝남·다시 보기는 T026
	const EMPTY_DECK: DeckSnapshot = { ready: false, total: null, position: null, clicksTotal: null };
	let { classroomId, title, nickname }: { classroomId: number; title: string; nickname: string } = $props();

	// 볼 수 있는 끝의 단계를 모르면(묶음을 바꾼 뒤) 그 슬라이드의 단계 전부까지다(AC41)
	const ALL_CLICKS = 9999;

	let snapshot = $state<ClassSnapshot | null>(null);
	let past = $state<ClassSessionSummary[] | null>(null);
	let pastFailed = $state(false);
	let pastRequest = 0; // 늦게 온 예전 응답이 새 목록을 덮지 않게 요청마다 번호를 붙인다
	let announcement = $state(''); // 화면이 바뀐 것을 화면 낭독기에 알린다(늘 있는 알림 자리)
	let lastSent = ''; // 슬라이드에 마지막으로 보낸 위치와 끝. 같으면 다시 보내지 않는다
	let frame = $state<HTMLIFrameElement | null>(null);
	let send: DeckBridge | null = null;
	let classLive: ClassLive | null = null;
	let mainDeck = $state<DeckSnapshot>(EMPTY_DECK);
	let mode = $state<'follow' | 'browse'>('follow');
	let mine = $state<Position | null>(null); // 직접 넘겨 보는 위치
	// 지나온 슬라이드의 단계 수. 이전 슬라이드로 돌아가면 그 슬라이드의 마지막 단계로 간다.
	// 바뀌면 이전 위치도 다시 계산하도록 반응형 Map이다. 회차나 묶음이 바뀌면 비운다
	const seenClicks = new SvelteMap<number, number>();
	let nextButton = $state<HTMLButtonElement | null>(null);
	let prevButton = $state<HTMLButtonElement | null>(null);

	const liveState = $derived(snapshot?.state?.session.status === 'live' ? snapshot.state : null);
	const deck = $derived(liveState?.deck ?? null);
	const current = $derived(liveState?.current ?? null);
	const limit = $derived(liveState ? { slide: liveState.limit.slide, click: liveState.limit.click ?? ALL_CLICKS } : null);
	const waiting = $derived(!!snapshot?.loaded && !liveState);
	// 화면에 보일 위치: 따라가는 중이면 교수 위치, 아니면 내가 넘긴 위치
	const shown = $derived(mode === 'follow' ? current : (mine ?? current));
	// 슬라이드가 그 위치를 그렸는가. 그리기 전에는 단계 수를 몰라 넘기지 않는다(단계를 건너뛰지 않게)
	const settled = $derived(
		!!shown && mainDeck.position?.slide === shown.slide && mainDeck.position.click === shown.click
	);
	const clicksTotal = $derived(settled ? mainDeck.clicksTotal : null);
	const total = $derived(mainDeck.total ?? deck?.slide_count ?? null);
	const nextRaw = $derived(shown ? nextPosition(shown, clicksTotal, total) : null);
	// 가장 멀리 간 위치 뒤로는 가지 않는다(AC27)
	const next = $derived(nextRaw && limit && !isAfter(nextRaw, limit) ? nextRaw : null);
	const prev = $derived(shown ? prevPosition(shown, seenClicks) : null);
	const atStart = $derived(settled && !prev);
	const atEnd = $derived(settled && !next);
	// 처음과 끝, 슬라이드가 따라오는 중에는 흐리게 한다. 진짜 disabled는 쓰지 않는다(초점을 잃지 않게)
	// 묶음이 남았는데 교수님이 아직 보여 주지 않아 못 가는 때만 그렇게 알린다(묶음의 마지막은 그냥 끝이다)
	const notShownYet = $derived(settled && !!nextRaw && !next);
	const canMove = $derived(!!deck?.available && settled);

	$effect(() => {
		if (mainDeck.position && mainDeck.clicksTotal !== null) seenClicks.set(mainDeck.position.slide, mainDeck.clicksTotal);
	});

	// 직접 넘겨 보던 곳이 볼 수 있는 끝이나 묶음 밖이 되면(교수가 넘겨 끝이 정해짐, 더 짧은 묶음으로 바뀜) 끝으로
	// 당긴다. 그대로 두면 애드온이 끝에서 멈춰 슬라이드가 그 위치를 그리지 못하고 넘기기가 멈춘다
	$effect(() => {
		if (mode !== 'browse' || !mine || !limit) return;
		let target = mine;
		if (isAfter(target, limit)) target = limit.click >= ALL_CLICKS ? { slide: limit.slide, click: 0 } : { ...limit };
		if (total !== null && target.slide > total) target = { slide: total, click: 0 };
		if (target !== mine) untrack(() => (mine = target));
	});

	// 묶음이 바뀌면 예전 묶음의 단계 수를 버린다
	let deckId: number | null = null;
	$effect(() => {
		const id = deck?.id ?? null;
		if (id === deckId) return;
		deckId = id;
		untrack(() => seenClicks.clear());
	});

	// 다른 회차의 수업이 시작되면 따라가는 중에서 다시 시작한다
	let sessionId: number | null = null;
	$effect(() => {
		const id = liveState?.session.id ?? null;
		if (id === sessionId) return;
		sessionId = id;
		untrack(() => {
			if (mode === 'browse') backToProfessor();
			seenClicks.clear();
		});
	});

	/** 학생이 넘기려 했다. 범위 안이면 따라가기를 풀고 한 단계 움직인다. 범위 밖이면 아무것도 하지 않는다. */
	function turn(direction: Direction) {
		if (!canMove) return;
		const target = direction === 'next' ? next : prev;
		if (!target) return; // 범위 밖: 움직이지 않고 따라가기도 그대로(AC26)
		if (mode === 'follow') setMode('browse');
		mine = target;
	}

	async function backToProfessor(moveFocus = false) {
		mine = null;
		setMode('follow');
		if (!moveFocus) return;
		await tick();
		(nextButton ?? prevButton)?.focus(); // 누른 버튼이 사라진다. 초점을 넘기기 버튼으로 옮긴다
	}

	function setMode(next: 'follow' | 'browse') {
		mode = next;
		send?.setMode(next);
		classLive?.setMode(next); // 교수 화면의 현황(AC15)
	}

	function typing(target: EventTarget | null): boolean {
		const el = target as HTMLElement | null;
		return !!el && (el.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName));
	}

	function onKey(event: KeyboardEvent) {
		// 다른 요소가 이미 처리한 키(가로 스크롤, 탭 목록 등)는 넘기지 않는다
		if (!liveState || event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey || typing(event.target))
			return;
		if (event.key === 'ArrowRight') turn('next');
		else if (event.key === 'ArrowLeft') turn('prev');
	}

	// 보일 위치로 간다: 따라가는 중이면 교수 위치(AC25, AC29), 직접 넘겨 보는 중이면 내 위치(교수가 넘겨도 그대로).
	// 볼 수 있는 끝을 먼저 보낸다. 애드온은 끝 뒤로 가는 지시를 끝에서 멈추므로, 새 슬라이드로 넘어갈 때 끝이 늦게
	// 가면 따라가지 못한다. 위치와 끝이 그대로면(자료가 오는 등) 다시 보내지 않는다
	$effect(() => {
		const key = limit && shown ? JSON.stringify([limit, shown]) : ''; // 먼저 읽어야 바뀔 때 다시 돈다
		if (!send || !limit || !shown) return;
		if (key === lastSent) return;
		lastSent = key;
		send.setLimit(limit);
		send.goto(shown);
	});

	// 대기에서 수업으로 바뀌면 알린다(AC23). 처음 열 때 이미 수업 중이면 알리지 않는다
	let wasWaiting = false;
	$effect(() => {
		if (waiting) wasWaiting = true;
		else if (liveState && wasWaiting) {
			wasWaiting = false;
			announcement = '수업이 시작되었습니다.';
		}
	});

	// 슬라이드 iframe이 생기면 다리를 잇는다
	$effect(() => {
		if (!frame) return;
		const win = frame;
		// 슬라이드 안에서 넘기려 한 것(밀기, ←·→)도 넘기기다(AC26)
		const bridge = connectDeck(() => win.contentWindow, { onIntent: (direction) => turn(direction) });
		const unsubscribe = bridge.subscribe((s) => (mainDeck = s));
		send = bridge;
		untrack(() => {
			bridge.setMode(mode);
			if (limit) bridge.setLimit(limit);
			if (shown) bridge.goto(shown);
			lastSent = limit && shown ? JSON.stringify([limit, shown]) : '';
		});
		return () => {
			unsubscribe();
			send = null;
			lastSent = '';
			mainDeck = EMPTY_DECK;
			bridge.stop();
		};
	});

	// 대기 화면이 될 때마다 지난 회차 목록을 받는다(수업이 끝나 돌아와도 새 목록)
	$effect(() => {
		if (!waiting) return;
		untrack(() => {
			const request = ++pastRequest;
			past = null;
			pastFailed = false;
			fetchClassSessions(classroomId)
				.then((list) => {
					if (request === pastRequest) past = list.items.filter((s) => s.status === 'ended');
				})
				.catch(() => {
					if (request === pastRequest) pastFailed = true;
				});
		});
	});

	onMount(() => {
		const live = connectClass(classroomId, { role: 'student' });
		classLive = live;
		const unsubscribe = live.subscribe((s) => (snapshot = s));
		return () => {
			unsubscribe();
			live.stop();
			classLive = null;
		};
	});
</script>

<svelte:window onkeydown={onKey} />

<p role="status" data-class-status class="sr-only">{announcement}</p>

{#if liveState}
	<div class="flex flex-col gap-4">
		<!-- 슬라이드(화면 폭, 16:9). 왼쪽 위에 아무것도 얹지 않는다 -->
		{#if !deck}
			<p class="rounded-md bg-foreground p-4 text-background">이번 수업은 슬라이드 없이 진행합니다. 자료를 확인하세요.</p>
		{:else if !deck.available}
			<p class="rounded-md bg-foreground p-4 text-background">슬라이드를 열 수 없습니다. 자료는 계속 볼 수 있습니다.</p>
		{:else}
			{#key deck.id}
				<!-- 화면 폭 전체(AC24): 입장 화면의 옆 여백을 넘어선다 -->
				<div class="-mx-6 aspect-video overflow-hidden bg-foreground">
					<iframe bind:this={frame} title="수업 슬라이드" src="/decks/{deck.id}/" class="h-full w-full border-0"></iframe>
				</div>
			{/key}
		{/if}

		<!-- 수업 정보 줄 -->
		<div class="flex flex-col gap-0.5">
			<h1 tabindex="-1" class="text-lg leading-tight font-bold break-all outline-none">{title}</h1>
			<p class="text-sm">{liveState.session.title}</p>
			<p class="flex items-center gap-1 text-sm">
				<Icon name="user" class="size-4" /><span class="text-muted-foreground">내 닉네임</span>
				<span class="font-medium">{nickname}</span>
			</p>
		</div>

		<!-- 따라가기 줄(AC24, AC26, AC28). 상태 글은 바뀔 때 화면 낭독기에도 읽힌다 -->
		<div class="flex flex-col gap-2">
			<p role="status" class="flex items-center gap-2 text-sm font-medium">
				<Icon name="presentation" class="size-4" />
				{#if mode === 'follow'}
					교수 화면 따라가는 중
				{:else}
					직접 넘겨 보는 중 · 교수 화면은 {current?.slide}번 슬라이드입니다.
				{/if}
			</p>
			{#if deck?.available}
				<div class="flex flex-wrap items-center gap-2">
					<!-- 흐림은 처음·끝에서만 보인다. 슬라이드가 따라오는 잠깐은 누른 것만 받지 않는다(깜빡이지 않게) -->
					<button
						type="button"
						class="btn btn-outline {atStart ? 'opacity-50' : ''}"
						bind:this={prevButton}
						aria-disabled={!canMove || atStart}
						onclick={() => turn('prev')}>이전</button
					>
					<button
						type="button"
						class="btn btn-outline {atEnd ? 'opacity-50' : ''}"
						bind:this={nextButton}
						aria-disabled={!canMove || atEnd}
						aria-describedby={notShownYet ? 'not-shown-yet' : undefined}
						onclick={() => turn('next')}>다음</button
					>
					{#if mode === 'browse'}
						<button type="button" class="btn btn-default" onclick={() => backToProfessor(true)}>교수 화면으로</button>
					{/if}
				</div>
				{#if notShownYet}
					<p id="not-shown-yet" class="text-sm text-muted-foreground">교수님이 아직 보여 주지 않은 슬라이드입니다.</p>
				{/if}
			{/if}
		</div>

		<!-- 자료(AC33~AC35). 회차가 바뀌면 새로 시작한다(새 회차의 항목을 '새 자료'로 세지 않게) -->
		{#key liveState.session.id}
			<MaterialsPanel items={liveState.items} />
		{/key}
	</div>
{:else}
	<!-- 입장 완료와 대기(AC23, 001 AC28) -->
	<div class="flex flex-col gap-1">
		<span class="flex items-center gap-1.5 text-sm font-medium text-success-text">
			<Icon name="check" class="size-4" />입장했습니다
		</span>
		<h1 tabindex="-1" class="text-2xl leading-tight font-bold break-all outline-none">{title}</h1>
	</div>
	<NicknameCard {nickname} />
	{#if snapshot?.loadError && !snapshot.loaded}
		<ErrorNotice title={snapshot.loadError} hint="잠시 뒤 자동으로 다시 불러옵니다." />
	{:else if !waiting}
		<p class="text-sm text-muted-foreground">수업을 불러오는 중…</p>
	{:else}
		<p>지금 진행 중인 수업이 없습니다. 수업이 시작되면 이 화면이 바뀝니다.</p>
		<section class="flex flex-col gap-2" aria-labelledby="past-heading">
			<h2 id="past-heading" class="text-base font-semibold">지난 회차</h2>
			{#if pastFailed}
				<p class="text-sm text-muted-foreground">지난 회차를 불러오지 못했습니다. 잠시 뒤 다시 열어 주세요.</p>
			{:else if past === null}
				<p class="text-sm text-muted-foreground">목록을 불러오는 중…</p>
			{:else if past.length === 0}
				<p class="text-sm text-muted-foreground">아직 끝난 회차가 없습니다.</p>
			{:else}
				<ul class="flex flex-col gap-2" aria-labelledby="past-heading">
					{#each past as s (s.id)}
						<li class="flex items-center justify-between gap-2 rounded-md border border-border p-3 text-sm">
							<span class="font-medium">{s.title}</span>
							{#if s.ended_at}<span class="text-muted-foreground">{dateTime(s.ended_at)}</span>{/if}
						</li>
					{/each}
				</ul>
			{/if}
		</section>
	{/if}
{/if}
