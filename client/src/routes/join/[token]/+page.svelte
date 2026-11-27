<script lang="ts">
	import { tick } from 'svelte';
	import { ApiError, submitJoinEmail, type JoinAnswer } from '#lib/api.js';
	import AccessRequestForm from '#lib/components/AccessRequestForm.svelte';
	import CodeStep from '#lib/components/CodeStep.svelte';
	import Icon from '#lib/components/Icon.svelte';
	import NoticeStep from '#lib/components/NoticeStep.svelte';
	import StudentClass from '#lib/components/StudentClass.svelte';
	import type { PageProps } from './$types';

	// 학생 입장 1: 이메일 단계, 링크 상태, 입장 요청(AC10, AC22, AC24, AC38, AC39, AC42, AC43).
	// 학생 입장 2: 코드 단계는 CodeStep(T027). 학생 입장 3: 채팅 이용 안내는 NoticeStep, 입장 완료(AC27, AC28).
	// 로그인 유지 중인 기기는 load가 알려 준 상태(AC35, AC37)에서 바로 시작한다.
	let { data }: PageProps = $props();

	type Step = 'email' | 'code' | 'request' | 'result' | 'notice' | 'entered';
	type Notice = { message: string; tone: 'info' | 'warning' | 'destructive' };

	// 같은 규칙을 서버도 검사한다(roster.is_valid_email). 여기서는 서버에 묻기 전에 바로 알려 주려고 쓴다
	const EMAIL = /^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$/;

	// 처음 단계는 이 기기의 상태로 정한다. 함수로 읽는 것은 처음 값만 쓰겠다는 뜻이다(이후 단계는 화면이 바꾼다)
	const startingMe = () => (data.invite.open ? data.invite.me : { state: 'login' as const });
	let step = $state<Step>(startingMe().state === 'login' ? 'email' : (startingMe().state as Step));
	let closedLater = $state<string | null>(null); // 화면을 연 뒤에 링크가 폐기됐거나 강좌가 보관됐다
	let email = $state('');
	let sentTo = $state(''); // 서버에 보낸(정리한) 이메일
	let waitSeconds = $state(60); // 코드 다시 받기까지 남은 초
	let codeKey = $state(0); // 이메일을 다시 보내면 코드 단계를 새로 시작한다
	let nickname = $state(startingMe().state === 'login' ? '' : (startingMe() as { nickname: string }).nickname);
	// 입장하면 서버가 알려 주는 강좌 번호. 수업 화면이 수업 연결과 상태에 쓴다(002)
	let classroomId = $state<number | null>(startingMe().state === 'entered' ? (startingMe() as { classroom_id: number }).classroom_id : null);
	let emailError = $state<string | null>(null);
	let formError = $state<string | null>(null);
	let sending = $state(false);
	let answer = $state<(Notice & { canRequest: boolean }) | null>(null); // 이메일 단계에서 받은 안내
	let result = $state<(Notice & { canGoBack: boolean }) | null>(null); // 입장 요청 뒤의 안내
	let emailInput = $state<HTMLInputElement | null>(null);
	// 수업 중에 입장이 끝났다(명단에서 빠짐, 로그인 끊김, 002 AC44). 입장 화면에서 그 이유를 보인다
	let goneMessage = $state<string | null>(null);
	const GONE_DEFAULT = '이 수업을 더 볼 수 없습니다. 이메일로 다시 입장해 주세요.';

	function onGone(message: string | null) {
		goneMessage = message ?? GONE_DEFAULT;
		classroomId = null;
		void go('email');
	}

	const closedMessage = $derived(closedLater ?? (data.invite.open ? null : data.invite.message));
	const classroom = $derived(data.invite.open ? data.invite.classroom : null);
	const title = $derived(
		classroom ? `${classroom.name}${classroom.section_name ? ` · ${classroom.section_name}` : ''}` : null
	);

	const tone = (next: JoinAnswer['next']): Notice['tone'] =>
		next === 'rejected' ? 'destructive' : next === 'request_access' ? 'warning' : 'info';

	async function go(next: Step, focus: 'heading' | 'email' = 'heading') {
		step = next;
		await tick();
		// 화면이 바뀐 것을 읽어 주는 도구에도 알리려고 새 제목으로 포커스를 옮긴다. 이메일로 돌아오면 바로 고칠 수 있게 칸으로
		(focus === 'email' ? emailInput : document.querySelector<HTMLElement>('main h1'))?.focus();
	}

	function onEmailInput() {
		emailError = null;
		formError = null;
		goneMessage = null;
		answer = null; // 이전 이메일에 대한 안내는 더 이상 맞지 않는다
	}

	async function submitEmail(event: SubmitEvent) {
		event.preventDefault();
		if (sending) return;
		const value = email.trim();
		formError = null;
		answer = null;
		emailError = !value ? '이메일을 입력해 주세요.' : EMAIL.test(value) ? null : '이메일 형식을 확인해 주세요.';
		if (emailError) {
			emailInput?.focus();
			return;
		}
		sending = true;
		try {
			const res = await submitJoinEmail(data.token, value);
			sentTo = value;
			if (res.next === 'code') {
				waitSeconds = res.wait_seconds;
				codeKey += 1;
				await go('code');
			} else {
				answer = { message: res.message, tone: tone(res.next), canRequest: res.next === 'request_access' };
			}
		} catch (e) {
			if (e instanceof ApiError && (e.status === 404 || e.status === 403)) {
				closedLater = e.message;
			} else if (e instanceof ApiError && e.status === 429 && typeof e.data?.wait_seconds === 'number') {
				// 방금 이 이메일로 코드를 보냈다. 막지 않고 그 코드를 입력하게 한다(다시 받기는 남은 시간 뒤에)
				sentTo = value;
				waitSeconds = e.data.wait_seconds;
				codeKey += 1;
				await go('code');
			} else if (e instanceof ApiError && e.field === 'email') {
				emailError = e.message;
				emailInput?.focus();
			} else {
				formError =
					e instanceof ApiError
						? e.message
						: '인증 코드를 요청하지 못했습니다. 네트워크 연결을 확인하고 다시 시도해 주세요.';
			}
		} finally {
			sending = false;
		}
	}

	function onRequestAnswer(res: JoinAnswer) {
		if (res.next === 'code') return; // 입장 요청은 코드 단계를 돌려주지 않는다
		result = { message: res.message, tone: tone(res.next), canGoBack: res.next === 'already_on_roster' };
		go('result');
	}

	async function onVerified(name: string) {
		nickname = name;
		await go('notice');
	}

	function onNotOnRoster(message: string) {
		// 코드를 받은 뒤 명단에서 빠졌다. 이메일 단계에서 명단 밖 안내와 입장 요청을 보인다
		answer = { message, tone: 'warning', canRequest: true };
		go('email', 'email');
	}

	async function onEntered(res: { nickname: string; classroom: string; classroom_id: number }) {
		nickname = res.nickname; // 강좌는 안내 화면과 같은 이름(분반 포함)으로 보인다
		classroomId = res.classroom_id;
		await go('entered');
	}

	function onNeedLogin(message: string) {
		// 그사이 로그인이 끊겼거나 끝났다(AC20). 이메일 인증부터 다시 한다
		formError = message;
		go('email', 'email');
	}

	function backToEmail() {
		answer = null;
		result = null;
		go('email', 'email');
	}
