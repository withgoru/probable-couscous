<script lang="ts" module>
	// Iconoir regular(선 두께 1.5). 쓰는 아이콘만 가져와서 번들에 넣는다. 색은 currentColor
	import github from 'iconoir/icons/regular/github.svg?raw';
	import logOut from 'iconoir/icons/regular/log-out.svg?raw';
	import navArrowDown from 'iconoir/icons/regular/nav-arrow-down.svg?raw';
	import presentation from 'iconoir/icons/regular/presentation.svg?raw';
	import user from 'iconoir/icons/regular/user.svg?raw';
	import warningCircle from 'iconoir/icons/regular/warning-circle.svg?raw';

	const ICONS = {
		github,
		'log-out': logOut,
		'nav-arrow-down': navArrowDown,
		presentation,
		user,
		'warning-circle': warningCircle
	} as const;

	export type IconName = keyof typeof ICONS;
</script>

<script lang="ts">
	let { name, class: className = 'size-5' }: { name: IconName; class?: string } = $props();
</script>

<!-- 장식용이다. 의미는 옆의 글자가 전달한다(C14) -->
<span class="inline-flex shrink-0 items-center justify-center [&>svg]:size-full {className}" aria-hidden="true">
	{@html ICONS[name]}
</span>
