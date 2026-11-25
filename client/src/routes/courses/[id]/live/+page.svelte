<script lang="ts">
	import { onMount, untrack } from 'svelte';
	import { fetchDeckNotes, type DeckNotes } from '#lib/api.js';
	import { connectClass, type ClassLive, type ClassSnapshot, type GotoFailure } from '#lib/classLive.js';
	import ErrorNotice from '#lib/components/ErrorNotice.svelte';
	import Icon from '#lib/components/Icon.svelte';
	import { connectDeck, type DeckBridge, type DeckSnapshot, type Position } from '#lib/deckBridge.js';
	import { nextPosition, prevPosition } from '#lib/slides.js';
	import type { PageProps } from './$types';

	// 교수 수업 화면(002 AC12~AC14, AC16, AC17). 메뉴바가 없다(레이아웃이 수업 중 화면에는 그리지 않는다).
	// 위치의 진실은 서버다(C13): 넘기면 서버에 보내고, 서버가 DB에 쓴 뒤 발행한 위치로 이 화면과 다른 탭이 함께 움직인다
	let { data }: PageProps = $props();

	const EMPTY_DECK: DeckSnapshot = { ready: false, total: null, position: null, clicksTotal: null };

	let snapshot = $state<ClassSnapshot | null>(null);
	let mainDeck = $state<DeckSnapshot>(EMPTY_DECK);
	let notes = $state<DeckNotes | null>(null);
	let notesError = $state(false);
	let moving = $state(false); // ack를 받기 전에는 다시 보내지 않는다
	let moveError = $state<string | null>(null);
	let now = $state(Date.now());
	// 지나온 슬라이드의 단계 수. 이전 슬라이드로 돌아갈 때 그 슬라이드의 마지막 단계로 간다
	const seenClicks = new Map<number, number>();

	let classLive: ClassLive | null = null;
	let currentFrame = $state<HTMLIFrameElement | null>(null);
	let nextFrame = $state<HTMLIFrameElement | null>(null);
	let currentBridge: DeckBridge | null = null;
	let nextBridge: DeckBridge | null = null;

	const liveState = $derived(snapshot?.state ?? null);
	const deck = $derived(liveState?.deck ?? null);
	const showSlides = $derived(!!deck?.available && liveState?.session.status === 'live');
	const current = $derived(liveState?.current ?? null);
	const total = $derived(mainDeck.total ?? deck?.slide_count ?? null);
	// 현재 슬라이드가 서버 위치를 그렸는가. 그리기 전에는 그 슬라이드의 단계 수를 모르므로 넘기지 않는다
	// (서버의 ack와 슬라이드가 따라오는 사이에 누르면 단계를 건너뛸 수 있다)
	const settled = $derived(
		!!current && mainDeck.position?.slide === current.slide && mainDeck.position.click === current.click
	);
	const clicksTotal = $derived(settled ? mainDeck.clicksTotal : null);
	const next = $derived(current ? nextPosition(current, clicksTotal, total) : null);
	const prev = $derived(current ? prevPosition(current, seenClicks) : null);
	// 기다리는 동안은 흐리게만 하고(초점을 잃지 않게) 처음과 끝에서만 누를 수 없게 한다
	const busy = $derived(moving || !settled);
	const atStart = $derived(settled && !prev);
	const atEnd = $derived(settled && !next);
	const note = $derived(current && notes ? (notes.slides.find((s) => s.no === current.slide)?.note ?? '') : null);
	const countMismatch = $derived(
		notes && mainDeck.total !== null && notes.slide_count !== mainDeck.total
			? `노트(${notes.slide_count}장)와 슬라이드(${mainDeck.total}장)의 수가 다릅니다.`
			: null
	);
	const elapsed = $derived.by(() => {
		const started = liveState?.session.started_at;
		if (!started) return null;
		const minutes = Math.max(0, Math.floor((now - new Date(started).getTime()) / 60_000));
		return minutes >= 60 ? `${Math.floor(minutes / 60)}시간 ${minutes % 60}분` : `${minutes}분`;
	});
	const online = $derived(snapshot?.presence ? snapshot.presence.follow + snapshot.presence.browse : null);
	const heading = $derived(liveState ? `${liveState.session.title} · 수업 중` : '수업 화면');

	async function move(target: Position | null) {
		if (!target || busy || !classLive) return;
		moving = true;
		moveError = null;
		try {
			await classLive.goto(target); // 서버가 기록한 뒤 발행한 위치로 슬라이드가 움직인다
		} catch (e) {
			moveError = (e as GotoFailure)?.message ?? '넘기지 못했습니다. 다시 눌러 주세요.';
		} finally {
			moving = false;
		}
	}

	function typing(target: EventTarget | null): boolean {
		const el = target as HTMLElement | null;
		return !!el && (el.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName));
	}

	/** Space를 제 동작으로 쓰는 요소(버튼, 링크). 여기서 Space는 그 요소를 누르는 것이다. */
	function pressable(target: EventTarget | null): boolean {
		const el = target as HTMLElement | null;
		return !!el?.closest?.('button, a[href], summary, [role="button"], [role="link"]');
	}

	function onKey(event: KeyboardEvent) {
		if (!showSlides || event.repeat || event.ctrlKey || event.metaKey || event.altKey || typing(event.target)) return;
		if (event.key === ' ' && (event.shiftKey || pressable(event.target))) return;
		if (event.key === 'ArrowRight' || event.key === ' ') {
			event.preventDefault();
			move(next);
		} else if (event.key === 'ArrowLeft') {
			event.preventDefault();
			move(prev);
		}
	}

	// 서버의 위치가 바뀌면 현재 슬라이드와 미리보기를 옮긴다
	$effect(() => {
		if (current) currentBridge?.goto(current);
	});
	$effect(() => {
		const target = next ?? current;
		if (target) nextBridge?.goto(target);
	});
	$effect(() => {
		if (mainDeck.position && mainDeck.clicksTotal !== null) seenClicks.set(mainDeck.position.slide, mainDeck.clicksTotal);
	});

	// 회차와 묶음이 정해지면 노트를 한 번 받는다
	let notesFor = '';
	$effect(() => {
		if (!data.classroom || !liveState || !deck?.available) return;
		const key = `${liveState.session.id}:${deck.id}`;
		if (key === notesFor) return;
		notesFor = key;
		notes = null;
		notesError = false;
		// 묶음이 그 사이 바뀌었으면 늦게 온 예전 응답은 버린다
		fetchDeckNotes(data.classroom.id, liveState.session.id)
			.then((n) => {
				if (notesFor === key) notes = n;
			})
			.catch(() => {
				if (notesFor === key) notesError = true;
			});
	});

	// iframe이 생기면 다리를 잇는다(묶음이 바뀌면 iframe이 새로 생긴다)
	$effect(() => {
		if (!currentFrame) return;
		const frame = currentFrame;
		const bridge = connectDeck(() => frame.contentWindow, {
			onIntent: (direction) => move(direction === 'next' ? next : prev) // 슬라이드 안에서 넘기려 한 것도 넘기기다
		});
		bridge.setMode('present');
		const unsubscribe = bridge.subscribe((s) => (mainDeck = s));
		currentBridge = bridge;
		// 위치를 읽지만 위치가 바뀔 때마다 다리를 다시 만들지는 않는다(위치는 아래 효과가 보낸다)
		untrack(() => current && bridge.goto(current));
		return () => {
			unsubscribe();
			bridge.stop();
			currentBridge = null;
			mainDeck = EMPTY_DECK;
		};
	});
	$effect(() => {
		if (!nextFrame) return;
		const frame = nextFrame;
		const bridge = connectDeck(() => frame.contentWindow);
		bridge.setMode('present');
		nextBridge = bridge;
		untrack(() => {
			const target = next ?? current;
			if (target) bridge.goto(target);
		});
		return () => {
			bridge.stop();
			nextBridge = null;
		};
	});

	onMount(() => {
		if (!data.classroom) return;
		classLive = connectClass(data.classroom.id, { role: 'professor' });
		const unsubscribe = classLive.subscribe((s) => (snapshot = s));
		const clock = setInterval(() => (now = Date.now()), 15_000);
		return () => {
			clearInterval(clock);
			unsubscribe();
			classLive?.stop();
			classLive = null;
		};
	});

	function openProjector() {
		if (data.classroom) window.open(`/courses/${data.classroom.id}/projector`, 'classroom-projector');
	}
