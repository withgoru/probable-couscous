<script lang="ts">
	import { goto } from '$app/navigation';
	import { ApiError, resumeSession, startSession, type ClassSession } from '#lib/api.js';
	import ConfirmDialog from '#lib/components/ConfirmDialog.svelte';
	import ErrorNotice from '#lib/components/ErrorNotice.svelte';
	import Icon from '#lib/components/Icon.svelte';

	// 선택한 회차의 수업 시작·이어서 하기·수업 화면으로(002 AC9~AC11, AC18, AC40).
	// 무엇이 보일지는 화면이 미리 정하지만(목록 기준), 그 사이 다른 화면에서 바뀌었으면 서버의 거절을 그대로 보인다
	let {
		classroomId,
		archived,
		session,
		sessions,
		onChanged,
		onSelect
	}: {
		classroomId: number;
		archived: boolean;
		session: ClassSession;
		sessions: ClassSession[];
		onChanged: () => void | Promise<void>;
		onSelect: (id: number) => void;
	} = $props();

	const ARCHIVED = '보관된 강좌는 수업을 시작할 수 없습니다.';
	const liveScreen = $derived(`/courses/${classroomId}/live`);
	const otherLive = $derived(sessions.find((s) => s.status === 'live' && s.id !== session.id) ?? null);
	const hasSlides = $derived(!!session.deck?.available);

	let busy = $state(false);
	let problem = $state<{ title: string; hint?: string; liveSessionId?: number } | null>(null);
	let confirmNoSlides = $state(false);

	async function run(action: 'start' | 'resume') {
		if (busy) return;
		busy = true;
		problem = null;
		try {
			await (action === 'start' ? startSession : resumeSession)(classroomId, session.id);
			await onChanged();
			await goto(liveScreen); // 시작하면 교수 수업 화면이 열린다(AC9)
		} catch (e) {
			if (e instanceof ApiError) {
				const live = e.data?.live_session_id;
				problem = { title: e.message, liveSessionId: typeof live === 'number' ? live : undefined };
				await onChanged(); // 다른 화면에서 바뀐 상태를 다시 불러온다
			} else {
				problem = { title: '수업을 시작하지 못했습니다.', hint: '네트워크 연결을 확인하고 다시 시도해 주세요.' };
			}
		} finally {
			busy = false;
		}
	}

	function start() {
		if (hasSlides) run('start');
		else confirmNoSlides = true; // 슬라이드 없이 시작하는지 먼저 묻는다(AC9)
	}
</script>

<section class="flex flex-col gap-3" aria-label="수업">
	{#if session.status === 'live'}
		<a class="btn btn-default btn-lg self-start" href={liveScreen}><Icon name="presentation" />수업 화면으로</a>
	{:else if archived}
		<p class="text-muted-foreground">{ARCHIVED}</p>
	{:else if otherLive}
		<div role="status" class="alert alert-info">
			<Icon name="info-circle" />
			<div class="flex flex-col gap-2">
				<div class="alert-title">{otherLive.title} 수업이 진행 중입니다. 먼저 끝내 주세요.</div>
				<button type="button" class="btn btn-outline self-start" onclick={() => onSelect(otherLive.id)}>
					{otherLive.title}로 가기
				</button>
			</div>
		</div>
	{:else if session.status === 'scheduled'}
		<button type="button" class="btn btn-default btn-lg self-start" disabled={busy} onclick={start}>
			{busy ? '시작하는 중…' : '수업 시작'}
		</button>
	{:else}
		<div class="flex flex-col gap-2">
			<button type="button" class="btn btn-default btn-lg self-start" disabled={busy} onclick={() => run('resume')}>
				{busy ? '시작하는 중…' : '이어서 수업하기'}
			</button>
			<p class="text-sm text-muted-foreground">마지막 위치에서 이어지고, 보낸 항목도 그대로입니다.</p>
		</div>
	{/if}

	{#if problem}
		<ErrorNotice title={problem.title} hint={problem.hint} />
		{#if problem.liveSessionId !== undefined}
			<button type="button" class="btn btn-outline self-start" onclick={() => onSelect(problem!.liveSessionId!)}>
				진행 중인 회차로 가기
			</button>
		{/if}
	{/if}
</section>

{#if confirmNoSlides}
	<ConfirmDialog
		title="슬라이드 없이 시작할까요?"
		description="메시지·자료 보내기만 쓸 수 있습니다."
		confirmLabel="슬라이드 없이 시작"
		busyLabel="시작하는 중…"
		tone="default"
		onConfirm={async () => {
			confirmNoSlides = false;
			await run('start');
			return null;
		}}
		onDone={() => (confirmNoSlides = false)}
		onCancel={() => (confirmNoSlides = false)}
	/>
{/if}
