<script lang="ts">
	import { onMount, tick, untrack } from 'svelte';
	import { goto } from '$app/navigation';
	import { ApiError, endSession, fetchDeckNotes, type DeckNotes } from '#lib/api.js';
	import { frameFocus } from '#lib/frameFocus.js';
	import { connectClass, type ClassLive, type ClassSnapshot, type GotoFailure } from '#lib/classLive.js';
	import ConfirmDialog from '#lib/components/ConfirmDialog.svelte';
	import ErrorNotice from '#lib/components/ErrorNotice.svelte';
	import Icon from '#lib/components/Icon.svelte';
	import SendPanel from '#lib/components/SendPanel.svelte';
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
	// 연결이 끊기면 넘겨도 반영되지 않으니 흐린다(누른 척하지 않는다, 오류 동작 "교수 연결이 끊김")
	const offline = $derived(snapshot?.status === 'reconnecting');
	// 기다리는 동안은 흐리게만 하고(초점을 잃지 않게) 처음과 끝에서만 누를 수 없게 한다
	const busy = $derived(moving || !settled || offline);
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
	const presence = $derived(snapshot?.presence ?? null);
	const online = $derived(presence ? presence.follow + presence.browse : null);
	// 끊긴 동안 현황은 마지막으로 받은 숫자다. 지금 숫자인 척하지 않는다
	const stale = $derived(offline ? ' (연결이 끊기기 전)' : '');
	const describe = (reason: string | false) =>
		[offline ? 'offline-notice' : null, reason || null].filter(Boolean).join(' ') || undefined;
	const heading = $derived(liveState ? `${liveState.session.title} · 수업 중` : '수업 화면');

	async function move(target: Position | null) {
		if (!target || busy || !classLive) return;
		moving = true;
		moveError = null;
		try {
			await classLive.goto(target); // 서버가 기록한 뒤 발행한 위치로 슬라이드가 움직인다
		} catch (e) {
			const failure = e as GotoFailure;
			// 끊겨서 실패했으면 끊김 안내가 이미 보인다. 다시 붙은 뒤에 남지 않게 따로 적지 않는다
			if (failure?.reason !== 'offline') moveError = failure?.message ?? '넘기지 못했습니다. 다시 눌러 주세요.';
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
		// 확인 창이 열린 동안에는 넘기지 않는다(발표용 리모컨은 화살표 키를 보낸다)
		if (endingSessionId !== null) return;
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
			alive = false;
			clearInterval(clock);
			unsubscribe();
			classLive?.stop();
			classLive = null;
		};
	});

	// 수업 종료(AC37): 확인한 뒤 회차를 끝내고 관리 페이지로 돌아간다.
	// 끝낼 회차는 확인 창을 연 때 정한다. 그 사이 다른 탭에서 회차가 바뀌어도 다른 회차를 끝내지 않는다
	let endingSessionId = $state<number | null>(null);
	let endButton = $state<HTMLButtonElement | null>(null);
	let alive = true; // 화면을 떠난 뒤 끝난 요청이 관리 페이지로 끌고 가지 않게

	async function endClass() {
		if (!data.classroom || endingSessionId === null) return null;
		try {
			await endSession(data.classroom.id, endingSessionId);
		} catch (e) {
			return e instanceof ApiError
				? { title: e.message }
				: { title: '수업을 끝내지 못했습니다.', hint: '네트워크 연결을 확인하고 다시 시도해 주세요.' };
		}
		if (alive) await goto(`/courses/${data.classroom.id}/admin`);
		return null;
	}

	async function cancelEnd() {
		endingSessionId = null;
		await tick();
		endButton?.focus(); // 확인 창을 연 버튼으로 초점을 돌려준다
	}

	function openProjector() {
		if (data.classroom) window.open(`/courses/${data.classroom.id}/projector`, 'classroom-projector');
	}
</script>

