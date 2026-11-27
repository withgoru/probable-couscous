<script lang="ts">
	import { onMount, tick, untrack } from 'svelte';
	import { SvelteMap } from 'svelte/reactivity';
	import { fetchClassSessions, type ClassSessionSummary } from '#lib/api.js';
	import { connectClass, type ClassLive, type ClassSnapshot } from '#lib/classLive.js';
	import ErrorNotice from '#lib/components/ErrorNotice.svelte';
	import MaterialsPanel from '#lib/components/MaterialsPanel.svelte';
	import ReplayView from '#lib/components/ReplayView.svelte';
	import Icon from '#lib/components/Icon.svelte';
	import NicknameCard from '#lib/components/NicknameCard.svelte';
	import { connectDeck, type DeckBridge, type DeckSnapshot, type Direction, type Position } from '#lib/deckBridge.js';
	import { nextPosition, prevPosition } from '#lib/slides.js';
	import { dateTime } from '#lib/time.js';

	// 학생 수업 화면(002 AC23~AC25, AC29, AC30). 입장한 학생이 강좌 링크를 열면 보인다.
	// 진행 중인 회차가 없으면 대기 화면과 지난 회차 목록, 있으면 수업 화면이다. 수업이 시작되면 연결이 상태를 다시 받아
	// 새로 고치지 않아도 바뀐다. 발표자 노트는 받지도 보이지도 않는다(AC30).
	// 공개 묶음이면 따라가는 중에 학생이 넘기면(이전·다음, 슬라이드 밀기, ←·→) 따라가기가 풀리고 처음부터 끝까지
	// 직접 넘겨 본다. '교수 화면으로'를 눌러야 다시 따라간다(AC26, AC28). 비공개 묶음이면 따라가기만 한다(AC27).
	// 수업 중에 공개 여부가 바뀌면 바로 따른다(AC48). 자료 탭의 알림·복사는 T025.
	// 수업이 끝나면 새로 고치지 않아도 같은 회차의 다시 보기로 바뀌고(AC38), 대기 화면의 지난 회차도 다시 볼 수 있다(AC39)
	const EMPTY_DECK: DeckSnapshot = { ready: false, total: null, position: null, clicksTotal: null };
	const UNPUBLISHED = '교수님이 슬라이드를 비공개로 바꿨습니다. 교수 화면을 따라갑니다.';
	let {
		classroomId,
		title,
		nickname,
		onGone = () => {}
	}: {
		classroomId: number;
		title: string;
		nickname: string;
		/** 입장이 끝났다(명단에서 빠짐, 로그인 끊김, AC44). 서버가 알려 준 이유. 이유 없이 닫혔으면 null. */
		onGone?: (message: string | null) => void;
	} = $props();

	let snapshot = $state<ClassSnapshot | null>(null);
	let past = $state<ClassSessionSummary[] | null>(null);
	// 미리 볼 수 있는 회차: 공개 묶음이 있는 예정 회차(AC49). 서버가 회차 순서로 준다
	let previews = $state<ClassSessionSummary[]>([]);
	let pastFailed = $state(false);
	let pastRequest = 0; // 늦게 온 예전 응답이 새 목록을 덮지 않게 요청마다 번호를 붙인다
	let announcement = $state(''); // 화면이 바뀐 것을 화면 낭독기에 알린다(늘 있는 알림 자리)
	let lastSent = ''; // 슬라이드에 마지막으로 보낸 위치. 같으면 다시 보내지 않는다
	let frame = $state<HTMLIFrameElement | null>(null);
	let send: DeckBridge | null = null;
	let classLive: ClassLive | null = null;
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
	let mode = $state<'follow' | 'browse'>('follow');
	let mine = $state<Position | null>(null); // 직접 넘겨 보는 위치
	// 지나온 슬라이드의 단계 수. 이전 슬라이드로 돌아가면 그 슬라이드의 마지막 단계로 간다.
	// 바뀌면 이전 위치도 다시 계산하도록 반응형 Map이다. 회차나 묶음이 바뀌면 비운다
	const seenClicks = new SvelteMap<number, number>();
	let nextButton = $state<HTMLButtonElement | null>(null);
	let prevButton = $state<HTMLButtonElement | null>(null);
	let waitingHeading = $state<HTMLElement | null>(null);
	// 다시 보는 회차. 끝나서 이어 보면 보던 곳에서, 목록에서 열면 처음부터. 수업이 시작되면 비운다
	let replay = $state<{ id: number; start: 'first' | 'last'; ended: boolean; takeFocus: boolean; preview?: boolean } | null>(
		null
	);
	// 초점이 수업 화면 안에 있었는가. 수업이 끝나 그 화면이 사라지면 초점을 다시 보기 제목으로 옮긴다
	let liveBox = $state<HTMLElement | null>(null);
	let focusInLive = false;
	// 비공개로 바뀌어 직접 넘겨 보다 교수 화면으로 돌아왔다는 안내(AC48). 다시 공개되거나 회차가 바뀌면 지운다
	let unpublished = $state(false);
	let heading = $state<HTMLElement | null>(null);
	// 초점이 넘기기 버튼들에 있었는가. 비공개로 바뀌어 버튼이 사라지면 초점을 수업 제목으로 옮긴다
	let controls = $state<HTMLElement | null>(null);
	let focusInControls = false;

	const liveState = $derived(snapshot?.state?.session.status === 'live' ? snapshot.state : null);
	// 연결이 끊겨 다시 붙는 중(오류 동작 "학생 연결이 끊김", C12). 화면은 마지막 상태 그대로 둔다
	const offline = $derived(snapshot?.status === 'reconnecting');
	// 끊겼다가 다시 붙으면 알린다(끊김 안내가 사라지는 것만으로는 읽히지 않는다)
	let wasOffline = false;
	$effect(() => {
		const now = offline;
		const status = snapshot?.status;
		if (now) wasOffline = true;
		else if (wasOffline && status === 'live') {
			wasOffline = false;
			untrack(() => announce('다시 연결되었습니다.'));
		}
	});
	const deck = $derived(liveState?.deck ?? null);
	const current = $derived(liveState?.current ?? null);
	// 직접 넘겨 볼 수 있는가: 공개 묶음이고 열 수 있을 때만(AC26, AC27)
	const browsable = $derived(!!deck?.available && deck.public);
	const waiting = $derived(!!snapshot?.loaded && !liveState);
	// 화면에 보일 위치: 따라가는 중이면 교수 위치, 아니면 내가 넘긴 위치
	const shown = $derived(mode === 'follow' ? current : (mine ?? current));
	// 슬라이드가 그 위치를 그렸는가. 그리기 전에는 단계 수를 몰라 넘기지 않는다(단계를 건너뛰지 않게)
	const settled = $derived(
		!!shown && mainDeck.position?.slide === shown.slide && mainDeck.position.click === shown.click
	);
	const clicksTotal = $derived(settled ? mainDeck.clicksTotal : null);
	const total = $derived(mainDeck.total ?? deck?.slide_count ?? null);
	const next = $derived(shown ? nextPosition(shown, clicksTotal, total) : null);
	const prev = $derived(shown ? prevPosition(shown, seenClicks) : null);
	const atStart = $derived(settled && !prev);
	const atEnd = $derived(settled && !next);
	// 처음과 끝, 슬라이드가 따라오는 중에는 흐리게 한다. 진짜 disabled는 쓰지 않는다(초점을 잃지 않게)
	const canMove = $derived(browsable && settled);

	$effect(() => {
		if (mainDeck.position && mainDeck.clicksTotal !== null) seenClicks.set(mainDeck.position.slide, mainDeck.clicksTotal);
	});

	// 비공개로 바뀌면(AC48) 직접 넘겨 보던 학생은 교수 화면으로 돌아가 따라간다. 다시 공개되면 안내를 지운다.
	// 넘기기 버튼이 사라지므로, 초점이 거기 있었으면 수업 제목으로 옮긴다
	let seen: { session: number | null; browsable: boolean } | null = null;
	$effect(() => {
		const now = { session: liveState?.session.id ?? null, browsable };
		const before = seen;
		seen = now;
		// 처음 열 때나 다른 회차가 시작될 때는 바뀐 것이 아니다
		if (!before || before.session !== now.session || before.browsable === now.browsable) return;
		untrack(() => {
			if (now.browsable) {
				unpublished = false;
				return;
			}
			// 넘겨 볼 수 없게 됐다(비공개, 또는 묶음을 열 수 없음): 직접 넘겨 보던 학생은 교수 화면으로 돌아간다
			if (mode === 'browse') {
				backToProfessor();
				if (deck?.available && !deck.public) {
					unpublished = true;
					announce(UNPUBLISHED);
				}
			}
			if (focusInControls) {
				focusInControls = false;
				// 버튼이 사라져 초점을 잃었을 때만 옮긴다(다른 곳을 쓰는 중이면 빼앗지 않는다)
				tick().then(() => {
					if (!document.activeElement || document.activeElement === document.body) heading?.focus();
				});
			}
		});
	});

	// 다시 보는 회차의 묶음이 바뀌거나(올리기·지우기 → session.updated) 공개 여부가 바뀌면(deck.updated) 다시 받는다(AC41)
	let replayRefresh = $state(0);
	function onClassEvent(event: Record<string, unknown>) {
		// 기다리는 동안 교수가 예정 회차를 공개하거나 묶음을 바꾸면 목록(미리 볼 수 있는 회차)을 다시 받는다.
		// 다시 연결되거나(ready) resync가 오면 그 사이 놓친 바뀜이 있을 수 있어 다시 받는다
		if (waiting && ['deck.updated', 'session.updated', 'ready', 'resync'].includes(event.type as string))
			loadSessions(false);
		if (!replay) return;
		// 다시 연결되거나(ready) 서버가 놓친 알림 대신 resync를 보내면 놓친 것이 있을 수 있어 다시 받는다
		if (event.type === 'ready' || event.type === 'resync') replayRefresh += 1;
		else if (event.session_id === replay.id && (event.type === 'deck.updated' || event.type === 'session.updated'))
			replayRefresh += 1;
	}

	// 입장이 끝나면(goodbye 또는 4403으로 닫힘) 한 번만 알린다. 이 화면을 연 입장 페이지가 입장 화면으로 돌아간다(AC44)
	let goneTold = false;
	$effect(() => {
		if (snapshot?.status !== 'gone' || goneTold) return;
		goneTold = true;
		const message = snapshot.goodbye?.message ?? null;
		untrack(() => onGone(message));
	});

	/** 늘 있는 알림 자리에 쓴다. 같은 글이 다시 와도 바뀐 것으로 읽히게 비웠다가 쓴다. */
	function announce(text: string) {
		announcement = '';
		tick().then(() => (announcement = text));
	}

	function leftControls() {
		const box = controls;
		queueMicrotask(() => (focusInControls = !!box?.contains(document.activeElement)));
	}

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
		const ended = sessionId;
		sessionId = id;
		untrack(() => {
			// 보던 수업이 끝났다: 같은 회차를 보던 곳에서 이어 본다(AC38). 새 수업이 시작되면 그쪽이 먼저다
			replay = id === null && ended !== null ? { id: ended, start: 'last', ended: true, takeFocus: focusInLive } : null;
			focusInLive = false;
			if (replay) announce('수업이 끝났습니다.'); // 늘 있는 알림 자리라 화면 낭독기가 읽는다
			if (mode === 'browse') backToProfessor();
			seenClicks.clear();
			unpublished = false;
			focusInControls = false; // 화면이 사라질 때는 focusout이 오지 않는다
		});
	});

	/** 학생이 넘기려 했다. 공개 묶음의 처음·끝 안이면 따라가기를 풀고 한 단계 움직인다. 아니면 아무것도 하지 않는다. */
	function turn(direction: Direction) {
		if (!canMove) return;
		const target = direction === 'next' ? next : prev;
		if (!target) return; // 묶음의 처음·끝 밖: 움직이지 않고 따라가기도 그대로(AC26)
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

	function leftLive(event: FocusEvent) {
		const to = event.relatedTarget as Node | null;
		if (to && liveBox?.contains(to)) return;
		// 화면이 사라져 초점을 잃은 것이면 기억해 둔다. 학생이 다른 곳을 눌러 나간 것이면 잊는다
		const box = liveBox;
		queueMicrotask(() => {
			if (box?.isConnected) focusInLive = false;
		});
	}

	async function closeReplay() {
		replay = null;
		if (waiting) loadSessions(false); // 보는 동안 지워지거나 바뀐 회차가 목록에 남지 않게
		await tick();
		waitingHeading?.focus(); // 누른 버튼이 사라진다. 대기 화면의 제목으로 초점을 옮긴다
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
	// 위치가 그대로면(자료가 오는 등) 다시 보내지 않는다
	$effect(() => {
		const key = shown ? JSON.stringify(shown) : ''; // 먼저 읽어야 바뀔 때 다시 돈다
		if (!send || !shown || key === lastSent) return;
		lastSent = key;
		send.goto(shown);
	});

	// 대기에서 수업으로 바뀌면 알린다(AC23). 처음 열 때 이미 수업 중이면 알리지 않는다
	let wasWaiting = false;
	$effect(() => {
		if (waiting) wasWaiting = true;
		else if (liveState && wasWaiting) {
			wasWaiting = false;
			announce('수업이 시작되었습니다.');
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
			if (shown) bridge.goto(shown);
			lastSent = shown ? JSON.stringify(shown) : '';
		});
		return () => {
			unsubscribe();
			send = null;
			lastSent = '';
			mainDeck = EMPTY_DECK;
			bridge.stop();
		};
	});

	// 대기 화면이 될 때마다 회차 목록을 받는다(수업이 끝나 돌아와도 새 목록)
	$effect(() => {
		if (!waiting) return;
		untrack(() => loadSessions(true));
	});

	/** 회차 목록을 받는다. 처음이면 비우고, 다시 받을 때는 보던 목록을 그대로 둔다(깜빡이지 않게). */
	function loadSessions(fresh: boolean) {
		const request = ++pastRequest;
		if (fresh) {
			past = null;
			previews = [];
			pastFailed = false;
		}
		fetchClassSessions(classroomId)
			.then((list) => {
				if (request !== pastRequest) return;
				past = list.items.filter((s) => s.status === 'ended');
				previews = list.items.filter((s) => s.status === 'scheduled' && !!s.deck?.public && s.deck.available);
				pastFailed = false;
			})
			.catch(() => {
				// 보던 목록이 있으면 그대로 두고, 아직 아무것도 없으면 실패를 알린다(불러오는 중에 머물지 않게)
				if (request === pastRequest && past === null) pastFailed = true;
			});
	}

	onMount(() => {
		const live = connectClass(classroomId, { role: 'student', onEvent: onClassEvent });
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

<!-- 연결 끊김 안내: 위쪽에, 늘 있는 알림 자리라 화면 낭독기에도 읽힌다 -->
<!-- 비어 있을 때는 화면 흐름을 차지하지 않는다(자리는 늘 있어야 바뀔 때 읽힌다) -->
<div role="status" data-connection class={offline ? '' : 'sr-only'}>
	{#if offline}
		<p class="alert alert-warning"><Icon name="warning-circle" />연결이 끊겼습니다. 다시 연결하는 중…</p>
	{/if}
</div>
<p role="status" data-class-status class="sr-only">{announcement}</p>

{#if liveState}
	<div class="flex flex-col gap-4" bind:this={liveBox} onfocusin={() => (focusInLive = true)} onfocusout={leftLive}>
		<!-- 슬라이드(화면 폭, 16:9). 왼쪽 위에 아무것도 얹지 않는다 -->
		{#if !deck}
			<p class="rounded-md bg-foreground p-4 text-background">이번 수업은 슬라이드 없이 진행합니다. 자료를 확인하세요.</p>
		{:else if !deck.available}
			<p class="rounded-md bg-foreground p-4 text-background">슬라이드를 열 수 없습니다. 자료는 계속 볼 수 있습니다.</p>
		{:else}
			{#key deck.id}
				<!-- 화면 폭 전체(AC24): 입장 화면의 옆 여백을 넘어선다 -->
				<div class="relative -mx-6 aspect-video overflow-hidden bg-foreground">
					<iframe bind:this={frame} title="수업 슬라이드" src="/decks/{deck.id}/" class="h-full w-full border-0"></iframe>
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

		<!-- 수업 정보 줄 -->
		<div class="flex flex-col gap-0.5">
			<h1 bind:this={heading} tabindex="-1" class="text-lg leading-tight font-bold break-all outline-none">{title}</h1>
			<p class="text-sm">{liveState.session.title}</p>
			<p class="flex items-center gap-1 text-sm">
				<Icon name="user" class="size-4" /><span class="text-muted-foreground">내 닉네임</span>
				<span class="font-medium">{nickname}</span>
			</p>
		</div>

		<!-- 따라가기 줄(AC24, AC26~AC28). 상태 글은 바뀔 때 화면 낭독기에도 읽힌다 -->
		<div class="flex flex-col gap-2">
			<p role="status" class="flex items-center gap-2 text-sm font-medium">
				<Icon name="presentation" class="size-4" />
				{#if mode === 'browse'}
					직접 넘겨 보는 중 · 교수 화면은 {current?.slide}번 슬라이드입니다.
				{:else if deck?.available && !deck.public}
					교수 화면 따라가는 중 · 교수님이 슬라이드를 공개하면 직접 넘겨 볼 수 있습니다.
				{:else}
					교수 화면 따라가는 중
				{/if}
			</p>
			{#if unpublished}<p class="text-sm">{UNPUBLISHED}</p>{/if}
			{#if browsable}
				<div
					class="flex flex-wrap items-center gap-2"
					bind:this={controls}
					onfocusin={() => (focusInControls = true)}
					onfocusout={leftControls}
				>
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
						onclick={() => turn('next')}>다음</button
					>
					{#if mode === 'browse'}
						<button type="button" class="btn btn-default" onclick={() => backToProfessor(true)}>교수 화면으로</button>
					{/if}
				</div>
			{/if}
		</div>

		<!-- 자료(AC33~AC35). 회차가 바뀌면 새로 시작한다(새 회차의 항목을 '새 자료'로 세지 않게) -->
		{#key liveState.session.id}
			<MaterialsPanel items={liveState.items} />
		{/key}
	</div>
{:else if replay}
	{#key replay.id}
		<ReplayView
			{classroomId}
			sessionId={replay.id}
			start={replay.start}
			ended={replay.ended}
			takeFocus={replay.takeFocus}
			refresh={replayRefresh}
			preview={replay.preview}
			onAnnounce={announce}
			onBack={closeReplay}
		/>
	{/key}
{:else}
	<!-- 입장 완료와 대기(AC23, 001 AC28) -->
	<div class="flex flex-col gap-1">
		<span class="flex items-center gap-1.5 text-sm font-medium text-success-text">
			<Icon name="check" class="size-4" />입장했습니다
		</span>
		<h1 bind:this={waitingHeading} tabindex="-1" class="text-2xl leading-tight font-bold break-all outline-none">{title}</h1>
	</div>
	<NicknameCard {nickname} />
	{#if snapshot?.loadError && !snapshot.loaded}
		<ErrorNotice title={snapshot.loadError} hint="잠시 뒤 자동으로 다시 불러옵니다." />
	{:else if !waiting}
		<p class="text-sm text-muted-foreground">수업을 불러오는 중…</p>
	{:else}
		<p>지금 진행 중인 수업이 없습니다. 수업이 시작되면 이 화면이 바뀝니다.</p>
		{#if previews.length > 0}
			<!-- 미리 볼 수 있는 회차(AC49): 공개 묶음이 있는 예정 회차. 없으면 이 목록은 보이지 않는다 -->
			<section class="flex flex-col gap-2" aria-labelledby="preview-heading">
				<h2 id="preview-heading" class="text-base font-semibold">미리 볼 수 있는 회차</h2>
				<ul class="flex flex-col gap-2" aria-labelledby="preview-heading">
					{#each previews as s (s.id)}
						<li class="flex items-center justify-between gap-2 rounded-md border border-border p-3 text-sm">
							<span class="font-medium">{s.title}</span>
							<button
								type="button"
								class="btn btn-outline shrink-0"
								aria-label="{s.title} 미리 보기"
								onclick={() => (replay = { id: s.id, start: 'first', ended: false, takeFocus: true, preview: true })}
								>미리 보기</button
							>
						</li>
					{/each}
				</ul>
			</section>
		{/if}
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
							<span class="flex flex-col">
								<span class="font-medium">{s.title}</span>
								{#if s.ended_at}<span class="text-muted-foreground">{dateTime(s.ended_at)}</span>{/if}
							</span>
							<button
								type="button"
								class="btn btn-outline shrink-0"
								aria-label="{s.title} 다시 보기"
								onclick={() => (replay = { id: s.id, start: 'first', ended: false, takeFocus: true })}>다시 보기</button
							>
						</li>
					{/each}
				</ul>
			{/if}
		</section>
	{/if}
{/if}
