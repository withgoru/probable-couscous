<script lang="ts">
	import type { Roster, RosterEntry } from '#lib/api.js';
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
		await onChanged();
		added = `${entry.name} 학생을 추가했습니다.`;
	}
	async function onImported() {
		added = null;
		await onChanged();
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

	<div class="card-content">
		{#if roster.entries.length === 0}
			<p class="text-sm text-muted-foreground">
				아직 등록된 학생이 없습니다. CSV로 올리거나 학생을 한 명씩 추가하세요.
			</p>
		{:else}
			<!-- 좁은 화면에서는 표만 가로로 스크롤한다. 키보드만으로 스크롤하려면 이 영역이 포커스를 받아야 한다(WCAG 2.1.1) -->
			<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
			<div role="region" aria-label="수강생 명단 표" tabindex="0" class="overflow-x-auto rounded-md">
				<table class="w-full min-w-[32rem] text-left text-sm">
					<thead class="border-b text-muted-foreground">
						<tr>
							<th scope="col" class="px-3 py-2 font-medium">학번</th>
							<th scope="col" class="px-3 py-2 font-medium">이름</th>
							<th scope="col" class="px-3 py-2 font-medium">이메일</th>
							<th scope="col" class="px-3 py-2 font-medium">입장 상태</th>
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
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	</div>
</section>
