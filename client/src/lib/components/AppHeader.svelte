<script lang="ts">
	import { goto } from '$app/navigation';
	import { logout } from '#lib/api.js';
	import type { Me } from '#lib/api.js';
	import Icon from '#lib/components/Icon.svelte';
	import * as DropdownMenu from '#lib/components/ui/dropdown-menu/index.js';

	let { me }: { me: Me } = $props();
	let failed = $state(false);

	async function signOut() {
		failed = false;
		try {
			await logout();
		} catch {
			failed = true; // 서버에 로그인 상태가 남아 있으니 이동하지 않는다
			return;
		}
		// 로그인 화면으로 바꿔 끼워 뒤로 가기에서 이전 화면이 나오지 않게 하고, 다시 불러와 로그인 상태를 비운다
		await goto('/login', { replace: true, refreshAll: true });
	}
</script>

<header class="relative flex h-16 items-center justify-between gap-4 border-b bg-background px-6 sm:px-8">
	<div class="flex min-w-0 items-center gap-2">
		<a
			href="/courses"
			class="flex min-h-11 items-center gap-2 rounded-md text-sm font-semibold text-foreground no-underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:outline-none"
		>
			<Icon name="presentation" />강의 상호작용 도구
		</a>
	</div>

	<div class="flex items-center gap-3">
		{#if failed}
			<p role="alert" class="text-sm text-destructive-strong">
				로그아웃하지 못했습니다. 네트워크 연결을 확인하고 다시 시도해 주세요.
			</p>
		{/if}
		<DropdownMenu.Root>
			<DropdownMenu.Trigger class="btn btn-outline rounded-full pr-3 pl-2">
				<span class="avatar size-8" aria-hidden="true">
					<span class="avatar-fallback">{me.login.slice(0, 1).toUpperCase()}</span>
				</span>
				@{me.login}
				<Icon name="nav-arrow-down" class="size-4" />
			</DropdownMenu.Trigger>
			<DropdownMenu.Content align="end" class="menu w-60">
				<DropdownMenu.Label class="menu-label">
					@{me.login}
					<div class="text-xs font-normal text-muted-foreground">GitHub 계정</div>
				</DropdownMenu.Label>
				<DropdownMenu.Separator class="menu-separator" />
				<DropdownMenu.Item class="menu-item">
					{#snippet child({ props })}
						<a href="/mypage" {...props}><Icon name="user" class="size-4" />마이페이지</a>
					{/snippet}
				</DropdownMenu.Item>
				<DropdownMenu.Separator class="menu-separator" />
				<DropdownMenu.Item class="menu-item menu-item-destructive" onSelect={signOut}>
					<Icon name="log-out" class="size-4" />로그아웃
				</DropdownMenu.Item>
			</DropdownMenu.Content>
		</DropdownMenu.Root>
	</div>
</header>
