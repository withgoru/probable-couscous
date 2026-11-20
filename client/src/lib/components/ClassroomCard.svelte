<script lang="ts">
	import type { Classroom } from '#lib/api.js';
	import Icon from '#lib/components/Icon.svelte';

	let { classroom, onClone }: { classroom: Classroom; onClone: (c: Classroom, opener: HTMLElement) => void } =
		$props();
	const archived = $derived(classroom.status === 'archived');
	const cloneLabel = $derived(archived ? '새 학기로 복제' : '분반 만들기');
	// 같은 이름의 버튼이 카드마다 있으니 어느 강좌의 것인지 이름에 넣는다. 보이는 글자로 시작해서 음성 입력도 맞는다
	const cloneName = $derived(
		`${cloneLabel}: ${classroom.name}${classroom.section_name ? ` (${classroom.section_name})` : ''}`
	);
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
	</div>
	<div class="card-footer">
		<a href="/courses/{classroom.id}/admin" class="btn btn-default flex-1">{archived ? '기록 보기' : '열기'}</a>
		<button
			type="button"
			class="btn btn-outline flex-1"
			aria-label={cloneName}
			onclick={(e) => onClone(classroom, e.currentTarget)}
		>
			{cloneLabel}
		</button>
	</div>
</li>
