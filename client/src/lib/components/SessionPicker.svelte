<script lang="ts">
	import { DropdownMenu } from 'bits-ui';
	import { tick } from 'svelte';
	import { ApiError, createSession, deleteSession, renameSession, type ClassSession } from '#lib/api.js';
	import ConfirmDialog from '#lib/components/ConfirmDialog.svelte';
	import ErrorNotice from '#lib/components/ErrorNotice.svelte';
	import Icon from '#lib/components/Icon.svelte';

	// 관리 페이지 위쪽의 회차 선택과 회차 관리(002 AC1~AC4).
	// 목록은 부르는 쪽이 갖고 있다. 바꾼 뒤 onChanged로 다시 불러오게 하고, 고른 회차는 onSelect로 알린다
	let {
		classroomId,
		sessions,
		selectedId,
		onChanged,
		onSelect
	}: {
		classroomId: number;
		sessions: ClassSession[];
		selectedId: number | null;
		onChanged: () => void | Promise<void>;
		onSelect: (id: number | null) => void;
	} = $props();

	const TITLE_MAX = 40; // 서버의 회차 이름 상한과 같다
	const STATUS: Record<ClassSession['status'], string> = { scheduled: '예정', live: '진행 중', ended: '종료' };

	const selected = $derived(sessions.find((s) => s.id === selectedId) ?? null);

	// 만들기와 이름 바꾸기가 같은 폼을 쓴다
	let form = $state<{ mode: 'create' | 'rename'; title: string } | null>(null);
	let saving = $state(false);
	let error = $state<string | null>(null);
	let confirmingDelete = $state(false);
	let titleInput = $state<HTMLInputElement | null>(null);
	const blank = $derived(!form || form.title.trim() === '');

	async function openForm(mode: 'create' | 'rename') {
		form = { mode, title: mode === 'rename' && selected ? selected.title : '' };
		error = null;
		await tick();
		titleInput?.focus();
		if (mode === 'rename') titleInput?.select();
	}

	async function submit(event: SubmitEvent) {
		event.preventDefault();
		if (!form || blank || saving) return;
		saving = true;
		error = null;
		const title = form.title.trim();
		try {
			if (form.mode === 'create') {
				const created = await createSession(classroomId, title);
				await onChanged();
				onSelect(created.id); // 만든 회차가 선택된다(AC2)
			} else if (selected) {
				await renameSession(classroomId, selected.id, title);
				await onChanged();
			}
			form = null;
		} catch (e) {
			error =
				e instanceof ApiError ? e.message : '회차를 저장하지 못했습니다. 네트워크 연결을 확인하고 다시 시도해 주세요.';
		} finally {
			saving = false;
		}
	}

	async function remove() {
		if (!selected) return null;
		try {
			await deleteSession(classroomId, selected.id);
		} catch (e) {
			return e instanceof ApiError
				? { title: e.message }
				: { title: '회차를 삭제하지 못했습니다.', hint: '네트워크 연결을 확인하고 다시 시도해 주세요.' };
		}
		confirmingDelete = false; // 지운 회차는 더 고를 수 없다
		onSelect(null);
		await onChanged();
		return null;
	}
</script>

<section class="flex flex-col gap-3" aria-label="회차">
	{#if sessions.length === 0}
		<p class="text-muted-foreground">아직 회차가 없습니다. 회차를 만들어 수업을 준비하세요.</p>
		{#if !form}
			<button type="button" class="btn btn-default self-start" onclick={() => openForm('create')}>
				<Icon name="plus" />회차 만들기
			</button>
		{/if}
	{:else}
		<div class="flex flex-wrap items-center gap-2">
			<DropdownMenu.Root>
				<DropdownMenu.Trigger class="btn btn-outline" aria-label={`회차 선택: ${selected ? `${selected.title} ${STATUS[selected.status]}` : '고르지 않음'}`}>
					{#if selected}
						{#if selected.status === 'live'}<Icon name="presentation" />{/if}
						<span class="font-medium">{selected.title}</span>
						<span class="text-muted-foreground">{STATUS[selected.status]}</span>
					{:else}
						<span>회차를 고르세요</span>
					{/if}
					<Icon name="nav-arrow-down" />
				</DropdownMenu.Trigger>
				<DropdownMenu.Portal>
					<DropdownMenu.Content align="end" class="menu w-72">
						<DropdownMenu.RadioGroup
							value={selectedId === null ? '' : String(selectedId)}
							onValueChange={(value) => onSelect(Number(value))}
						>
							{#each sessions as s (s.id)}
								<DropdownMenu.RadioItem value={String(s.id)} class="menu-item justify-between">
									{#snippet children({ checked })}
										<span class="flex items-center gap-2">
											{#if checked}<Icon name="check" />{/if}
											<span>{s.title}</span>
										</span>
										<span class="flex items-center gap-1 text-sm text-muted-foreground">
											{#if s.status === 'live'}<Icon name="presentation" />{/if}
											{STATUS[s.status]}
										</span>
									{/snippet}
								</DropdownMenu.RadioItem>
							{/each}
						</DropdownMenu.RadioGroup>
						<DropdownMenu.Separator class="menu-separator" />
						<DropdownMenu.Item class="menu-item" onSelect={() => openForm('create')}>
							<Icon name="plus" />새 회차 만들기
						</DropdownMenu.Item>
					</DropdownMenu.Content>
				</DropdownMenu.Portal>
			</DropdownMenu.Root>
			{#if selected && !form}
				<button type="button" class="btn btn-outline" onclick={() => openForm('rename')}>이름 바꾸기</button>
				{#if selected.can_delete}<!-- 서버가 정한다: 한 번도 시작하지 않은 예정 회차(AC4) -->
					<button type="button" class="btn btn-outline text-destructive-strong" onclick={() => (confirmingDelete = true)}>삭제</button>
				{/if}
			{/if}
		</div>
	{/if}

	{#if form}
		<form class="card" onsubmit={submit}>
			<div class="card-content flex flex-col gap-2">
				<label for="session-title" class="label">회차 이름</label>
				<input
					id="session-title"
					type="text"
					class="input"
					bind:this={titleInput}
					bind:value={form.title}
					maxlength={TITLE_MAX}
					placeholder="예: 3주차 1회차"
					aria-describedby={[blank ? 'session-title-hint' : null, error ? 'session-title-error' : null]
						.filter(Boolean)
						.join(' ') || undefined}
				/>
				{#if blank}
					<p id="session-title-hint" class="text-sm text-muted-foreground">회차 이름을 입력해 주세요.</p>
				{/if}
				{#if error}<div id="session-title-error"><ErrorNotice title={error} /></div>{/if}
				<div class="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
					<button type="button" class="btn btn-outline" disabled={saving} onclick={() => (form = null)}>취소</button>
					<button type="submit" class="btn btn-default" disabled={blank || saving}>
						{form.mode === 'create' ? (saving ? '만드는 중…' : '만들기') : saving ? '저장하는 중…' : '저장'}
					</button>
				</div>
			</div>
		</form>
	{/if}
</section>

{#if confirmingDelete && selected}
	<ConfirmDialog
		title={`${selected.title} 회차를 삭제할까요?`}
		description="올린 슬라이드도 함께 지워집니다."
		confirmLabel="삭제"
		busyLabel="삭제하는 중…"
		onConfirm={remove}
		onDone={() => (confirmingDelete = false)}
		onCancel={() => (confirmingDelete = false)}
	/>
{/if}
