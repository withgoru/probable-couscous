<script lang="ts">
	import { onMount } from 'svelte';
	import { ApiError, type Classroom } from '#lib/api.js';
	import Icon from '#lib/components/Icon.svelte';

	// 새로 만들기와 복제가 같은 폼을 쓴다. 무엇을 보낼지(save)와 처음 채울 값은 부르는 쪽이 정한다
	let {
		title,
		description,
		initialName = '',
		initialSection = '',
		save,
		onCreated,
		onCancel
	}: {
		title: string;
		description: string;
		initialName?: string;
		initialSection?: string;
		save: (input: { name: string; section_name: string | null }) => Promise<Classroom>;
		onCreated: (c: Classroom) => void | Promise<void>;
		onCancel: () => void;
	} = $props();

	// 서버의 길이 상한과 같다(강좌 이름 100자, 분반 이름 50자)
	const NAME_MAX = 100;
	const SECTION_MAX = 50;

	// 폼을 열 때마다 새로 만들어지므로(부르는 쪽이 key를 바꾼다) 처음 값만 필요하다
	// svelte-ignore state_referenced_locally
	let name = $state(initialName);
	// svelte-ignore state_referenced_locally
	let section = $state(initialSection);
	let saving = $state(false);
	let error = $state<string | null>(null);
	let nameInput: HTMLInputElement;

	const blank = $derived(name.trim() === '');
	const describedBy = $derived([blank ? 'name-hint' : null, error ? 'create-error' : null].filter(Boolean).join(' '));

	onMount(() => {
		nameInput.focus();
		if (name !== '') nameInput.select(); // 채워진 이름은 바로 고쳐 쓸 수 있게 선택해 둔다
	});

	async function submit(event: SubmitEvent) {
		event.preventDefault();
		if (blank || saving) return;
		saving = true;
		error = null;
		try {
			const created = await save({
				name: name.trim(),
				section_name: section.trim() === '' ? null : section.trim()
			});
			await onCreated(created);
		} catch (e) {
			// 서버가 준 안내(ApiError)는 그대로, 연결 문제는 해결 방법과 함께 알려 준다
			error =
				e instanceof ApiError
					? e.message
					: '강좌를 만들지 못했습니다. 네트워크 연결을 확인하고 다시 시도해 주세요.';
		} finally {
			saving = false;
		}
	}
</script>

<form id="create-form" class="card" onsubmit={submit}>
	<div class="card-header">
		<h2 class="card-title">{title}</h2>
		<p class="card-description">{description}</p>
	</div>
	<div class="card-content grid grid-cols-[repeat(auto-fit,minmax(min(15rem,100%),1fr))] gap-4">
		<div class="flex flex-col gap-2">
			<label for="classroom-name" class="label">강좌 이름</label>
			<input
				id="classroom-name"
				type="text"
				class="input"
				bind:this={nameInput}
				bind:value={name}
				maxlength={NAME_MAX}
				placeholder="강좌 이름을 입력하세요"
				aria-describedby={describedBy || undefined}
			/>
			{#if blank}
				<!-- 만들기를 누를 수 없는 이유. 입력 칸과 연결해 읽어 주는 도구도 전달한다 -->
				<p id="name-hint" class="text-sm text-muted-foreground">강좌 이름을 입력해 주세요.</p>
			{/if}
		</div>
		<div class="flex flex-col gap-2">
			<label for="classroom-section" class="label">분반 이름 (선택)</label>
			<input
				id="classroom-section"
				type="text"
				class="input"
				bind:value={section}
				maxlength={SECTION_MAX}
				placeholder="예: 월수반"
			/>
		</div>
	</div>
	{#if error}
		<p id="create-error" role="alert" class="card-content flex items-start gap-2 text-sm text-destructive-strong">
			<Icon name="warning-circle" class="size-4 mt-0.5" />{error}
		</p>
	{/if}
	<div class="card-footer">
		<button type="submit" class="btn btn-default" disabled={blank || saving}>
			{saving ? '만드는 중…' : '만들기'}
		</button>
		<button type="button" class="btn btn-outline" onclick={onCancel}>취소</button>
	</div>
</form>
