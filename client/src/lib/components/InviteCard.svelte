<script lang="ts">
	import { ApiError, regenerateInvite, type Invite } from '#lib/api.js';
	import Icon from '#lib/components/Icon.svelte';

	let {
		classroomId,
		invite,
		onChanged
	}: { classroomId: number; invite: Invite; onChanged: () => void | Promise<void> } = $props();

	// 알림 문구 하나. ok는 보통 알림(role=status), error는 경고(role=alert)로 보인다
	let message = $state('');
	let problem = $state<string | null>(null);
	let busy = $state(false);
	let linkInput: HTMLInputElement;

	async function copy() {
		message = '';
		problem = null;
		try {
			await navigator.clipboard.writeText(invite.url);
			message = '복사했습니다';
		} catch {
			// 복사했다고 거짓으로 알리지 않고, 직접 복사할 수 있게 링크를 선택해 둔다
			linkInput.select();
			problem = '복사하지 못했습니다. 링크를 선택해 직접 복사해 주세요.';
		}
	}

	async function regenerate() {
		if (busy) return;
		busy = true;
		message = '';
		problem = null;
		try {
			await regenerateInvite(classroomId);
			await onChanged();
			message = '새 링크를 만들었습니다. 이전 링크는 더 이상 사용할 수 없습니다.';
		} catch (e) {
			problem =
				e instanceof ApiError ? e.message : '링크를 만들지 못했습니다. 네트워크 연결을 확인하고 다시 시도해 주세요.';
		} finally {
			busy = false;
		}
	}
</script>

<section class="card gap-4" aria-labelledby="invite-title">
	<div class="card-header">
		<h2 id="invite-title" class="card-title text-xl">초대 링크</h2>
		<p class="card-description">
			학생에게 이 링크를 보내 주세요. 링크를 열어도 입장되지 않습니다. 수강생 명단에 있는 이메일로 인증해야 입장합니다.
		</p>
	</div>
	<div class="card-content flex flex-col gap-3">
		<div class="flex flex-col gap-2">
			<label for="invite-link" class="label">초대 링크 주소</label>
			<div class="flex flex-wrap gap-2">
				<input
					id="invite-link"
					type="text"
					class="input min-w-0 flex-1"
					readonly
					value={invite.url}
					bind:this={linkInput}
					onfocus={(e) => e.currentTarget.select()}
				/>
				<button type="button" class="btn btn-default" onclick={copy}>
					<Icon name="copy" />복사
				</button>
			</div>
		</div>
		<div class="flex flex-wrap items-center gap-3">
			<button type="button" class="btn btn-outline" onclick={regenerate} disabled={busy}>
				{busy ? '만드는 중…' : '링크 다시 만들기'}
			</button>
			<p class="text-sm text-muted-foreground">다시 만들면 이전 링크는 바로 사용할 수 없게 됩니다.</p>
		</div>
		<!-- 알림 영역은 처음부터 있어야 화면 읽기 도구가 문구가 바뀔 때 읽어 준다 -->
		<p role="status" class="text-sm">{message}</p>
		{#if problem}
			<p role="alert" class="flex items-start gap-2 text-sm text-destructive-strong">
				<Icon name="warning-circle" class="mt-0.5 size-4 shrink-0" />{problem}
			</p>
		{/if}
	</div>
</section>
