<script lang="ts">
	import { tick } from 'svelte';
	import { ApiError, removeStudent, revokeStudentLogin, type Roster, type RosterEntry } from '#lib/api.js';
	import ConfirmDialog from '#lib/components/ConfirmDialog.svelte';
	import CsvImport from '#lib/components/CsvImport.svelte';
	import Icon from '#lib/components/Icon.svelte';
	import StudentForm from '#lib/components/StudentForm.svelte';

	let {
		classroomId,
		roster,
		onChanged
	}: { classroomId: number; roster: Roster; onChanged: () => void | Promise<void> } = $props();

	let added = $state<string | null>(null);
	const full = $derived(roster.count >= roster.limit);

	async function onAdded(entry: Omit<RosterEntry, 'entered'>) {
		done = null;
		await onChanged();
		added = `${entry.name} 학생을 추가했습니다.`;
	}
	async function onImported() {
		added = null;
		await onChanged();
	}

	// --- 빼기와 로그인 끊기(AC19, AC20). 되돌리기 어려워서 확인 창을 거친다 ---
	type Action = 'remove' | 'revoke';
	let confirming = $state<{ entry: RosterEntry; action: Action; opener: HTMLElement } | null>(null);
	let tableRegion = $state<HTMLElement | null>(null);
	let done = $state<string | null>(null); // 표 위에 보이는 빼기·끊기 결과

	const label = (e: RosterEntry) => `${e.name} (${e.student_no})`;
	const TEXT = {
		remove: {
			title: (e: RosterEntry) => `${label(e)} 학생을 명단에서 뺄까요?`,
			description:
				'빼면 이 학생은 이 강좌에 입장할 수 없고 로그인 유지도 끝납니다. 다시 추가하면 이메일 인증을 거쳐 같은 닉네임으로 입장합니다.',
			confirm: '빼기',
			busy: '빼는 중…',
			done: (e: RosterEntry) => `${e.name} 학생을 명단에서 뺐습니다.`
		},
		revoke: {
			title: (e: RosterEntry) => `${label(e)} 학생의 로그인을 끊을까요?`,
			description: '이 학생의 모든 기기가 이 강좌에서 로그아웃됩니다. 다시 들어오려면 이메일 인증이 필요하고, 닉네임은 같습니다.',
			confirm: '로그인 끊기',
			busy: '끊는 중…',
			done: (e: RosterEntry) => `${e.name} 학생의 로그인을 끊었습니다.`
		}
	} as const;

	async function run(entry: RosterEntry, action: Action) {
		try {
			if (action === 'remove') await removeStudent(classroomId, entry.id);
			else await revokeStudentLogin(classroomId, entry.id);
			return null;
		} catch (e) {
			if (e instanceof ApiError) {
				if (e.status === 404) onChanged(); // 다른 창에서 이미 뺐다. 명단을 맞춘다
				return { title: e.message };
			}
			return { title: '처리하지 못했습니다.', hint: '네트워크 연결을 확인하고 다시 시도해 주세요.' };
		}
	}

	async function finish() {
		if (!confirming) return;
		const { entry, action, opener } = confirming;
		confirming = null;
		added = null;
		done = TEXT[action].done(entry);
		await onChanged();
		await tick();
		// 뺀 줄은 사라지므로 표 영역으로, 로그인 끊기는 그 버튼으로 포커스를 돌린다
		(action === 'remove' || !opener.isConnected ? tableRegion : opener)?.focus();
	}

	async function cancel() {
		const opener = confirming?.opener;
		confirming = null;
		await tick();
		opener?.focus();
	}
</script>

