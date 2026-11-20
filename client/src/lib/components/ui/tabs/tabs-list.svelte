<script lang="ts">
	import { Tabs as TabsPrimitive } from "bits-ui";
	import { cn } from "#lib/utils.js";

	let { ref = $bindable(null), class: className, ...restProps }: TabsPrimitive.ListProps = $props();
</script>

<!-- 밑줄형 탭. 모양은 디자인 시스템(theme.css)의 tabs-line -->
<TabsPrimitive.List bind:ref data-slot="tabs-list" class={cn("tabs-line", className)} {...restProps} />