</script>

<svelte:head><title>{heading} · 강의 상호작용 도구</title></svelte:head>
<svelte:window onkeydown={onKey} />

{#if data.notice || !data.classroom}
	<main class="mx-auto flex max-w-3xl flex-col gap-4 px-6 py-8">
		<ErrorNotice title={data.notice?.message ?? '찾을 수 없는 강좌입니다.'} hint="내 강좌 목록에서 다시 열어 주세요." />
		<a href="/courses" class="btn btn-outline self-start">내 강좌로 돌아가기</a>
	</main>
{:else}
	<header class="flex flex-wrap items-center justify-between gap-3 border-b border-border px-6 py-3">
		<div class="flex min-w-0 flex-col">
			<p class="text-sm text-muted-foreground">{data.classroom.name}</p>
			<h1 class="truncate text-xl font-bold">{liveState?.session.title ?? '수업 화면'}</h1>
		</div>
		<div class="flex flex-wrap items-center gap-3 text-sm">
			{#if elapsed}<span>경과 {elapsed}</span>{/if}
			{#if online !== null}<span class="flex items-center gap-1"><Icon name="group" />접속 {online}명</span>{/if}
			<button type="button" class="btn btn-outline" onclick={openProjector}>
				<Icon name="presentation" />프로젝터 화면 열기
			</button>
			<!-- 확인 창은 T021에서 붙인다 -->
			<button type="button" class="btn btn-outline text-destructive-strong">수업 종료</button>
		</div>
	</header>

	<main class="mx-auto flex max-w-6xl flex-col gap-4 px-6 py-6">
		{#if snapshot?.loadError && !liveState}
			<ErrorNotice title={snapshot.loadError} hint="잠시 뒤 자동으로 다시 불러옵니다." />
		{:else if !snapshot || (!liveState && !snapshot.loaded)}
			<p class="text-muted-foreground" role="status">수업을 불러오는 중…</p>
		{:else if !liveState}
			<p>진행 중인 수업이 없습니다.</p>
			<a class="btn btn-outline self-start" href="/courses/{data.classroom.id}/admin">관리 페이지로</a>
		{:else if liveState.session.status !== 'live'}
			<p>수업이 끝났습니다.</p>
			<a class="btn btn-outline self-start" href="/courses/{data.classroom.id}/admin">관리 페이지로</a>
		{:else}
			<section class="flex flex-col gap-4" aria-label="슬라이드">
				{#if !deck}
					<p class="rounded-md bg-foreground p-6 text-background">
						올린 슬라이드가 없습니다. 메시지·자료 보내기만 쓸 수 있습니다.
					</p>
				{:else if !deck.available}
					<ErrorNotice title="슬라이드를 열 수 없습니다. 묶음을 다시 올려 주세요." hint="관리 페이지에서 묶음을 다시 올릴 수 있습니다." />
				{:else}
					{#key deck.id}
						<div class="aspect-video w-full overflow-hidden rounded-md bg-foreground">
							<iframe bind:this={currentFrame} title="현재 슬라이드" src="/decks/{deck.id}/" class="h-full w-full border-0"></iframe>
						</div>
					{/key}
					<div class="flex flex-wrap items-center gap-3">
						<button
							type="button"
							class="btn btn-outline aria-disabled:opacity-50"
							disabled={atStart}
							aria-disabled={busy}
							aria-describedby={atStart ? 'at-start' : undefined}
							onclick={() => move(prev)}>이전</button
						>
						<button
							type="button"
							class="btn btn-default aria-disabled:opacity-50"
							disabled={atEnd}
							aria-disabled={busy}
							aria-describedby={atEnd ? 'at-end' : undefined}
							onclick={() => move(next)}>다음</button
						>
						<span class="text-sm text-muted-foreground" aria-live="polite">
							{current?.slide} / {total ?? '?'} 슬라이드{#if clicksTotal}{` · 단계 ${current?.click}/${clicksTotal}`}{/if}
						</span>
						{#if atStart}<span id="at-start" class="text-sm text-muted-foreground">첫 슬라이드입니다.</span>{/if}
						{#if atEnd}<span id="at-end" class="text-sm text-muted-foreground">마지막 슬라이드입니다.</span>{/if}
					</div>
					{#if moveError}<ErrorNotice title={moveError} />{/if}
					{#if countMismatch}
						<ErrorNotice title={countMismatch} hint="슬라이드 템플릿으로 다시 빌드해 올려 주세요." />
					{/if}
					<div class="grid gap-4 md:grid-cols-2">
						<section class="card" aria-labelledby="next-heading">
							<div class="card-header"><h2 id="next-heading" class="card-title">다음 슬라이드</h2></div>
							<div class="card-content flex flex-col gap-2">
								{#key deck.id}
									<!-- 보기용 사본이다. 화면 낭독기가 같은 슬라이드를 두 번 읽지 않게 숨긴다 -->
									<div class="aspect-video w-full overflow-hidden rounded-md bg-foreground" aria-hidden="true" inert>
										<iframe bind:this={nextFrame} title="다음 슬라이드 미리보기" src="/decks/{deck.id}/" class="pointer-events-none h-full w-full border-0" tabindex="-1"></iframe>
									</div>
								{/key}
							</div>
						</section>
						<section class="card" aria-labelledby="notes-heading">
							<div class="card-header"><h2 id="notes-heading" class="card-title">발표자 노트</h2></div>
							<div class="card-content">
								{#if notesError}
									<p class="text-sm text-muted-foreground">발표자 노트를 불러오지 못했습니다.</p>
								{:else if note === null}
									<p class="text-sm text-muted-foreground">노트를 불러오는 중…</p>
								{:else if note}
									<p class="whitespace-pre-line">{note}</p>
								{:else}
									<p class="text-sm text-muted-foreground">이 슬라이드에는 노트가 없습니다.</p>
								{/if}
							</div>
						</section>
					</div>
				{/if}
			</section>
		{/if}
	</main>
{/if}
