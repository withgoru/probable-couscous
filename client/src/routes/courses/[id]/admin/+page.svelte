<script lang="ts">
	import { onMount } from 'svelte';
	import { invalidate } from '$app/navigation';
	import { connectAdmin, type AdminEvent, type LiveStatus } from '#lib/adminLive.js';
	import {
		fetchJoinRequests,
		fetchPendingAuth,
		type ClassSession,
		type JoinRequest,
		type PendingAuth
	} from '#lib/api.js';
	import ErrorNotice from '#lib/components/ErrorNotice.svelte';
	import Icon from '#lib/components/Icon.svelte';
	import InviteCard from '#lib/components/InviteCard.svelte';
	import JoinRequestsSection from '#lib/components/JoinRequestsSection.svelte';
	import PendingAuthSection from '#lib/components/PendingAuthSection.svelte';
	import RosterSection from '#lib/components/RosterSection.svelte';
	import SessionPicker from '#lib/components/SessionPicker.svelte';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();

	const HINTS: Record<number, string> = {
		403: '다른 교수님의 강좌입니다. 내 강좌 목록에서 열어 주세요.',
		404: '주소를 확인하거나 내 강좌 목록에서 열어 주세요.'
	};
	const RETRY_HINT = '다시 연결되면 자동으로 다시 불러옵니다.';

	// 입장 요청과 대기 중인 인증은 실시간 연결이 준비된 뒤에 불러온다(T023의 ready). 대기 중인 인증은 부를 때마다
	// 코드 열람이 기록되므로 그 목록이 바뀌었다는 이벤트가 올 때만 다시 부른다
	let requests = $state<JoinRequest[] | null>(null);
	let pending = $state<PendingAuth[] | null>(null);
	let requestsError = $state<string | null>(null);
	let pendingError = $state<string | null>(null);
	let live = $state<LiveStatus | 'connecting'>('connecting');
	let now = $state(new Date()); // 대기 중인 인증의 만료 표시를 위한 시계

	// 회차 선택(002). 고르지 않았으면 진행 중인 회차, 없으면 아직 시작하지 않은 첫 회차, 그것도 없으면 마지막 회차
	let chosenId = $state<number | null>(null);
	const sessions = $derived<ClassSession[]>(data.sessions ?? []);
	function defaultSession(list: ClassSession[]): number | null {
		const pick = list.find((s) => s.status === 'live') ?? list.find((s) => s.status === 'scheduled') ?? list.at(-1);
		return pick?.id ?? null;
	}
	const selectedId = $derived(
		chosenId !== null && sessions.some((s) => s.id === chosenId) ? chosenId : defaultSession(sessions)
	);

	async function loadRequests(id: number) {
		try {
			requests = await fetchJoinRequests(id);
			requestsError = null;
		} catch {
			requestsError = `입장 요청을 불러오지 못했습니다. ${RETRY_HINT}`;
		}
	}

	async function loadPending(id: number) {
		try {
			pending = await fetchPendingAuth(id);
			pendingError = null;
		} catch {
			pendingError = `대기 중인 인증을 불러오지 못했습니다. ${RETRY_HINT}`;
		}
	}

	function onEvent(id: number, event: AdminEvent) {
		if (event.type.startsWith('join_request.')) loadRequests(id);
		else if (event.type.startsWith('pending_auth.')) loadPending(id);
		else if (event.type === 'roster.updated') invalidate('app:roster');
		else if (event.type === 'resync') {
			loadRequests(id);
			loadPending(id);
			invalidate('app:roster');
		}
	}

	onMount(() => {
		const id = data.classroom?.id;
		if (id === undefined) return;
		const clock = setInterval(() => (now = new Date()), 15_000);
		const stop = connectAdmin(id, {
			onReady: () => {
				loadRequests(id);
				loadPending(id);
			},
			onEvent: (event) => onEvent(id, event),
			onStatus: (status) => {
				live = status;
				if (status === 'never-connected') {
					// 실시간 연결이 안 돼도 목록은 한 번 보여 준다
					loadRequests(id);
					loadPending(id);
				}
			}
		});
		return () => {
			clearInterval(clock);
			stop();
		};
	});

	function onDecided(outcome: 'approved' | 'rejected' | 'stale') {
		const id = data.classroom?.id;
		if (id === undefined) return;
		loadRequests(id);
		if (outcome !== 'rejected') invalidate('app:roster'); // 승인하면 명단에 추가된다(AC41)
	}
</script>

<svelte:head><title>관리 페이지 · 강의 상호작용 도구</title></svelte:head>

<main class="mx-auto flex max-w-5xl flex-col gap-4 px-6 py-8 sm:px-8">
	{#if data.notice}
		<ErrorNotice title={data.notice.message} hint={HINTS[data.notice.status]} />
		<a href="/courses" class="btn btn-outline self-start">내 강좌로 돌아가기</a>
	{:else if data.classroom}
		<div class="flex flex-wrap items-start justify-between gap-4">
			<div class="flex flex-col gap-1">
				<h1 class="text-3xl font-bold tracking-tight">관리 페이지</h1>
				<p class="text-muted-foreground">{data.classroom.name}</p>
			</div>
			<SessionPicker
				classroomId={data.classroom.id}
				{sessions}
				{selectedId}
				onChanged={() => invalidate('app:sessions')}
				onSelect={(id) => (chosenId = id)}
			/>
		</div>
		{#if live === 'reconnecting' || live === 'never-connected'}
			<div role="status" class="alert alert-warning">
				<Icon name="warning-circle" />
				<div class="alert-title leading-6 font-medium">
					실시간 연결이 끊겼습니다. 다시 연결하는 중입니다. 그동안 새 요청은 자동으로 나타나지 않습니다.
				</div>
			</div>
		{/if}
		<!-- 수업 중에 학생이 기다리는 일이라 맨 위에 둔다 -->
		<div class="grid gap-4 lg:grid-cols-2">
			<JoinRequestsSection classroomId={data.classroom.id} {requests} loadError={requestsError} {onDecided} />
			<PendingAuthSection items={pending} {now} loadError={pendingError} />
		</div>
		{#if data.invite}
			<InviteCard
				classroomId={data.classroom.id}
				invite={data.invite}
				onChanged={() => invalidate('app:invite')}
			/>
		{/if}
		{#if data.roster}
			<RosterSection
				classroomId={data.classroom.id}
				roster={data.roster}
				onChanged={() => invalidate('app:roster')}
			/>
		{/if}
	{/if}
</main>
