<script lang="ts">
	import { tick } from 'svelte';
	import { ApiError, retractItem, sendItem, type SentItem } from '#lib/api.js';
	import type { LiveItem } from '#lib/classLive.js';
	import ConfirmDialog from '#lib/components/ConfirmDialog.svelte';
	import ErrorNotice from '#lib/components/ErrorNotice.svelte';
	import Icon from '#lib/components/Icon.svelte';
	import { clockTime } from '#lib/time.js';

	// 교수 수업 화면의 메시지·자료 보내기(002 AC31, AC32, AC35, AC36, 오류 동작 "보내기 실패").
	// 목록은 수업 상태(items)가 진실이다. 방금 보낸 항목은 상태가 다시 오기 전에도 바로 목록 맨 위에 보인다
	let {
		classroomId,
		sessionId,
		items,
		offline,
		onChanged
	}: {
		classroomId: number;
		sessionId: number;
		items: LiveItem[];
		offline: boolean;
		onChanged: () => void;
	} = $props();

	const TEXT_MAX = 2000; // 서버와 같다
	const LINK = /^https?:\/\/\S+$/i; // 서버와 같은 규칙: 전체가 http(s):// 뒤 공백 없는 글자
	const BAD_LINK = '링크는 http:// 또는 https://로 시작해야 합니다.';
	const FAILED = '보내지 못했습니다. 연결을 확인하고 다시 보내 주세요.';

	let body = $state('');
	let url = $state('');
	let sending = $state(false);
	let fieldError = $state<{ field: 'body' | 'url'; message: string } | null>(null);
	let problem = $state<string | null>(null);
	let sent = $state<SentItem[]>([]); // 방금 보냈고 상태에는 아직 없는 항목
	let retracted = $state<Record<number, string>>({}); // 방금 거둔 항목(상태가 다시 오기 전에도 거둔 항목으로 보인다)
	let retracting = $state<LiveItem | null>(null);
	let announcement = $state('');
	let bodyField = $state<HTMLTextAreaElement | null>(null);
	let urlField = $state<HTMLInputElement | null>(null);
	// 같은 글을 다시 보내면(실패 뒤 다시 누름) 같은 열쇠로 보내 서버가 한 번만 저장한다.
	// 보내고 나거나 글을 고치면 새 열쇠다. 고친 글을 같은 열쇠로 보내면 서버가 예전에 저장한 글을 돌려주기 때문이다
	let clientKey = newKey();
	let attempted: string | null = null;

	function newKey(): string {
		// crypto.randomUUID는 보안 연결(https, localhost)에서만 있다. getRandomValues는 어디서나 된다
		const bytes = crypto.getRandomValues(new Uint8Array(16));
		return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
	}

	const empty = $derived(body.trim() === '' && url.trim() === '');
	const busy = $derived(sending || offline);
	const list = $derived.by(() => {
		const known = new Set(items.map((i) => i.id));
		return [...items, ...sent.filter((i) => !known.has(i.id))]
			.map((i) => (retracted[i.id] && !i.retracted_at ? { ...i, retracted_at: retracted[i.id] } : i))
			.sort((a, b) => b.id - a.id); // 최근 것부터
	});
	const describedBy = (...ids: (string | false | null)[]) => ids.filter(Boolean).join(' ') || undefined;

	async function submit(event: SubmitEvent) {
		event.preventDefault();
		if (empty || busy) return;
		const link = url.trim();
		if (link && !LINK.test(link)) {
			await showFieldError({ field: 'url', message: BAD_LINK });
			return;
		}
		const content = JSON.stringify([body, link]);
		if (attempted !== null && attempted !== content) clientKey = newKey(); // 고친 글은 새 메시지다
		attempted = content;
		sending = true;
		fieldError = null;
		problem = null;
		announcement = '';
		try {
			const saved = await sendItem(classroomId, sessionId, {
				body: body.trim() === '' ? null : body, // 글은 쓴 그대로(줄바꿈, 들여쓰기)
				url: link || null,
				client_key: clientKey
			});
			sent = [...sent, saved];
			body = '';
			url = '';
			clientKey = newKey();
			attempted = null;
			announcement = '학생에게 보냈습니다.';
			onChanged();
		} catch (e) {
			if (e instanceof ApiError && (e.field === 'body' || e.field === 'url')) {
				sending = false;
				await showFieldError({ field: e.field, message: e.message });
			} else if (e instanceof ApiError && e.status < 500) {
				problem = e.message;
			} else {
				problem = FAILED; // 글은 칸에 그대로 남는다
			}
		} finally {
			sending = false;
		}
	}

	/** 칸 옆에 이유를 보이고 그 칸으로 초점을 옮긴다. 화면 낭독기가 칸과 함께 이유를 읽는다. */
	async function showFieldError(error: { field: 'body' | 'url'; message: string }) {
		fieldError = error;
		await tick();
		(error.field === 'body' ? bodyField : urlField)?.focus();
	}

	async function retract() {
		if (!retracting) return null;
		let done: SentItem;
		try {
			done = await retractItem(classroomId, sessionId, retracting.id);
		} catch (e) {
			return e instanceof ApiError
				? { title: e.message }
				: { title: '거두지 못했습니다.', hint: '네트워크 연결을 확인하고 다시 시도해 주세요.' };
		}
		retracted = { ...retracted, [done.id]: done.retracted_at ?? new Date().toISOString() };
		onChanged();
		return null;
	}

	// 거두기 버튼의 읽는 이름. 글 전체(최대 2000자)를 읽지 않게 앞부분만 쓴다
	const LABEL_MAX = 40;
	const label = (item: LiveItem) => {
		const text = item.body?.trim() || item.url || '';
		return text.length > LABEL_MAX ? `${text.slice(0, LABEL_MAX)}…` : text;
	};
