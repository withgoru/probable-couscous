<script lang="ts">
	import { ApiError, removeDeck, uploadDeck, type ClassSession } from '#lib/api.js';
	import ConfirmDialog from '#lib/components/ConfirmDialog.svelte';
	import ErrorNotice from '#lib/components/ErrorNotice.svelte';
	import Icon from '#lib/components/Icon.svelte';
	import { dateTime } from '#lib/time.js';

	// 선택한 회차의 '이 회차의 자료'(002 AC5~AC7): 슬라이드 묶음(zip) 올리기·바꾸기·지우기.
	// 거절 문구는 서버가 정한 것을 그대로 보인다(크기 상한도 서버 설정을 따른다)
	let {
		classroomId,
		session,
		onChanged
	}: {
		classroomId: number;
		session: ClassSession;
		onChanged: () => void | Promise<void>;
	} = $props();

	const LIVE_LOCKED = '수업 중에는 슬라이드를 바꿀 수 없습니다.';
	const deck = $derived(session.deck);
	const locked = $derived(session.status === 'live');

	let uploading = $state(false);
	let problem = $state<string | null>(null);
	let done = $state<string | null>(null);
	let confirming = $state(false);
	let fileInput = $state<HTMLInputElement | null>(null);

	async function upload(event: Event) {
		const input = event.currentTarget as HTMLInputElement;
		const file = input.files?.[0];
		if (!file) return; // 올리는 동안에는 입력 칸이 흐려져 다시 고를 수 없다
		uploading = true;
		problem = null;
		done = null;
		try {
			await uploadDeck(classroomId, session.id, file);
			await onChanged();
			done = `올렸습니다: ${file.name}`; // 파일 이름에 따라 조사가 달라져 이름을 뒤에 둔다
		} catch (e) {
			problem =
				e instanceof ApiError ? e.message : '슬라이드를 올리지 못했습니다. 네트워크 연결을 확인하고 다시 올려 주세요.';
		} finally {
			uploading = false;
			input.value = ''; // 같은 파일을 다시 골라도 다시 올린다
		}
	}

	async function remove() {
		try {
			await removeDeck(classroomId, session.id);
		} catch (e) {
			return e instanceof ApiError
				? { title: e.message }
				: { title: '슬라이드를 지우지 못했습니다.', hint: '네트워크 연결을 확인하고 다시 시도해 주세요.' };
		}
		done = null;
		await onChanged();
		return null;
	}
</script>

<section class="card" aria-labelledby="deck-heading">
	<div class="card-header flex flex-row items-center justify-between gap-2">
		<h2 id="deck-heading" class="card-title text-xl">이 회차의 자료</h2>
		{#if deck}
			<span class="badge badge-success"><Icon name="check" />업로드됨</span>
		{:else}
			<span class="badge badge-secondary">비어 있음</span>
		{/if}
	</div>
	<div class="card-content flex flex-col gap-4">
		{#if deck}
			<dl class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
				<dt class="text-muted-foreground">파일</dt>
				<dd class="font-medium break-all">{deck.original_name}</dd>
				<dt class="text-muted-foreground">올린 시각</dt>
				<dd>{dateTime(deck.uploaded_at)}</dd>
				<dt class="text-muted-foreground">분량</dt>
				<dd>슬라이드 {deck.slide_count}장</dd>
			</dl>
			{#if !deck.available}
				<ErrorNotice title="슬라이드를 열 수 없습니다. 묶음을 다시 올려 주세요." />
			{/if}
		{:else}
			<p class="text-sm text-muted-foreground">
				슬라이드 템플릿으로 빌드한 폴더(dist)를 zip으로 묶어 올려 주세요. 슬라이드 없이도 수업을 시작할 수 있습니다.
			</p>
		{/if}

		<div class="flex flex-col gap-2">
			<label for="deck-file" class="label">슬라이드 묶음(zip) {deck ? '바꾸기' : '올리기'}</label>
			<input
				id="deck-file"
				type="file"
				class="input"
				accept=".zip,application/zip"
				bind:this={fileInput}
				disabled={locked || uploading}
				aria-describedby={locked ? 'deck-locked' : undefined}
				onchange={upload}
			/>
			{#if locked}<p id="deck-locked" class="text-sm text-muted-foreground">{LIVE_LOCKED}</p>{/if}
			{#if uploading}<p class="text-sm" role="status">올리는 중…</p>{/if}
		</div>
		{#if problem}<ErrorNotice title={problem} />{/if}
		{#if done && !uploading}<p class="text-sm" role="status">{done}</p>{/if}
		{#if deck}
			<button
				type="button"
				class="btn btn-outline text-destructive-strong self-start"
				aria-label="슬라이드 지우기"
				disabled={locked || uploading}
				aria-describedby={locked ? 'deck-locked' : undefined}
				onclick={() => (confirming = true)}
			>
				지우기
			</button>
		{/if}
	</div>
</section>

{#if confirming && deck}
	<ConfirmDialog
		title="슬라이드 묶음을 지울까요?"
		description={`${deck.original_name} 파일을 지웁니다. 지운 뒤에도 다시 올릴 수 있습니다.`}
		confirmLabel="지우기"
		busyLabel="지우는 중…"
		onConfirm={remove}
		onDone={() => (confirming = false)}
		onCancel={() => (confirming = false)}
	/>
{/if}
