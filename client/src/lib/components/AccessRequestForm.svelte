<script lang="ts">
	import { ApiError, requestAccess, type JoinAnswer } from '#lib/api.js';
	import Icon from '#lib/components/Icon.svelte';

	// 명단에 없는 이메일로 교수님께 입장 요청을 보낸다(AC39). 검사 규칙은 서버 한곳에 두고, 서버의 안내를 칸 옆에 보인다
	let {
		token,
		email,
		onAnswer,
		onClosed
	}: {
		token: string;
		email: string;
		onAnswer: (answer: JoinAnswer) => void;
		onClosed: (message: string) => void; // 그사이 링크가 폐기됐거나 강좌가 보관됐다
	} = $props();

	type Field = 'name' | 'student_no';
	const FIELDS: { key: Field; label: string; autocomplete: string; inputmode?: 'numeric' }[] = [
		{ key: 'name', label: '이름', autocomplete: 'name' },
		{ key: 'student_no', label: '학번', autocomplete: 'off', inputmode: 'numeric' }
	];

	let values = $state<Record<Field, string>>({ name: '', student_no: '' });
	let errors = $state<Partial<Record<Field, string>>>({});
	let formError = $state<string | null>(null);
	let sending = $state(false);
	const inputs: Partial<Record<Field, HTMLInputElement>> = {};

	async function submit(event: SubmitEvent) {
		event.preventDefault();
		if (sending) return;
		sending = true;
		errors = {};
		formError = null;
		try {
			onAnswer(await requestAccess(token, { email, name: values.name, student_no: values.student_no }));
		} catch (e) {
			if (e instanceof ApiError && (e.status === 404 || e.status === 403)) {
				onClosed(e.message);
			} else if (e instanceof ApiError && (e.field === 'name' || e.field === 'student_no')) {
				errors = { [e.field]: e.message };
				inputs[e.field]?.focus();
			} else {
				formError =
					e instanceof ApiError ? e.message : '요청을 보내지 못했습니다. 네트워크 연결을 확인하고 다시 시도해 주세요.';
			}
		} finally {
			sending = false;
		}
	}
</script>

<form class="flex flex-col gap-5" onsubmit={submit} novalidate aria-label="입장 요청">
	<div class="flex flex-col gap-1">
		<span class="text-sm text-muted-foreground">요청할 이메일</span>
		<span class="text-base font-medium break-all">{email}</span>
	</div>
	{#each FIELDS as f (f.key)}
		<div class="flex flex-col gap-2">
			<label for="request-{f.key}" class="label">{f.label}</label>
			<input
				id="request-{f.key}"
				type="text"
				class="input input-lg"
				autocomplete={f.autocomplete as 'off'}
				inputmode={f.inputmode}
				bind:this={inputs[f.key]}
				bind:value={values[f.key]}
				aria-invalid={errors[f.key] ? 'true' : undefined}
				aria-describedby={errors[f.key] ? `request-${f.key}-error` : undefined}
			/>
			{#if errors[f.key]}
				<p id="request-{f.key}-error" class="flex items-start gap-1.5 text-sm font-medium text-destructive-strong">
					<Icon name="warning-circle" class="mt-0.5 size-4 shrink-0" />{errors[f.key]}
				</p>
			{/if}
		</div>
	{/each}
	{#if formError}
		<p role="alert" class="flex items-start gap-2 text-sm font-medium text-destructive-strong">
			<Icon name="warning-circle" class="mt-0.5 size-4 shrink-0" />{formError}
		</p>
	{/if}
	<button type="submit" class="btn btn-default btn-lg w-full" disabled={sending}>
		{#if !sending}<Icon name="send" />{/if}{sending ? '보내는 중…' : '요청 보내기'}
	</button>
</form>
