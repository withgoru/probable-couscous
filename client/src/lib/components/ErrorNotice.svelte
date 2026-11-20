<script lang="ts">
	import Icon from '#lib/components/Icon.svelte';

	// 무엇이 잘못됐는지(title)와 어떻게 하면 되는지(hint)를 함께 알려 주는 오류 알림
	let { title, hint }: { title: string; hint?: string } = $props();
</script>

<div role="alert" class="alert alert-destructive">
	<Icon name="warning-circle" />
	<div class="flex flex-col gap-0.5">
		<div class="alert-title">{title}</div>
		{#if hint}<div class="alert-description">{hint}</div>{/if}
	</div>
</div>
