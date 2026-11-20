<script lang="ts">
	import { invalidate } from '$app/navigation';
	import ErrorNotice from '#lib/components/ErrorNotice.svelte';
	import InviteCard from '#lib/components/InviteCard.svelte';
	import RosterSection from '#lib/components/RosterSection.svelte';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();

	const HINTS: Record<number, string> = {
		403: '다른 교수님의 강좌입니다. 내 강좌 목록에서 열어 주세요.',
		404: '주소를 확인하거나 내 강좌 목록에서 열어 주세요.'
	};
</script>

<svelte:head><title>관리 페이지 · 강의 상호작용 도구</title></svelte:head>

<!-- 입장 요청, 대기 중인 인증 등은 이후 작업에서 채운다 -->
<main class="mx-auto flex max-w-5xl flex-col gap-4 px-6 py-8 sm:px-8">
	{#if data.notice}
		<ErrorNotice title={data.notice.message} hint={HINTS[data.notice.status]} />
		<a href="/courses" class="btn btn-outline self-start">내 강좌로 돌아가기</a>
	{:else if data.classroom}
		<h1 class="text-3xl font-bold tracking-tight">관리 페이지</h1>
		<p class="text-muted-foreground">{data.classroom.name}</p>
		{#if data.invite}
			<InviteCard
				classroomId={data.classroom.id}
				invite={data.invite}
				onChanged={() => invalidate('app:invite')}
			/>
		{/if}
		{#if data.roster}
			<RosterSection
				classroomId={data.classroom.id}
				roster={data.roster}
				onChanged={() => invalidate('app:roster')}
			/>
		{/if}
	{/if}
</main>
