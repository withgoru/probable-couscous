<script lang="ts">
	import { AlertDialog } from 'bits-ui';
	import { ApiError, archiveClassroom, type Classroom } from '#lib/api.js';
	import ErrorNotice from '#lib/components/ErrorNotice.svelte';

	// 강좌 보관 확인(AC9). 되돌릴 수 없어서 확인 창이 열리면 포커스는 '취소'에 둔다
	let {
		classroom,
		onArchived,
		onAlready,
		onCancel
	}: {
		classroom: Classroom;
		onArchived: (c: Classroom) => void;
		onAlready: () => void; // 다른 창에서 이미 보관했다
		onCancel: () => void;
	} = $props();

	const CONFIRM = '보관하면 학생이 더 이상 입장할 수 없고 모든 학생의 로그인 유지가 끝납니다. 기록은 볼 수 있습니다.';
	let pending = $state(false);
	let cancelButton = $state<HTMLButtonElement | null>(null);
	let problem = $state<{ title: string; hint: string } | null>(null);
	let liveClass = $state(false); // 수업 중이라 거절됨(002 AC46): 수업 화면으로 가는 버튼을 보인다
	const label = $derived(`${classroom.name}${classroom.section_name ? ` (${classroom.section_name})` : ''}`);

	async function confirm() {
		if (pending) return;
		pending = true;
		problem = null;
		liveClass = false;
		try {
			onArchived(await archiveClassroom(classroom.id));
		} catch (err) {
			if (err instanceof ApiError && err.status === 409 && err.data?.live_session_id != null) {
				problem = { title: err.message, hint: '수업 화면에서 수업 종료를 누른 뒤 다시 보관해 주세요.' };
				liveClass = true;
			} else if (err instanceof ApiError && err.status === 409) {
				problem = { title: err.message, hint: '보관됨 탭에서 확인하세요.' };
				onAlready();
			} else if (err instanceof ApiError) {
				problem = { title: err.message, hint: '잠시 뒤 다시 시도해 주세요.' };
			} else {
				problem = { title: '강좌를 보관하지 못했습니다.', hint: '네트워크 연결을 확인하고 다시 시도해 주세요.' };
			}
		} finally {
			pending = false;
		}
	}
</script>

<AlertDialog.Root
	open={true}
	onOpenChange={(open) => {
		if (!open && !pending) onCancel();
	}}
>
	<AlertDialog.Portal>
		<AlertDialog.Overlay class="fixed inset-0 z-50 bg-foreground/50" />
		<AlertDialog.Content
			class="dialog fixed top-1/2 left-1/2 z-50 w-[calc(100%-2rem)] -translate-x-1/2 -translate-y-1/2"
			onOpenAutoFocus={(e) => {
				e.preventDefault();
				cancelButton?.focus();
			}}
			onCloseAutoFocus={(e) => e.preventDefault()}
		>
			<div class="flex flex-col gap-2">
				<AlertDialog.Title class="text-lg font-semibold">{label} 강좌를 보관할까요?</AlertDialog.Title>
				<AlertDialog.Description class="text-sm text-muted-foreground">{CONFIRM}</AlertDialog.Description>
			</div>
			{#if problem}<ErrorNotice title={problem.title} hint={problem.hint} />{/if}
			{#if liveClass}<a class="btn btn-default self-start" href={`/courses/${classroom.id}/live`}>수업 화면으로</a>{/if}
			<div class="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
				<AlertDialog.Cancel bind:ref={cancelButton} class="btn btn-outline" disabled={pending}>취소</AlertDialog.Cancel>
				<AlertDialog.Action class="btn btn-destructive" disabled={pending} onclick={confirm}>
					{pending ? '보관하는 중…' : '보관'}
				</AlertDialog.Action>
			</div>
		</AlertDialog.Content>
	</AlertDialog.Portal>
</AlertDialog.Root>