</script>

<section class="card" aria-labelledby="send-heading">
	<div class="card-header">
		<h2 id="send-heading" class="card-title text-xl">메시지·자료 보내기</h2>
	</div>
	<div class="card-content flex flex-col gap-4">
		<form class="flex flex-col gap-3" onsubmit={submit} novalidate>
			<div class="flex flex-col gap-2">
				<label for="send-body" class="label">글</label>
				<textarea
					id="send-body"
					class="input min-h-28 py-2"
					bind:this={bodyField}
					bind:value={body}
					readonly={sending}
					maxlength={TEXT_MAX}
					aria-invalid={fieldError?.field === 'body' || undefined}
					aria-describedby={describedBy(fieldError?.field === 'body' && 'send-body-error')}
				></textarea>
				{#if fieldError?.field === 'body'}<p id="send-body-error" class="text-sm text-destructive-strong">{fieldError.message}</p>{/if}
			</div>
			<div class="flex flex-col gap-2">
				<label for="send-url" class="label">링크(선택)</label>
				<input
					id="send-url"
					type="url"
					class="input"
					bind:this={urlField}
					bind:value={url}
					readonly={sending}
					placeholder="https://"
					aria-invalid={fieldError?.field === 'url' || undefined}
					aria-describedby={describedBy(fieldError?.field === 'url' && 'send-url-error')}
				/>
				{#if fieldError?.field === 'url'}<p id="send-url-error" class="text-sm text-destructive-strong">{fieldError.message}</p>{/if}
			</div>
			{#if problem}<ErrorNotice title={problem} />{/if}
			<button
				type="submit"
				class="btn btn-default aria-disabled:opacity-50"
				disabled={empty}
				aria-disabled={busy}
				aria-describedby={describedBy(empty && 'send-empty', offline && 'offline-notice')}
			>
				<Icon name="send" />{sending ? '보내는 중…' : '학생에게 보내기'}
			</button>
			{#if empty}<p id="send-empty" class="text-sm text-muted-foreground">글이나 링크를 입력해 주세요.</p>{/if}
			<!-- 늘 있는 알림 자리. 보내면 글이 칸에서 사라지므로 보냈다는 것을 읽어 준다 -->
			<p role="status" data-send-status class="text-sm">{announcement}</p>
		</form>

		<div class="flex flex-col gap-2">
			<h3 id="sent-heading" class="text-sm font-semibold">보낸 항목</h3>
			{#if list.length === 0}
				<p class="text-sm text-muted-foreground">아직 보낸 항목이 없습니다.</p>
			{:else}
				<ul class="flex flex-col gap-2" aria-labelledby="sent-heading">
					{#each list as item (item.id)}
						<li class="flex flex-col gap-1 rounded-md border border-border p-3 text-sm {item.retracted_at ? 'text-muted-foreground' : ''}">
							<div class="flex items-center justify-between gap-2">
								<span class="text-muted-foreground">{clockTime(item.created_at)}</span>
								{#if item.retracted_at}
									<span class="badge badge-secondary"><Icon name="eye-closed" />거둔 항목 · 학생에게 보이지 않습니다.</span>
								{:else}
									<button
										type="button"
										class="btn btn-ghost text-destructive-strong"
										aria-label={`거두기: ${label(item)}`}
										onclick={() => (retracting = item)}>거두기</button
									>
								{/if}
							</div>
							{#if item.body}<p class="whitespace-pre-wrap break-words">{item.body}</p>{/if}
							{#if item.url}
								<a class="break-all underline" href={item.url} target="_blank" rel="noopener noreferrer">{item.url}</a>
							{/if}
						</li>
					{/each}
				</ul>
			{/if}
			<p class="text-sm text-muted-foreground">보낸 항목은 수업이 끝난 뒤 공개할 목록으로 정리됩니다.</p>
		</div>
	</div>
</section>

{#if retracting}
	<ConfirmDialog
		title="이 항목을 거둘까요?"
		description="학생 화면에서 바로 사라지고 되살릴 수 없습니다. 이 목록에는 거둔 항목으로 남습니다."
		confirmLabel="거두기"
		busyLabel="거두는 중…"
		onConfirm={retract}
		onDone={() => (retracting = null)}
		onCancel={() => (retracting = null)}
	/>
{/if}
