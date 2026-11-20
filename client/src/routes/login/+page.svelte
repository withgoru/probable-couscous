<script lang="ts">
	import { page } from '$app/state';
	import Icon from '#lib/components/Icon.svelte';

	// 서버가 `/login?error=코드`로 돌려보낸다. 코드마다 무엇이 잘못됐고 어떻게 하면 되는지 알려 준다
	const MESSAGES: Record<string, { title: string; hint: string }> = {
		not_allowed: {
			title: '이 GitHub 계정은 사용할 수 없습니다',
			hint: '허용 목록에 없는 계정입니다. 허용된 계정으로 다시 로그인해 주세요.'
		},
		state: {
			title: '로그인을 완료하지 못했습니다',
			hint: '로그인 요청이 만료되었거나 다른 창에서 시작되었습니다. 다시 로그인해 주세요.'
		},
		cancelled: {
			title: 'GitHub 로그인을 취소했습니다',
			hint: '계속하려면 GitHub로 로그인해 주세요.'
		},
		github: {
			title: 'GitHub와 통신하지 못했습니다',
			hint: '잠시 뒤 다시 시도해 주세요. 계속되면 서버 설정(GitHub 클라이언트 ID와 비밀값)을 확인해 주세요.'
		}
	};
	const GENERIC = {
		title: '로그인하지 못했습니다',
		hint: '다시 로그인해 주세요. 계속되면 서버 관리자에게 알려 주세요.'
	};

	const code = $derived(page.url.searchParams.get('error'));
	const message = $derived(code ? (MESSAGES[code] ?? GENERIC) : null);
</script>

<svelte:head><title>교수 로그인 · 강의 상호작용 도구</title></svelte:head>

<div class="flex min-h-screen items-center justify-center bg-muted/40 px-5 py-8">
	<main class="card w-full max-w-md">
		<div class="card-header">
			<div class="flex items-center gap-2 text-sm font-medium text-muted-foreground">
				<Icon name="presentation" class="size-4" />강의 상호작용 도구
			</div>
			<h1 class="card-title mt-2 text-2xl leading-tight">교수 로그인</h1>
			<p class="card-description">GitHub 계정으로 로그인합니다. 허용된 계정만 강좌를 만들고 관리할 수 있습니다.</p>
		</div>

		<div class="card-content flex flex-col gap-4">
			{#if message}
				<div role="alert" class="alert alert-destructive">
					<Icon name="warning-circle" />
					<div class="flex flex-col gap-0.5">
						<div class="alert-title">{message.title}</div>
						<div class="alert-description">{message.hint}</div>
					</div>
				</div>
			{/if}
			<!-- 서버가 GitHub로 보내는 주소라서 화면 전환(SPA 이동)이 아니라 서버로 이동한다 -->
			<a href="/api/auth/github/login" data-sveltekit-reload class="btn btn-default btn-lg w-full">
				<Icon name="github" />GitHub로 로그인
			</a>
		</div>

		<div class="px-6"><div class="separator"></div></div>
		<p class="card-footer text-sm text-muted-foreground">
			학생이신가요? 가입 없이, 교수님이 보낸 초대 링크를 열어 이메일로 입장합니다.
		</p>
	</main>
</div>
