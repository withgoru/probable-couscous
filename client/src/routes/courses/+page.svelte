<script lang="ts">
	import { invalidate } from '$app/navigation';
	import { tick } from 'svelte';
	import type { Classroom } from '#lib/api.js';
	import ClassroomCard from '#lib/components/ClassroomCard.svelte';
	import ClassroomForm from '#lib/components/ClassroomForm.svelte';
	import Icon from '#lib/components/Icon.svelte';
	import * as Tabs from '#lib/components/ui/tabs/index.js';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();

	let tab = $state('active');
	let creating = $state(false);
	let created = $state<string | null>(null);
	let createButton: HTMLButtonElement;

	const byStatus = $derived({
		active: data.classrooms.filter((c) => c.status === 'active'),
		archived: data.classrooms.filter((c) => c.status === 'archived')
	});
	const EMPTY = {
		active: "진행 중인 강좌가 없습니다. '새 강좌 만들기'로 시작하세요.",
		archived: '보관된 강좌가 없습니다.'
	};

	function startCreate() {
		creating = true;
		created = null;
		tab = 'active'; // 새 강좌는 진행 중 목록 맨 앞에 생긴다
	}

	async function closeForm() {
		creating = false;
		await tick();
		createButton?.focus(); // 열었던 버튼으로 포커스를 돌려준다
	}

	async function onCreated(classroom: Classroom) {
		await invalidate('app:classrooms');
		created = classroom.name;
		tab = 'active';
		await closeForm();
	}
</script>

<svelte:head><title>내 강좌 · 강의 상호작용 도구</title></svelte:head>

<main class="mx-auto flex max-w-5xl flex-col gap-6 px-6 py-8 sm:px-8">
	<div class="flex flex-wrap items-center justify-between gap-3">
		<h1 class="text-3xl font-bold tracking-tight">내 강좌</h1>
		<button
			bind:this={createButton}
			type="button"
			class="btn btn-default"
			aria-expanded={creating}
			aria-controls="create-form"
			onclick={startCreate}
		>
			<Icon name="plus" />새 강좌 만들기
		</button>
	</div>

	{#if created}
		<div role="status" class="alert alert-info">
			<Icon name="check" />
			<div class="alert-title">강좌를 만들었습니다: {created}</div>
		</div>
	{/if}

	{#if creating}
		<ClassroomForm {onCreated} onCancel={closeForm} />
	{/if}

	<Tabs.Root bind:value={tab}>
		<Tabs.List>
			<Tabs.Trigger value="active">
				진행 중 <span class="badge badge-secondary ml-2">{data.counts.active}</span>
			</Tabs.Trigger>
			<Tabs.Trigger value="archived">
				보관됨 <span class="badge badge-secondary ml-2">{data.counts.archived}</span>
			</Tabs.Trigger>
		</Tabs.List>
		{#each ['active', 'archived'] as const as status (status)}
			<Tabs.Content value={status} class="pt-4">
				{#if byStatus[status].length === 0}
					<p class="text-sm text-muted-foreground">{EMPTY[status]}</p>
				{:else}
					<ul class="grid grid-cols-[repeat(auto-fit,minmax(min(20rem,100%),1fr))] gap-4">
						{#each byStatus[status] as classroom (classroom.id)}
							<ClassroomCard {classroom} />
						{/each}
					</ul>
				{/if}
			</Tabs.Content>
		{/each}
	</Tabs.Root>
</main>
