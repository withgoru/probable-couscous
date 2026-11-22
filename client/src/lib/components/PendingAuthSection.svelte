<script lang="ts">
	import type { PendingAuth } from '#lib/api.js';
	import Icon from '#lib/components/Icon.svelte';
	import { clockTime } from '#lib/time.js';

	// '교수님께 알리기'를 누른 학생의 코드(AC45, AC47). 학번·이름·시각·코드만 보이고 이메일과 닉네임은 없다(C9).
	// 코드는 시간이 지나면 서버에 묻지 않고 '만료됨'으로 바꾼다(다시 부르면 코드 열람이 기록되므로, now로만 판단한다)
	let {
		items,
		now,
		loadError = null
	}: { items: PendingAuth[] | null; now: Date; loadError?: string | null } = $props();

	const expired = (item: PendingAuth) =>
		item.status === 'expired' || (item.status === 'waiting' && now >= new Date(item.expires_at));
</script>

<section class="card gap-4" aria-labelledby="pending-title">
	<div class="card-header">
		<h2 id="pending-title" class="card-title text-xl">대기 중인 인증</h2>
		<p class="card-description">인증 메일을 받지 못한 학생이 '교수님께 알리기'를 누르면 코드가 여기에 보입니다. 학생에게 알려 주세요.</p>
		<p class="card-description">코드를 볼 때마다 기록됩니다.</p>
	</div>
	<div class="card-content">
		{#if loadError}
			<p role="alert" class="flex items-start gap-2 text-sm font-medium text-destructive-strong">
				<Icon name="warning-circle" class="mt-0.5 size-4 shrink-0" />{loadError}
			</p>
		{:else if items === null}
			<p class="text-sm text-muted-foreground">불러오는 중…</p>
		{:else if items.length === 0}
			<p class="text-sm text-muted-foreground">대기 중인 인증이 없습니다.</p>
		{:else}
			<div class="overflow-x-auto">
				<table class="w-full text-sm">
					<thead>
						<tr class="border-b text-left text-muted-foreground">
							<th scope="col" class="py-2 pr-4 font-medium">학번</th>
							<th scope="col" class="py-2 pr-4 font-medium">이름</th>
							<th scope="col" class="py-2 pr-4 font-medium">요청 시각</th>
							<th scope="col" class="py-2 font-medium">코드</th>
						</tr>
					</thead>
					<tbody>
						{#each items as item (item.id)}
							<tr class="border-b last:border-0">
								<td class="py-3 pr-4">{item.student_no}</td>
								<td class="py-3 pr-4">{item.name}</td>
								<td class="py-3 pr-4"><time datetime={item.notified_at}>{clockTime(item.notified_at)}</time></td>
								<td class="py-3">
									{#if item.status === 'used'}
										<span class="font-medium text-success-text">사용됨 ({clockTime(item.used_at)})</span>
									{:else if expired(item) || item.status !== 'waiting'}
										<span class="text-muted-foreground">만료됨</span>
									{:else}
										<span class="flex flex-wrap items-baseline gap-x-3">
											<span class="font-mono text-2xl font-semibold tracking-[0.2em]">{item.code}</span>
											<span class="text-muted-foreground">{clockTime(item.expires_at)}까지</span>
										</span>
									{/if}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	</div>
</section>
