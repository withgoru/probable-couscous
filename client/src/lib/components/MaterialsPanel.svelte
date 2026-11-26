<script lang="ts">
	import { onMount, untrack } from 'svelte';
	import type { LiveItem } from '#lib/classLive.js';
	import Icon from '#lib/components/Icon.svelte';
	import { clockTime } from '#lib/time.js';

	// 학생 수업 화면의 '자료'(002 AC33~AC35). 교수가 보낸 글과 링크가 최근 것부터 보인다.
	// 거둔 항목은 수업 연결이 목록에서 빼므로 여기서도 사라진다.
	let { items }: { items: LiveItem[] } = $props();

	const ARRIVED = '교수님이 자료를 보냈습니다.';
	const ARRIVED_MS = 4_000; // 몇 초간 보인다
	const COPIED_MS = 3_000;
	const LABEL_MAX = 30; // 복사 버튼의 읽는 이름에 쓰는 앞부분 길이

	let section = $state<HTMLElement | null>(null);
	// 읽었다 = 학생이 이 화면을 보고 있고(다른 앱·탭이 아님) 자료 구역이 화면에 들어와 있다.
	// 화면에 들어왔는지 알 수 없는 브라우저에서는 보인다고 본다(수가 쌓여 남지 않게)
	let intersecting = $state(typeof IntersectionObserver === 'undefined');
	let pageVisible = $state(typeof document === 'undefined' || document.visibilityState !== 'hidden');
	const inView = $derived(intersecting && pageVisible);
	let arrival = $state('');
	let arrivalTimer: ReturnType<typeof setTimeout> | null = null;
	let copied = $state<{ id: number; ok: boolean } | null>(null);
	let copiedTimer: ReturnType<typeof setTimeout> | null = null;
	// 이미 본(알린) 항목과 아직 읽지 않은 항목
	let known: Set<number> | null = null;
	let unread = $state<number[]>([]);

	const list = $derived([...items].sort((a, b) => b.id - a.id)); // 최근 것부터
	const copyMessage = $derived(
		copied ? (copied.ok ? '복사했습니다.' : '복사하지 못했습니다. 글을 선택해 직접 복사해 주세요.') : ''
	);
	// 거둔 항목은 읽지 않은 수에서도 빠진다
	const unreadCount = $derived(unread.filter((id) => items.some((i) => i.id === id)).length);

	$effect(() => {
		if (inView) untrack(() => (unread = []));
	});

	// 새 항목: 알리고, 자료가 보이지 않을 때 왔으면 읽지 않은 것으로 센다. 처음 열 때 있던 항목은 이미 본 것이다
	$effect(() => {
		const ids = items.map((i) => i.id);
		untrack(() => {
			if (known === null) {
				known = new Set(ids);
				return;
			}
			const fresh = ids.filter((id) => !known!.has(id));
			for (const id of ids) known.add(id);
			if (fresh.length === 0) return;
			announce();
			if (!inView) unread = [...unread, ...fresh];
		});
	});

	function announce() {
		arrival = ARRIVED;
		if (arrivalTimer) clearTimeout(arrivalTimer);
		arrivalTimer = setTimeout(() => (arrival = ''), ARRIVED_MS);
	}

	async function copy(item: LiveItem) {
		if (!item.body) return;
		let ok = true;
		try {
			await navigator.clipboard.writeText(item.body); // 글 전체를 쓴 그대로
		} catch {
			ok = false; // 복사했다고 거짓으로 알리지 않는다
		}
		copied = { id: item.id, ok };
		if (copiedTimer) clearTimeout(copiedTimer);
		if (ok) copiedTimer = setTimeout(() => (copied = null), COPIED_MS);
	}

	function shortLabel(text: string): string {
		const flat = text.trim().replace(/\s+/g, ' ');
		return flat.length > LABEL_MAX ? `${flat.slice(0, LABEL_MAX)}…` : flat;
	}

	onMount(() => {
		// 자료 구역이 화면에 들어오면 읽은 것이 된다(스크롤해 내려와 보면)
		let observer: IntersectionObserver | null = null;
		if (section && typeof IntersectionObserver !== 'undefined') {
			observer = new IntersectionObserver((entries) => (intersecting = entries.some((e) => e.isIntersecting)));
			observer.observe(section);
		}
		const onVisibility = () => (pageVisible = document.visibilityState !== 'hidden');
		document.addEventListener('visibilitychange', onVisibility);
		return () => {
			document.removeEventListener('visibilitychange', onVisibility);
			observer?.disconnect();
			if (arrivalTimer) clearTimeout(arrivalTimer);
			if (copiedTimer) clearTimeout(copiedTimer);
		};
	});
</script>

<!-- 아래 여백: 도착 알림이 마지막 항목을 가리지 않게 -->
<section bind:this={section} class="flex flex-col gap-2 pb-16" aria-labelledby="materials-heading">
	<!-- 읽지 않은 수는 제목 안에 둔다(제목으로 옮겨 다닐 때 함께 읽힌다) -->
	<h2 id="materials-heading" class="flex items-center gap-2 text-base font-semibold">
		자료
		{#if unreadCount > 0}<span class="badge badge-info">새 자료 {unreadCount}</span>{/if}
	</h2>
	{#if list.length === 0}
		<p class="text-sm text-muted-foreground">아직 받은 자료가 없습니다.</p>
	{:else}
		<ul class="flex flex-col gap-2" aria-label="자료">
			{#each list as item (item.id)}
				<li class="flex flex-col gap-2 rounded-md border border-border p-3 text-sm">
					<div class="flex items-center justify-between gap-2">
						<span class="text-muted-foreground">{clockTime(item.created_at)}</span>
						{#if item.body}
							<button
								type="button"
								class="btn btn-outline"
								aria-label={`복사: ${shortLabel(item.body)}`}
								onclick={() => copy(item)}><Icon name="copy" />복사</button
							>
						{/if}
					</div>
					{#if item.body}<p class="break-words whitespace-pre-wrap">{item.body}</p>{/if}
					{#if item.url}
						<a class="break-all underline" href={item.url} target="_blank" rel="noopener noreferrer">
							{item.url}<span class="sr-only"> (새 탭에서 열림)</span>
						</a>
					{/if}
					{#if copied?.id === item.id}<p class="text-sm">{copyMessage}</p>{/if}
				</li>
			{/each}
		</ul>
	{/if}
</section>

<!-- 복사 결과를 읽어 주는 자리(목록 전체에 하나). 글은 그 항목 안에 보인다 -->
<p role="status" data-copy-status class="sr-only">{copyMessage}</p>

<!-- 도착 알림: 화면 아래에 몇 초 보이고 화면 낭독기에도 읽힌다. 자리는 늘 있고 글만 바뀐다 -->
<div
	role="status"
	aria-live="polite"
	data-arrival
	class="pointer-events-none fixed inset-x-0 bottom-4 z-40 flex justify-center px-4"
>
	{#if arrival}
		<p class="rounded-md bg-foreground px-4 py-2 text-sm text-background shadow">{arrival}</p>
	{/if}
</div>
