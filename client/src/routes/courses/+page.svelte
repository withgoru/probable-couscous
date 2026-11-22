<script lang="ts">
	import { invalidate } from '$app/navigation';
	import { tick } from 'svelte';
	import { cloneClassroom, createClassroom, type Classroom } from '#lib/api.js';
	import ArchiveDialog from '#lib/components/ArchiveDialog.svelte';
	import ClassroomCard from '#lib/components/ClassroomCard.svelte';
	import ClassroomForm from '#lib/components/ClassroomForm.svelte';
	import Icon from '#lib/components/Icon.svelte';
	import * as Tabs from '#lib/components/ui/tabs/index.js';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();

	// 열려 있는 폼 하나. key가 바뀌면 폼이 새로 만들어져 이전 입력이 남지 않는다
	type OpenForm = { key: number; source: Classroom | null; opener: HTMLElement | null };

	let tab = $state('active');
	let form = $state<OpenForm | null>(null);
	let formCount = 0;
	let created = $state<string | null>(null);
	let archived = $state<string | null>(null);
	let archiving = $state<{ classroom: Classroom; opener: HTMLElement } | null>(null);
	let createButton: HTMLButtonElement;
	let archivedTab = $state<HTMLButtonElement | null>(null);

	const byStatus = $derived({
		active: data.classrooms.filter((c) => c.status === 'active'),
		archived: data.classrooms.filter((c) => c.status === 'archived')
	});
	const EMPTY = {
		active: "진행 중인 강좌가 없습니다. '새 강좌 만들기'로 시작하세요.",
		archived: '보관된 강좌가 없습니다.'
	};

	function startCreate() {
		form = { key: ++formCount, source: null, opener: createButton };
		created = null;
		tab = 'active'; // 새 강좌는 진행 중 목록 맨 앞에 생긴다
	}

	function startClone(source: Classroom, opener: HTMLElement) {
		// 탭은 그대로 둔다. 눌렀던 카드가 보여야 닫을 때 그 버튼으로 포커스를 돌려줄 수 있다
		form = { key: ++formCount, source, opener };
		created = null;
	}

	async function closeForm(backToOpener = true) {
		const opener = form?.opener;
		form = null;
		await tick();
		// 열었던 버튼으로 포커스를 돌려준다. 만든 뒤에는 그 버튼이 가려질 수 있어 새 강좌 만들기 버튼으로 간다
		(backToOpener && opener && opener.isConnected ? opener : createButton)?.focus();
	}

	async function onCreated(classroom: Classroom) {
		await invalidate('app:classrooms');
		created = classroom.name;
		archived = null;
		tab = 'active';
		await closeForm(false);
	}

	function startArchive(classroom: Classroom, opener: HTMLElement) {
		archiving = { classroom, opener };
	}

	async function cancelArchive() {
		const opener = archiving?.opener;
		archiving = null;
		await tick();
		opener?.focus();
	}

	async function onArchived(classroom: Classroom) {
		archiving = null;
		created = null;
		archived = classroom.name;
		await invalidate('app:classrooms');
		tab = 'archived'; // 확인하면 보관됨 탭으로 옮겨진다(AC9)
		await tick();
		archivedTab?.focus(); // 눌렀던 카드는 진행 중 목록에서 사라졌다
	}

	const formText = $derived(
		form?.source
			? {
					title: form.source.status === 'archived' ? '새 학기로 복제' : '분반 만들기',
					description: '이름과 분반을 확인하고 고칠 수 있습니다. 수강생 명단과 기록은 새로 시작합니다.'
				}
			: { title: '새 강좌 만들기', description: '분반 이름은 비워 둘 수 있습니다.' }
	);
</script>

<svelte:head><title>내 강좌 · 강의 상호작용 도구</title></svelte:head>

<main class="mx-auto flex max-w-5xl flex-col gap-6 px-6 py-8 sm:px-8">
	<div class="flex flex-wrap items-center justify-between gap-3">
		<h1 class="text-3xl font-bold tracking-tight">내 강좌</h1>
		<button
			bind:this={createButton}
			type="button"
			class="btn btn-default"
			aria-expanded={form !== null && form.source === null}
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

	{#if archived}
		<div role="status" class="alert alert-info">
			<Icon name="check" />
			<div class="alert-title">강좌를 보관했습니다: {archived}</div>
		</div>
	{/if}

	{#if archiving}
		{#key archiving.classroom.id}
			<ArchiveDialog
				classroom={archiving.classroom}
				{onArchived}
				onAlready={() => invalidate('app:classrooms')}
				onCancel={cancelArchive}
			/>
		{/key}
	{/if}

	{#if form}
		{#key form.key}
			<ClassroomForm
				title={formText.title}
				description={formText.description}
				initialName={form.source?.name ?? ''}
				initialSection={form.source?.section_name ?? ''}
				save={form.source ? (input) => cloneClassroom(form!.source!.id, input) : createClassroom}
				{onCreated}
				onCancel={() => closeForm()}
			/>
		{/key}
	{/if}

	<Tabs.Root bind:value={tab}>
		<Tabs.List>
			<Tabs.Trigger value="active">
				진행 중 <span class="badge badge-secondary ml-2">{data.counts.active}</span>
			</Tabs.Trigger>
			<Tabs.Trigger value="archived" bind:ref={archivedTab}>
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
							<ClassroomCard {classroom} onClone={startClone} onArchive={startArchive} />
						{/each}
					</ul>
				{/if}
			</Tabs.Content>
		{/each}
	</Tabs.Root>
</main>
