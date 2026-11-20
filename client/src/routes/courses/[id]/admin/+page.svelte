<script lang="ts">
	import ErrorNotice from '#lib/components/ErrorNotice.svelte';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();

	const HINTS: Record<number, string> = {
		403: '다른 교수님의 강좌입니다. 내 강좌 목록에서 열어 주세요.',
		404: '주소를 확인하거나 내 강좌 목록에서 열어 주세요.'
	};
</script>

<svelte:head><title>관리 페이지 · 강의 상호작용 도구</title></svelte:head>

<!-- 관리 페이지의 내용(명단, 초대 링크 등)은 T013 이후에 채운다. 지금은 열 수 있는지와 이유만 보여 준다 -->
<main class="mx-auto flex max-w-5xl flex-col gap-4 px-6 py-8 sm:px-8">
	{#if data.notice}
		<ErrorNotice title={data.notice.message} hint={HINTS[data.notice.status]} />
		<a href="/courses" class="btn btn-outline self-start">내 강좌로 돌아가기</a>
	{:else if data.classroom}
		<h1 class="text-3xl font-bold tracking-tight">관리 페이지</h1>
		<p class="text-muted-foreground">{data.classroom.name}</p>
	{/if}
</main>
