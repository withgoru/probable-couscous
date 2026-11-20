<script lang="ts">
	import Icon from '#lib/components/Icon.svelte';
</script>

<svelte:head><title>오류 · 강의 상호작용 도구</title></svelte:head>

<main class="mx-auto flex max-w-xl flex-col gap-4 px-6 py-12">
	<div role="alert" class="alert alert-destructive">
		<Icon name="warning-circle" />
		<div class="flex flex-col gap-0.5">
			<div class="alert-title">화면을 불러오지 못했습니다</div>
			<div class="alert-description">
				서버에 연결되지 않았거나 일시적인 문제일 수 있습니다. 잠시 뒤 새로고침해 주세요. 계속되면 서버가 실행 중인지 확인해 주세요.
			</div>
		</div>
	</div>
	<a href="/" class="btn btn-outline self-start">처음으로 돌아가기</a>
</main>