</script>

<svelte:head>
	<title>{title ? `${title} 입장` : '입장할 수 없습니다'} · 강의 상호작용 도구</title>
</svelte:head>

{#snippet noticeBox(n: Notice)}
	<div role="status" class="alert alert-{n.tone}">
		<Icon name={n.tone === 'destructive' ? 'warning-circle' : 'info-circle'} />
		<div class="alert-title leading-6 font-medium">{n.message}</div>
	</div>
{/snippet}

<!-- 학생 화면: 휴대폰 한 손 사용을 기준으로 한 열. 390px 폭에서 가로 스크롤이 없어야 한다(AC51) -->
<main class="mx-auto flex min-h-dvh w-full max-w-md flex-col gap-6 px-6 pt-10 pb-8">
	{#if closedMessage}
		<h1 tabindex="-1" class="text-2xl leading-tight font-bold outline-none">입장할 수 없습니다</h1>
		<div class="alert alert-destructive">
			<Icon name="warning-circle" />
			<div class="alert-title leading-6 font-medium">{closedMessage}</div>
		</div>
	{:else if step === 'email'}
		<div class="flex flex-col gap-2">
			<span class="flex items-center gap-1.5 text-sm text-muted-foreground">
				<Icon name="link" class="size-4" />초대 링크로 들어왔습니다
			</span>
			<h1 tabindex="-1" class="text-2xl leading-tight font-bold outline-none">
				{title}<br />수업에 입장
			</h1>
			<p class="text-sm text-muted-foreground">수강생 명단에 있는 이메일로 입장합니다. 가입은 필요 없습니다.</p>
		</div>

		{#if goneMessage}
			<div role="alert" class="alert alert-warning">
				<Icon name="warning-circle" />
				<div class="alert-title leading-6 font-medium">{goneMessage}</div>
			</div>
		{/if}
		<!-- novalidate: 브라우저 기본 말풍선 대신 칸 옆에 한국어 안내를 보인다 -->
		<form class="flex flex-col gap-6" onsubmit={submitEmail} novalidate>
			<div class="flex flex-col gap-2">
				<label for="join-email" class="label">이메일</label>
				<input
					id="join-email"
					type="email"
					inputmode="email"
					autocomplete="email"
					class="input input-lg"
					placeholder="이메일 주소를 입력하세요"
					bind:this={emailInput}
					bind:value={email}
					oninput={onEmailInput}
					aria-invalid={emailError ? 'true' : undefined}
					aria-describedby={emailError ? 'join-email-error' : undefined}
				/>
				{#if emailError}
					<p id="join-email-error" class="flex items-start gap-1.5 text-sm font-medium text-destructive-strong">
						<Icon name="warning-circle" class="mt-0.5 size-4 shrink-0" />{emailError}
					</p>
				{/if}
			</div>
			{#if formError}
				<p role="alert" class="flex items-start gap-2 text-sm font-medium text-destructive-strong">
					<Icon name="warning-circle" class="mt-0.5 size-4 shrink-0" />{formError}
				</p>
			{/if}
			<button type="submit" class="btn btn-default btn-lg w-full" disabled={sending}>
				{#if !sending}<Icon name="mail" />{/if}{sending ? '보내는 중…' : '인증 코드 받기'}
			</button>
		</form>

		{#if answer}
			<div class="flex flex-col gap-3">
				{@render noticeBox(answer)}
				{#if answer.canRequest}
					<button type="button" class="btn btn-outline btn-lg w-full" onclick={() => go('request')}>
						입장 요청 보내기
					</button>
				{/if}
			</div>
		{/if}
	{:else if step === 'code'}
		{#key codeKey}
			<CodeStep
				token={data.token}
				email={sentTo}
				{waitSeconds}
				{onVerified}
				onBack={backToEmail}
				onClosed={(message) => (closedLater = message)}
				{onNotOnRoster}
			/>
		{/key}
	{:else if step === 'request'}
		<div class="flex flex-col gap-2">
			<h1 tabindex="-1" class="text-2xl leading-tight font-bold outline-none">입장 요청 보내기</h1>
			<p class="text-sm text-muted-foreground">
				이름과 학번을 적어 보내면 교수님이 확인한 뒤 수강생 명단에 추가합니다.
			</p>
		</div>
		<AccessRequestForm
			token={data.token}
			email={sentTo}
			onAnswer={onRequestAnswer}
			onClosed={(message) => (closedLater = message)}
		/>
		<button type="button" class="btn btn-outline btn-lg w-full" onclick={backToEmail}>이메일 다시 입력</button>
	{:else if step === 'notice'}
		<NoticeStep
			token={data.token}
			classroom={title ?? ''}
			{nickname}
			{onEntered}
			onClosed={(message) => (closedLater = message)}
			{onNeedLogin}
		/>
	{:else if step === 'entered' && classroomId !== null}
		<!-- 입장 완료(001 AC28) 뒤는 수업 화면이다: 수업이 없으면 대기, 있으면 슬라이드와 자료(002) -->
		<StudentClass {classroomId} title={title ?? ''} {nickname} {onGone} />
	{:else if step === 'result' && result}
		<h1 tabindex="-1" class="text-2xl leading-tight font-bold outline-none">입장 요청</h1>
		{@render noticeBox(result)}
		{#if result.canGoBack}
			<button type="button" class="btn btn-default btn-lg w-full" onclick={backToEmail}>이메일 다시 입력</button>
		{/if}
	{/if}
</main>
