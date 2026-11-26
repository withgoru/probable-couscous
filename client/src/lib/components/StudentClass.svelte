<script lang="ts">
	import { onMount, untrack } from 'svelte';
	import { fetchClassSessions, type ClassSessionSummary } from '#lib/api.js';
	import { connectClass, type ClassSnapshot } from '#lib/classLive.js';
	import ErrorNotice from '#lib/components/ErrorNotice.svelte';
	import Icon from '#lib/components/Icon.svelte';
	import NicknameCard from '#lib/components/NicknameCard.svelte';
	import { connectDeck } from '#lib/deckBridge.js';
	import { clockTime, dateTime } from '#lib/time.js';

	// 학생 수업 화면(002 AC23~AC25, AC29, AC30). 입장한 학생이 강좌 링크를 열면 보인다.
	// 진행 중인 회차가 없으면 대기 화면과 지난 회차 목록, 있으면 수업 화면이다. 수업이 시작되면 연결이 상태를 다시 받아
	// 새로 고치지 않아도 바뀐다. 발표자 노트는 받지도 보이지도 않는다(AC30).
	// 따라가기 풀기와 이전·다음은 T024, 자료 탭의 알림·복사는 T025, 끝남·다시 보기는 T026이 더한다
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
	let send: { goto: (p: { slide: number; click: number }) => void; setLimit: (p: { slide: number; click: number }) => void } | null = null;

	const liveState = $derived(snapshot?.state?.session.status === 'live' ? snapshot.state : null);
	const deck = $derived(liveState?.deck ?? null);
	const current = $derived(liveState?.current ?? null);
	const limit = $derived(liveState ? { slide: liveState.limit.slide, click: liveState.limit.click ?? ALL_CLICKS } : null);
	const items = $derived([...(liveState?.items ?? [])].sort((a, b) => b.id - a.id)); // 최근 것부터
	const waiting = $derived(!!snapshot?.loaded && !liveState);

	// 따라가는 중: 교수의 위치로 간다(AC25, AC29). 볼 수 있는 끝을 먼저 보낸다.
	// 애드온은 끝 뒤로 가는 지시를 끝에서 멈추므로, 새 슬라이드로 넘어갈 때 끝이 늦게 가면 따라가지 못한다.
	// 위치와 끝이 그대로면(자료가 오는 등) 다시 보내지 않는다
	$effect(() => {
		const key = limit && current ? JSON.stringify([limit, current]) : ''; // 먼저 읽어야 바뀔 때 다시 돈다
		if (!send || !limit || !current) return;
		if (key === lastSent) return;
		lastSent = key;
		send.setLimit(limit);
		send.goto(current);
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
		const bridge = connectDeck(() => win.contentWindow);
		bridge.setMode('follow');
		send = bridge;
		untrack(() => {
			if (limit) bridge.setLimit(limit);
			if (current) bridge.goto(current);
			lastSent = limit && current ? JSON.stringify([limit, current]) : '';
		});
		return () => {
			send = null;
			lastSent = '';
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
		const classLive = connectClass(classroomId, { role: 'student' });
		const unsubscribe = classLive.subscribe((s) => (snapshot = s));
		return () => {
			unsubscribe();
			classLive.stop();
		};
	});
</script>

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

		<!-- 따라가기 줄 -->
		<p class="flex items-center gap-2 text-sm font-medium"><Icon name="presentation" class="size-4" />교수 화면 따라가는 중</p>

		<!-- 자료 -->
		<section class="flex flex-col gap-2" aria-labelledby="materials-heading">
			<h2 id="materials-heading" class="text-base font-semibold">자료</h2>
			{#if items.length === 0}
				<p class="text-sm text-muted-foreground">아직 받은 자료가 없습니다.</p>
			{:else}
				<ul class="flex flex-col gap-2" aria-labelledby="materials-heading">
					{#each items as item (item.id)}
						<li class="flex flex-col gap-1 rounded-md border border-border p-3 text-sm">
							<span class="text-muted-foreground">{clockTime(item.created_at)}</span>
							{#if item.body}<p class="break-words whitespace-pre-wrap">{item.body}</p>{/if}
							{#if item.url}
								<a class="break-all underline" href={item.url} target="_blank" rel="noopener noreferrer">{item.url}</a>
							{/if}
						</li>
					{/each}
				</ul>
			{/if}
		</section>
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
