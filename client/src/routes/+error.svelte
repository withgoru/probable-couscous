<script lang="ts">
	import { page } from '$app/state';
	import ErrorNotice from '#lib/components/ErrorNotice.svelte';

	// 없는 주소(404)와 연결·서버 문제를 나눠서, 무엇이 잘못됐고 어떻게 하면 되는지 알려 준다
	const notFound = $derived(page.status === 404);
</script>

<svelte:head><title>오류 · 강의 상호작용 도구</title></svelte:head>

<main class="mx-auto flex max-w-xl flex-col gap-4 px-6 py-12">
	{#if notFound}
		<ErrorNotice title="찾을 수 없는 화면입니다" hint="주소를 확인하거나 처음으로 돌아가 주세요." />
	{:else}
		<ErrorNotice
			title="화면을 불러오지 못했습니다"
			hint="서버에 연결되지 않았거나 일시적인 문제일 수 있습니다. 잠시 뒤 새로고침해 주세요. 계속되면 서버가 실행 중인지 확인해 주세요."
		/>
	{/if}
	<a href="/" class="btn btn-outline self-start">처음으로 돌아가기</a>
</main>
