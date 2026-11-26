<script lang="ts">
	import { onMount, untrack } from 'svelte';
	import { connectClass, type ClassSnapshot } from '#lib/classLive.js';
	import ErrorNotice from '#lib/components/ErrorNotice.svelte';
	import Icon from '#lib/components/Icon.svelte';
	import { connectDeck } from '#lib/deckBridge.js';
	import type { PageProps } from './$types';

	// 프로젝터 화면(002 AC19~AC22). 학생 모두가 보는 화면이라 슬라이드만 16:9로 화면 가득 보인다.
	// 교수의 위치를 따라오기만 하고 직접 넘길 수 없다. 메뉴바는 레이아웃이 그리지 않는다.
	// 슬라이드 왼쪽 위에는 아무것도 얹지 않는다(슬라이드의 중요한 정보가 있다, screens.md). 오른쪽 사이드바 자리는
	// 003(출석코드)·004(채팅)가 채운다. 지금은 비워 둔다
	let { data }: PageProps = $props();

	let snapshot = $state<ClassSnapshot | null>(null);
	let frame = $state<HTMLIFrameElement | null>(null);
	let fullscreen = $state(false);
	let fullscreenError = $state(false);
	// 전체 화면 버튼은 마우스를 멈추면 숨는다. 브라우저의 F11로 전체 화면을 켜면 이 화면은 그것을 알 수 없어서,
	// 숨기지 않으면 버튼이 학생 모두가 보는 슬라이드 구석에 계속 남는다
	let idle = $state(false);
	let buttonFocused = $state(false);
	let idleTimer: ReturnType<typeof setTimeout> | null = null;
	let hadClass = $state(false); // 이 화면이 수업을 보이고 있었다(끝나면 "수업이 끝났습니다.")
	let goto: ((p: { slide: number; click: number }) => void) | null = null;
	const IDLE_MS = 3_000;

	const liveState = $derived(snapshot?.state ?? null);
	const deck = $derived(liveState?.deck ?? null);
	const current = $derived(liveState?.current ?? null);
	const offline = $derived(snapshot?.status === 'reconnecting');
	const heading = $derived(liveState ? `${liveState.session.title} · 프로젝터` : '프로젝터');
	const ended = $derived(liveState ? liveState.session.status !== 'live' : hadClass);
	const showButton = $derived(!fullscreen && (!idle || buttonFocused));

	$effect(() => {
		if (liveState?.session.status === 'live') hadClass = true;
	});

	function wake() {
		idle = false;
		if (idleTimer) clearTimeout(idleTimer);
		idleTimer = setTimeout(() => (idle = true), IDLE_MS);
	}

	// 교수의 위치(슬라이드와 단계)를 그대로 따라간다(AC20)
	$effect(() => {
		if (current) goto?.(current);
	});

	// iframe이 생기면 다리를 잇는다. 넘기려 한 방향(deck:intent)은 받지 않는다
	$effect(() => {
		if (!frame) return;
		const win = frame;
		const bridge = connectDeck(() => win.contentWindow);
		bridge.setMode('present');
		goto = (p) => bridge.goto(p);
		untrack(() => current && bridge.goto(current));
		return () => {
			goto = null;
			bridge.stop();
		};
	});

	async function toggleFullscreen() {
		fullscreenError = false;
		try {
			if (document.fullscreenElement) await document.exitFullscreen();
			else await document.documentElement.requestFullscreen();
		} catch {
			fullscreenError = true; // 막혔거나 이 브라우저에 없다
		}
	}

	function onKey(event: KeyboardEvent) {
		wake(); // 키보드로 다니는 사람에게도 버튼을 보인다
		// 넘기기 키는 받지 않는다. F만 전체 화면을 켜고 끈다(AC19). Ctrl+F(찾기)와 길게 누름은 받지 않는다
		if (event.key !== 'f' && event.key !== 'F') return;
		if (event.ctrlKey || event.metaKey || event.altKey || event.repeat) return;
		event.preventDefault();
		void toggleFullscreen();
	}

	onMount(() => {
		if (!data.classroom) return;
		const classLive = connectClass(data.classroom.id, { role: 'projector' });
		const unsubscribe = classLive.subscribe((s) => (snapshot = s));
		const onChange = () => (fullscreen = !!document.fullscreenElement);
		document.addEventListener('fullscreenchange', onChange);
		wake();
		return () => {
			if (idleTimer) clearTimeout(idleTimer);
			document.removeEventListener('fullscreenchange', onChange);
			unsubscribe();
			classLive.stop();
		};
	});
