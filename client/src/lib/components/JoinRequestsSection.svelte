<script lang="ts">
	import { ApiError, approveJoinRequest, rejectJoinRequest, type JoinRequest } from '#lib/api.js';
	import Icon from '#lib/components/Icon.svelte';
	import { clockTime } from '#lib/time.js';

	// 명단에 없는 학생이 보낸 입장 요청(AC40~AC42). 이름·학번·이메일·시각만 보이고 닉네임은 없다(C9)
	let {
		classroomId,
		requests,
		loadError = null,
		onDecided
	}: {
		classroomId: number;
		requests: JoinRequest[] | null; // null이면 아직 불러오기 전
		loadError?: string | null;
		onDecided: (outcome: 'approved' | 'rejected' | 'stale') => void; // 목록(승인이면 명단도)을 다시 불러온다
	} = $props();

	let busy = $state<number | null>(null);
	let done = $state<string | null>(null);
	let problem = $state<string | null>(null);

	const who = (r: JoinRequest) => `${r.name} (${r.student_no})`;

	async function decide(r: JoinRequest, action: 'approve' | 'reject') {
		if (busy !== null) return;
		busy = r.id;
		done = null;
		problem = null;
		try {
			if (action === 'approve') {
				await approveJoinRequest(classroomId, r.id);
				done = `${r.name} 학생을 수강생 명단에 추가했습니다. 학생은 이메일 인증부터 다시 하면 입장할 수 있습니다.`;
				onDecided('approved');
			} else {
				await rejectJoinRequest(classroomId, r.id);
				done = `${r.name} 학생의 요청을 거절했습니다.`;
				onDecided('rejected');
			}
		} catch (e) {
			if (e instanceof ApiError) {
				problem = `${r.name}: ${e.message}`;
				if (e.message === '이미 처리한 요청입니다.' || e.status === 404) onDecided('stale'); // 다른 창에서 처리했다
			} else {
				problem = `${r.name} 학생의 요청을 처리하지 못했습니다. 네트워크 연결을 확인하고 다시 시도해 주세요.`;
			}
		} finally {
			busy = null;
		}
	}
</script>

<section class="card gap-4" aria-labelledby="requests-title">
	<div class="card-header">
		<div class="flex flex-wrap items-baseline justify-between gap-2">
			<h2 id="requests-title" class="card-title text-xl">입장 요청</h2>
			{#if requests}<span class="badge badge-secondary">{requests.length}건</span>{/if}
		</div>
		<p class="card-description">수강생 명단에 없는 이메일로 들어온 학생입니다. 승인하면 명단에 추가됩니다.</p>
	</div>
	<div class="card-content flex flex-col gap-3">
		{#if done}
			<div role="status" class="alert alert-info">
				<Icon name="check" />
				<div class="alert-title leading-6 font-medium">{done}</div>
			</div>
		{/if}
		{#if problem}
			<p role="alert" class="flex items-start gap-2 text-sm font-medium text-destructive-strong">
				<Icon name="warning-circle" class="mt-0.5 size-4 shrink-0" />{problem}
			</p>
		{/if}
		{#if loadError}
			<p role="alert" class="flex items-start gap-2 text-sm font-medium text-destructive-strong">
				<Icon name="warning-circle" class="mt-0.5 size-4 shrink-0" />{loadError}
			</p>
		{:else if requests === null}
			<p class="text-sm text-muted-foreground">불러오는 중…</p>
		{:else if requests.length === 0}
			<p class="text-sm text-muted-foreground">처리할 입장 요청이 없습니다.</p>
		{:else}
			<ul class="flex flex-col divide-y">
				{#each requests as r (r.id)}
					<li class="flex flex-wrap items-center justify-between gap-3 py-3">
						<div class="flex min-w-0 flex-col gap-0.5">
							<span class="font-semibold">{r.name}</span>
							<span class="text-sm break-all text-muted-foreground">{r.student_no} · {r.email}</span>
							<span class="text-sm text-muted-foreground">
								요청 <time datetime={r.created_at}>{clockTime(r.created_at)}</time>
							</span>
						</div>
						<div class="flex gap-2">
							<button
								type="button"
								class="btn btn-default"
								aria-label="승인: {who(r)}"
								disabled={busy === r.id}
								onclick={() => decide(r, 'approve')}
							>
								승인
							</button>
							<button
								type="button"
								class="btn btn-outline text-destructive-strong"
								aria-label="거절: {who(r)}"
								disabled={busy === r.id}
								onclick={() => decide(r, 'reject')}
							>
								거절
							</button>
						</div>
					</li>
				{/each}
			</ul>
		{/if}
	</div>
</section>
