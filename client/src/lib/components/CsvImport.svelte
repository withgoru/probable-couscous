<script lang="ts">
	import { ApiError, importRoster, type ImportResult } from '#lib/api.js';
	import Icon from '#lib/components/Icon.svelte';

	let { classroomId, onImported }: { classroomId: number; onImported: () => void | Promise<void> } = $props();

	const MAX_BYTES = 1024 * 1024; // 서버의 상한과 같다
	let file = $state<File | null>(null);
	let busy = $state(false);
	let result = $state<ImportResult | null>(null);
	let error = $state<string | null>(null);
	let picker: HTMLInputElement;

	function choose() {
		file = picker.files?.[0] ?? null;
		result = null; // 새 파일을 고르면 이전 결과는 치운다
		error = null;
	}

	async function upload(event: SubmitEvent) {
		event.preventDefault();
		if (!file || busy) return;
		result = null;
		error = null;
		if (file.size > MAX_BYTES) {
			error = '파일이 너무 큽니다. 1MB 이하로 나눠 올려 주세요.';
			return;
		}
		busy = true;
		try {
			result = await importRoster(classroomId, file);
			picker.value = '';
			file = null;
			await onImported();
		} catch (e) {
			error =
				e instanceof ApiError ? e.message : '파일을 올리지 못했습니다. 네트워크 연결을 확인하고 다시 시도해 주세요.';
		} finally {
			busy = false;
		}
	}
</script>

<form class="flex flex-col gap-3" onsubmit={upload} aria-label="CSV 올리기">
	<div class="flex flex-col gap-2">
		<label for="roster-csv" class="label">CSV 파일</label>
		<input
			id="roster-csv"
			type="file"
			accept=".csv,text/csv"
			class="input h-auto min-h-11 py-2"
			bind:this={picker}
			onchange={choose}
			aria-describedby="roster-csv-help"
		/>
		<p id="roster-csv-help" class="text-sm text-muted-foreground">
			첫 줄은 제목이고, 열은 학번, 이름, 이메일 순서입니다. 엑셀에서는 'CSV UTF-8'로 저장해 주세요. 1MB까지 올릴 수 있습니다.
		</p>
	</div>
	<div>
		<button type="submit" class="btn btn-outline" disabled={!file || busy}>
			{busy ? '올리는 중…' : '올리기'}
		</button>
	</div>

	{#if error}
		<p role="alert" class="flex items-start gap-2 text-sm text-destructive-strong">
			<Icon name="warning-circle" class="mt-0.5 size-4 shrink-0" />{error}
		</p>
	{/if}

	{#if result}
		<div role="status" class="alert alert-info">
			<Icon name="check" />
			<div class="flex flex-col gap-2">
				<div class="alert-title">{result.added}명 추가, {result.skipped}줄 건너뜀</div>
				{#if result.skipped_lines.length > 0}
					<ul aria-label="건너뛴 줄" class="list-inside list-disc text-sm">
						{#each result.skipped_lines as s (s.line)}
							<li>{s.line}줄: {s.reason}</li>
						{/each}
					</ul>
				{/if}
			</div>
		</div>
	{/if}
</form>