<section class="card gap-6" aria-labelledby="roster-title">
	<div class="card-header">
		<div class="flex flex-wrap items-baseline justify-between gap-2">
			<h2 id="roster-title" class="card-title text-xl">수강생 명단</h2>
			<p class="text-sm text-muted-foreground">{roster.count} / {roster.limit}명</p>
		</div>
		<p class="card-description">한 강좌에 {roster.limit}명까지 등록할 수 있습니다.</p>
	</div>

	{#if full}
		<div class="card-content">
			<div class="alert alert-warning">
				<Icon name="warning-circle" />
				<div class="alert-title">명단이 {roster.limit}명으로 가득 찼습니다.</div>
			</div>
		</div>
	{/if}

	<div class="card-content grid gap-8 lg:grid-cols-2">
		<div class="flex flex-col gap-3">
			<h3 class="font-semibold">학생 한 명 추가</h3>
			<StudentForm {classroomId} {onAdded} />
			{#if added}<p role="status" class="text-sm">{added}</p>{/if}
		</div>
		<div class="flex flex-col gap-3">
			<h3 class="font-semibold">CSV로 올리기</h3>
			<CsvImport {classroomId} {onImported} />
		</div>
	</div>

	<div class="card-content flex flex-col gap-3">
		{#if done}
			<div role="status" class="alert alert-info">
				<Icon name="check" />
				<div class="alert-title leading-6 font-medium">{done}</div>
			</div>
		{/if}
		{#if roster.entries.length === 0}
			<p class="text-sm text-muted-foreground">
				아직 등록된 학생이 없습니다. CSV로 올리거나 학생을 한 명씩 추가하세요.
			</p>
		{:else}
			<!-- 좁은 화면에서는 표만 가로로 스크롤한다. 키보드만으로 스크롤하려면 이 영역이 포커스를 받아야 한다(WCAG 2.1.1) -->
			<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
			<div
				bind:this={tableRegion}
				role="region"
				aria-label="수강생 명단 표"
				tabindex="0"
				class="overflow-x-auto rounded-md"
			>
				<table class="w-full min-w-[44rem] text-left text-sm">
					<thead class="border-b text-muted-foreground">
						<tr>
							<th scope="col" class="px-3 py-2 font-medium">학번</th>
							<th scope="col" class="px-3 py-2 font-medium">이름</th>
							<th scope="col" class="px-3 py-2 font-medium">이메일</th>
							<th scope="col" class="px-3 py-2 font-medium">입장 상태</th>
							<th scope="col" class="px-3 py-2 font-medium">관리</th>
						</tr>
					</thead>
					<tbody>
						{#each roster.entries as e (e.id)}
							<tr class="border-b last:border-0">
								<td class="px-3 py-2 tabular-nums">{e.student_no}</td>
								<td class="px-3 py-2">{e.name}</td>
								<td class="px-3 py-2 break-all">{e.email}</td>
								<!-- 상태는 색만이 아니라 글로 전달한다(C14) -->
								<td class="px-3 py-2">
									<span class="badge {e.entered ? 'badge-success' : 'badge-secondary'}">
										{e.entered ? '입장함' : '입장 전'}
									</span>
								</td>
								<td class="px-3 py-1">
									<div class="flex gap-2">
										{#if e.entered}
											<!-- 입장한 적 없는 학생은 끊을 로그인이 없다 -->
											<button
												type="button"
												class="btn btn-outline"
												aria-label="로그인 끊기: {label(e)}"
												onclick={(ev) => (confirming = { entry: e, action: 'revoke', opener: ev.currentTarget })}
											>
												로그인 끊기
											</button>
										{/if}
										<button
											type="button"
											class="btn btn-outline text-destructive-strong"
											aria-label="빼기: {label(e)}"
											onclick={(ev) => (confirming = { entry: e, action: 'remove', opener: ev.currentTarget })}
										>
											빼기
										</button>
									</div>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	</div>
	{#if confirming}
		{@const c = confirming}
		{#key `${c.action}-${c.entry.id}`}
			<ConfirmDialog
				title={TEXT[c.action].title(c.entry)}
				description={TEXT[c.action].description}
				confirmLabel={TEXT[c.action].confirm}
				busyLabel={TEXT[c.action].busy}
				onConfirm={() => run(c.entry, c.action)}
				onDone={finish}
				onCancel={cancel}
			/>
		{/key}
	{/if}
</section>
