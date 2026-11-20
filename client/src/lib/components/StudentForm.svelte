<script lang="ts">
	import { ApiError, addStudent, type RosterEntry } from '#lib/api.js';
	import Icon from '#lib/components/Icon.svelte';

	let {
		classroomId,
		onAdded
	}: { classroomId: number; onAdded: (entry: Omit<RosterEntry, 'entered'>) => void | Promise<void> } = $props();

	type Field = 'student_no' | 'name' | 'email';
	const FIELDS: { key: Field; label: string; type: string; autocomplete: string }[] = [
		{ key: 'student_no', label: '학번', type: 'text', autocomplete: 'off' },
		{ key: 'name', label: '이름', type: 'text', autocomplete: 'off' },
		{ key: 'email', label: '이메일', type: 'email', autocomplete: 'off' }
	];

	let values = $state<Record<Field, string>>({ student_no: '', name: '', email: '' });
	let errors = $state<Partial<Record<Field, string>>>({});
	let formError = $state<string | null>(null);
	let saving = $state(false);
	const inputs: Partial<Record<Field, HTMLInputElement>> = {};

	async function submit(event: SubmitEvent) {
		event.preventDefault();
		if (saving) return;
		saving = true;
		errors = {};
		formError = null;
		try {
			const added = await addStudent(classroomId, { ...values });
			values = { student_no: '', name: '', email: '' };
			inputs.student_no?.focus(); // 다음 학생을 바로 쓸 수 있게
			await onAdded(added);
		} catch (e) {
			if (e instanceof ApiError && (e.field === 'student_no' || e.field === 'name' || e.field === 'email')) {
				errors = { [e.field]: e.message };
				inputs[e.field]?.focus();
			} else {
				formError =
					e instanceof ApiError ? e.message : '학생을 추가하지 못했습니다. 네트워크 연결을 확인하고 다시 시도해 주세요.';
			}
		} finally {
			saving = false;
		}
	}
</script>

<!-- novalidate: 브라우저의 기본 말풍선 대신 서버와 같은 검사의 한국어 안내를 입력 칸 옆에 보여 준다 -->
<form class="flex flex-col gap-4" onsubmit={submit} aria-label="학생 추가" novalidate>
	<div class="grid grid-cols-[repeat(auto-fit,minmax(min(13rem,100%),1fr))] gap-4">
		{#each FIELDS as f (f.key)}
			<div class="flex flex-col gap-2">
				<label for="student-{f.key}" class="label">{f.label}</label>
				<input
					id="student-{f.key}"
					type={f.type}
					class="input"
					autocomplete={f.autocomplete as 'off'}
					bind:this={inputs[f.key]}
					bind:value={values[f.key]}
					aria-invalid={errors[f.key] ? 'true' : undefined}
					aria-describedby={errors[f.key] ? `student-${f.key}-error` : undefined}
				/>
				{#if errors[f.key]}
					<p id="student-{f.key}-error" class="flex items-start gap-1.5 text-sm text-destructive-strong">
						<Icon name="warning-circle" class="mt-0.5 size-4 shrink-0" />{errors[f.key]}
					</p>
				{/if}
			</div>
		{/each}
	</div>
	{#if formError}
		<p role="alert" class="flex items-start gap-2 text-sm text-destructive-strong">
			<Icon name="warning-circle" class="mt-0.5 size-4 shrink-0" />{formError}
		</p>
	{/if}
	<div>
		<button type="submit" class="btn btn-default" disabled={saving}>
			{saving ? '추가하는 중…' : '학생 추가'}
		</button>
	</div>
</form>