</script>

<svelte:head><title>{heading} · 강의 상호작용 도구</title></svelte:head>
<svelte:window onkeydown={onKey} onmousemove={wake} />

{#if data.notice || !data.classroom}
	<main class="mx-auto flex max-w-3xl flex-col gap-4 px-6 py-8">
		<ErrorNotice title={data.notice?.message ?? '찾을 수 없는 강좌입니다.'} hint="내 강좌 목록에서 다시 열어 주세요." />
		<a href="/courses" class="btn btn-outline self-start">내 강좌로 돌아가기</a>
	</main>
{:else}
	<!-- 어두운 면 위에 16:9 상자를 화면에 맞춰 놓는다(남는 곳은 검은 띠) -->
	<main class="relative flex h-dvh w-full items-center justify-center overflow-hidden bg-foreground text-background">
		<!-- 화면 낭독기용 제목. 슬라이드 위에 아무것도 얹지 않도록 보이지 않게 둔다 -->
		<h1 class="sr-only">{liveState?.session.title ?? '프로젝터'} · 프로젝터 화면</h1>
		{#if snapshot?.loadError && !liveState}
			<div class="text-foreground"><ErrorNotice title={snapshot.loadError} hint="잠시 뒤 자동으로 다시 불러옵니다." /></div>
		{:else if !snapshot || (!liveState && !snapshot.loaded)}
			<p role="status">수업을 불러오는 중…</p>
		{:else if !liveState || ended}
			<!-- 프로젝터는 진행 중인 회차를 따라가므로 수업이 끝나면 회차가 사라진다. 보던 수업이었으면 끝났다고 알린다 -->
			<p>{ended ? '수업이 끝났습니다.' : '진행 중인 수업이 없습니다.'}</p>
		{:else if !deck}
			<p class="px-8 text-center text-5xl font-bold" aria-hidden="true">{liveState.session.title}</p>
		{:else if !deck.available}
			<p>슬라이드를 열 수 없습니다.</p>
		{:else}
			{#key deck.id}
				<div class="aspect-video w-[min(100vw,calc(100dvh*16/9))]">
					<iframe
						bind:this={frame}
						title="슬라이드"
						src="/decks/{deck.id}/"
						tabindex="-1"
						class="pointer-events-none h-full w-full border-0"
					></iframe>
				</div>
			{/key}
		{/if}

		<!-- 오른쪽 아래 구석: 전체 화면 버튼(전체 화면이면 숨김)과, 끊겼을 때만 작은 표시(AC21) -->
		<div data-corner="bottom-right" class="absolute right-3 bottom-3 flex items-center gap-2 text-sm">
			<div role="status" data-connection-notice>
				{#if offline}
					<span class="flex items-center gap-1 rounded bg-background/90 px-2 py-1 text-foreground">
						<Icon name="warning-circle" class="size-4" />연결 끊김
					</span>
				{/if}
			</div>
			{#if fullscreenError}
				<p class="rounded bg-background/90 px-2 py-1 text-foreground">
					전체 화면을 켤 수 없습니다. 브라우저의 전체 화면(F11)을 써 주세요.
				</p>
			{/if}
			{#if showButton}
				<button
					type="button"
					class="btn btn-outline bg-background/90 text-foreground"
					onclick={toggleFullscreen}
					onfocus={() => (buttonFocused = true)}
					onblur={() => (buttonFocused = false)}
				>
					전체 화면
				</button>
			{/if}
		</div>
	</main>
{/if}
