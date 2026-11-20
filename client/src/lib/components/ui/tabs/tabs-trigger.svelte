<script lang="ts">
	import { Tabs as TabsPrimitive } from "bits-ui";
	import { cn } from "#lib/utils.js";

	let { ref = $bindable(null), class: className, ...restProps }: TabsPrimitive.TriggerProps = $props();
</script>

<!-- 선택된 탭은 data-state="active"로 theme.css가 그린다. 포커스 링은 불투명 2px + 간격 2px(C14).
     theme.css의 tabs-line-trigger에는 간격이 없어 여기서 더한다 -->
<TabsPrimitive.Trigger
	bind:ref
	data-slot="tabs-trigger"
	class={cn("tabs-line-trigger focus-visible:ring-offset-2 focus-visible:ring-offset-background", className)}
	{...restProps}
/>
