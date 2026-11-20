<script lang="ts">
	import Icon from '#lib/components/Icon.svelte';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();

	const stats = $derived([
		{ label: '진행 중 강좌', value: data.counts.active },
		{ label: '보관된 강좌', value: data.counts.archived },
		{ label: '진행 중 수강생', value: data.active_students }
	]);
	const openName = (name: string, section: string | null) => `열기: ${name}${section ? ` (${section})` : ''}`;
</script>

<svelte:head><title>마이페이지 · 강의 상호작용 도구</title></svelte:head>

<main class="mx-auto flex max-w-5xl flex-col gap-6 px-6 py-8 sm:px-8">
	<h1 class="text-3xl font-bold tracking-tight">마이페이지</h1>

	<section class="card" aria-label="프로필">
		<div class="card-content flex items-center gap-4">
			<span class="avatar size-12" aria-hidden="true">
				<span class="avatar-fallback">{data.login.slice(0, 1).toUpperCase()}</span>
			</span>
			<div class="flex flex-col gap-0.5">
				<p class="text-lg font-semibold">@{data.login}</p>
				<p class="flex items-center gap-1.5 text-sm text-muted-foreground">
					<Icon name="github" class="size-4" />GitHub 계정으로 로그인됨
				</p>
			</div>
		</div>
	</section>

	<section aria-label="요약" class="grid gap-4 sm:grid-cols-3">
		{#each stats as stat (stat.label)}
			<div class="card" data-stat>
				<div class="card-content flex flex-col gap-1">
					<p class="text-sm text-muted-foreground">{stat.label}</p>
					<p class="text-3xl font-bold tabular-nums">{stat.value}</p>
				</div>
			</div>
		{/each}
	</section>

	<section class="flex flex-col gap-3">
		<h2 class="text-xl font-semibold">진행 중 강좌</h2>
		{#if data.active_classrooms.length === 0}
			<p class="text-sm text-muted-foreground">
				진행 중인 강좌가 없습니다. <a href="/courses" class="underline">내 강좌에서 만들기</a>
			</p>
		{:else}
			<ul class="flex flex-col gap-3">
				{#each data.active_classrooms as classroom (classroom.id)}
					<li class="card">
						<div class="card-content flex flex-wrap items-center justify-between gap-3">
							<div class="flex min-w-0 flex-col gap-0.5">
								<h3 class="font-semibold">{classroom.name}</h3>
								<p class="text-sm text-muted-foreground">
									<span>{classroom.section_name ?? '분반 없음'}</span> · 수강생 {classroom.student_count}명
								</p>
							</div>
							<a
								href="/courses/{classroom.id}/admin"
								class="btn btn-default"
								aria-label={openName(classroom.name, classroom.section_name)}>열기</a
							>
						</div>
					</li>
				{/each}
			</ul>
		{/if}
	</section>
</main>
