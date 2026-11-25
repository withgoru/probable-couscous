<script lang="ts">
	import type { Classroom } from '#lib/api.js';
	import Icon from '#lib/components/Icon.svelte';

	type Opener = (c: Classroom, opener: HTMLElement) => void;
	let { classroom, onClone, onArchive }: { classroom: Classroom; onClone: Opener; onArchive: Opener } = $props();
	const archived = $derived(classroom.status === 'archived');
	const cloneLabel = $derived(archived ? '새 학기로 복제' : '분반 만들기');
	// 같은 이름의 버튼이 카드마다 있으니 어느 강좌의 것인지 이름에 넣는다. 보이는 글자로 시작해서 음성 입력도 맞는다
	const label = $derived(`${classroom.name}${classroom.section_name ? ` (${classroom.section_name})` : ''}`);
	const cloneName = $derived(`${cloneLabel}: ${label}`);
</script>

<li class="card gap-4">
	<div class="card-header">
		<div class="flex items-start justify-between gap-3">
			<div class="flex min-w-0 flex-col gap-1">
				<h2 class="card-title text-lg leading-tight">{classroom.name}</h2>
				<p class="card-description">{classroom.section_name ?? '분반 없음'}</p>
			</div>
			<!-- 상태는 색만이 아니라 문구로 전달한다(C14) -->
			<span class="badge {archived ? 'badge-secondary' : 'badge-success'}">{archived ? '보관됨' : '진행 중'}</span>
		</div>
	</div>
	<div class="card-content flex flex-col gap-1.5 text-sm text-muted-foreground">
		<span class="flex items-center gap-2"><Icon name="group" class="size-4" />수강생 {classroom.student_count}명</span>
		<!-- 한 번이라도 시작한 회차 수(002 AC8) -->
		<span class="flex items-center gap-2"><Icon name="presentation" class="size-4" />진행 회차 {classroom.session_count}</span>
	</div>
	<div class="card-footer flex-wrap">
		<a href="/courses/{classroom.id}/admin" class="btn btn-default flex-1">{archived ? '기록 보기' : '열기'}</a>
		<button
			type="button"
			class="btn btn-outline flex-1"
			aria-label={cloneName}
			onclick={(e) => onClone(classroom, e.currentTarget)}
		>
			{cloneLabel}
		</button>
		{#if !archived}
			<!-- 되돌릴 수 없어서 바로 보관하지 않고 확인 창을 연다 -->
			<button
				type="button"
				class="btn btn-ghost text-destructive-strong"
				aria-label="보관: {label}"
				onclick={(e) => onArchive(classroom, e.currentTarget)}
			>
				보관
			</button>
		{/if}
	</div>
</li>
