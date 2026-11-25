<script lang="ts">
	import { AlertDialog } from 'bits-ui';
	import ErrorNotice from '#lib/components/ErrorNotice.svelte';

	// 되돌리기 어려운 동작의 확인 창. 열리면 포커스는 '취소'에 둔다(Enter를 잘못 눌러도 실행되지 않게).
	// onConfirm이 문제를 돌려주면 창 안에 보이고 창은 그대로 둔다. null이면 성공이라 onDone을 부른다.
	type Problem = { title: string; hint?: string };
	let {
		title,
		description,
		confirmLabel,
		busyLabel,
		onConfirm,
		onDone,
		onCancel,
		tone = 'destructive'
	}: {
		title: string;
		description: string;
		confirmLabel: string;
		busyLabel: string;
		onConfirm: () => Promise<Problem | null>;
		onDone: () => void;
		onCancel: () => void;
		/** 확인 버튼 모양. 지우기처럼 되돌릴 수 없는 일은 destructive, 그 밖의 확인은 default. */
		tone?: 'destructive' | 'default';
	} = $props();

	let pending = $state(false);
	let problem = $state<Problem | null>(null);
	let cancelButton = $state<HTMLButtonElement | null>(null);

	async function confirm() {
		if (pending) return;
		pending = true;
		problem = null;
		try {
			problem = await onConfirm();
		} finally {
			pending = false;
		}
		if (!problem) onDone();
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
				<AlertDialog.Title class="text-lg font-semibold">{title}</AlertDialog.Title>
				<AlertDialog.Description class="text-sm text-muted-foreground">{description}</AlertDialog.Description>
			</div>
			{#if problem}<ErrorNotice title={problem.title} hint={problem.hint} />{/if}
			<div class="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
				<AlertDialog.Cancel bind:ref={cancelButton} class="btn btn-outline" disabled={pending}>취소</AlertDialog.Cancel>
				<AlertDialog.Action class={`btn btn-${tone}`} disabled={pending} onclick={confirm}>
					{pending ? busyLabel : confirmLabel}
				</AlertDialog.Action>
			</div>
		</AlertDialog.Content>
	</AlertDialog.Portal>
</AlertDialog.Root>