{#snippet presenceLine()}
	{#if presence}
		<!-- 숫자만 보인다. 누가 어느 쪽인지는 보이지 않는다(AC15, C7) -->
		<p class="flex items-center gap-2 text-sm">
			<Icon name="group" />따라가는 중 {presence.follow}명 · 직접 넘겨 보는 중 {presence.browse}명{stale}
		</p>
	{/if}
{/snippet}

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
			{#if online !== null}<span class="flex items-center gap-1"><Icon name="group" />접속 {online}명{stale}</span>{/if}
			<button type="button" class="btn btn-outline" onclick={openProjector}>
				<Icon name="presentation" />프로젝터 화면 열기
			</button>
			{#if liveState?.session.status === 'live'}
				<button
					type="button"
					class="btn btn-outline text-destructive-strong"
					bind:this={endButton}
					onclick={() => (endingSessionId = liveState?.session.id ?? null)}
				>
					수업 종료
				</button>
			{/if}
		</div>
	</header>

	<main class="mx-auto flex max-w-7xl flex-col gap-4 px-6 py-6">
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
			<!-- 자리는 늘 두고 글만 넣는다. 처음부터 있는 알림 자리여야 화면 낭독기가 바뀐 글을 읽는다 -->
			<div role="status" data-connection-notice>
				{#if offline}
					<div class="alert alert-warning">
						<Icon name="warning-circle" />
						<div class="flex flex-col gap-0.5">
							<div id="offline-notice" class="alert-title">연결이 끊겼습니다. 다시 연결하는 중…</div>
							<div class="alert-description">다시 연결되면 저장된 위치에서 이어집니다. 학생과 프로젝터는 마지막 슬라이드에 머뭅니다.</div>
						</div>
					</div>
				{/if}
			</div>
			<!-- 왼쪽은 슬라이드, 오른쪽은 메시지·자료 보내기(AC13, AC31, 목업 Main) -->
			<div class="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_24rem]">
			<section class="flex flex-col gap-4" aria-label="슬라이드">
				{#if !deck}
					<p class="rounded-md bg-foreground p-6 text-background">
						올린 슬라이드가 없습니다. 메시지·자료 보내기만 쓸 수 있습니다.
					</p>
					{@render presenceLine()}
				{:else if !deck.available}
					<ErrorNotice
						title="슬라이드를 열 수 없습니다. 메시지·자료 보내기는 계속 쓸 수 있습니다."
						hint="노트북의 원본으로 발표를 이어 가세요. 묶음은 관리 페이지에서 다시 올릴 수 있습니다."
					/>
					{@render presenceLine()}
				{:else}
					{#key deck.id}
						<div class="relative aspect-video w-full overflow-hidden rounded-md bg-foreground">
							<iframe bind:this={currentFrame} use:frameFocus title="현재 슬라이드" src="/decks/{deck.id}/" class="peer h-full w-full border-0"></iframe>
							<!-- 키보드로 슬라이드에 들어가면 보이는 링(primary 2px + 간격 2px, C14). iframe은 :focus가 걸리지 않아 표시로 그린다 -->
							<div data-frame-ring aria-hidden="true" class="pointer-events-none absolute inset-0 z-10 hidden rounded-[inherit] peer-data-[focused]:block" style="box-shadow: inset 0 0 0 2px var(--ring), inset 0 0 0 4px var(--background)"></div>
						</div>
					{/key}
					<div class="flex flex-wrap items-center gap-3">
						<button
							type="button"
							class="btn btn-outline aria-disabled:opacity-50"
							disabled={atStart}
							aria-disabled={busy}
							aria-describedby={describe(atStart && 'at-start')}
							onclick={() => move(prev)}>이전</button
						>
						<button
							type="button"
							class="btn btn-default aria-disabled:opacity-50"
							disabled={atEnd}
							aria-disabled={busy}
							aria-describedby={describe(atEnd && 'at-end')}
							onclick={() => move(next)}>다음</button
						>
						<span class="text-sm text-muted-foreground" aria-live="polite">
							{current?.slide} / {total ?? '?'} 슬라이드{#if clicksTotal}{` · 단계 ${current?.click}/${clicksTotal}`}{/if}
						</span>
						{#if atStart}<span id="at-start" class="text-sm text-muted-foreground">첫 슬라이드입니다.</span>{/if}
						{#if atEnd}<span id="at-end" class="text-sm text-muted-foreground">마지막 슬라이드입니다.</span>{/if}
					</div>
					{@render presenceLine()}
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
			<!-- 회차가 바뀌면 보내기 칸(쓰던 글, 열쇠, 방금 보낸 항목)을 새로 시작한다 -->
			{#key liveState.session.id}
				<SendPanel
					classroomId={data.classroom.id}
					sessionId={liveState.session.id}
					items={liveState.items}
					{offline}
					onChanged={() => classLive?.reload()}
				/>
			{/key}
			</div>
		{/if}
	</main>
{/if}

{#if endingSessionId !== null}
	<ConfirmDialog
		title="수업을 끝낼까요?"
		description={deck?.public
			? '학생은 슬라이드와 받은 자료를 계속 볼 수 있습니다.'
			: '학생은 받은 자료를 계속 볼 수 있습니다. 슬라이드는 공개해야 볼 수 있습니다.'}
		confirmLabel="수업 종료"
		busyLabel="끝내는 중…"
		onConfirm={endClass}
		onDone={() => (endingSessionId = null)}
		onCancel={cancelEnd}
	/>
{/if}
