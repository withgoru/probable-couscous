<script lang="ts">
	import { onMount, tick } from 'svelte';
	import { ApiError, notifyProfessor, resendCode, verifyCode } from '#lib/api.js';
	import Icon from '#lib/components/Icon.svelte';

	// 학생 입장 2: 코드 단계(AC25, AC26, AC30~AC33, AC44). 메일 코드와 교수님이 알려 주는 코드를 같은 칸에 입력한다.
	// 규칙(횟수, 만료, 기기 묶음)은 서버가 판단하고, 화면은 서버의 안내를 그대로 보인다.
	let {
		token,
		email,
		waitSeconds,
		onVerified,
		onBack,
		onClosed,
		onNotOnRoster
	}: {
		token: string;
		email: string;
		waitSeconds: number; // 다시 받기까지 남은 초(서버가 알려 준 값)
		onVerified: (nickname: string) => void;
		onBack: () => void;
		onClosed: (message: string) => void; // 그사이 링크가 폐기됐거나 강좌가 보관됐다
		onNotOnRoster: (message: string) => void; // 코드를 받은 뒤 명단에서 빠졌다
	} = $props();

	const LOST = '연결이 끊겼습니다. 다시 연결되면 이어서 진행합니다.';
	const NOTIFIED_FALLBACK = '교수님께 알렸습니다. 교수님이 알려 주는 코드를 입력하세요.';

	let code = $state('');
	let keepLogin = $state(true); // '이 기기에서 로그인 유지'는 처음부터 켜져 있다(AC26)
	let codeError = $state<string | null>(null);
	let helpError = $state<string | null>(null);
	let info = $state<string | null>(null); // 새 코드를 보냈다, 교수님께 알렸다
	let notified = $state(false);
	let lost = $state(false);
	let busy = $state<'verify' | 'resend' | 'notify' | null>(null);
	let codeInput = $state<HTMLInputElement | null>(null);

	// 다시 받기 카운트다운. 남은 초는 마감 시각에서 계산해 탭이 잠시 멈춰도 어긋나지 않는다
	let deadline = 0;
	let remaining = $state(0);
	const tickDown = () => (remaining = Math.max(0, Math.ceil((deadline - Date.now()) / 1000)));
	function startCountdown(seconds: number) {
		deadline = Date.now() + Math.max(0, seconds) * 1000;
		tickDown();
	}

	onMount(() => {
		startCountdown(waitSeconds);
		const timer = setInterval(tickDown, 250);
		const offline = () => (lost = true);
		const online = () => (lost = false);
		window.addEventListener('offline', offline);
		window.addEventListener('online', online);
		return () => {
			clearInterval(timer);
			window.removeEventListener('offline', offline);
			window.removeEventListener('online', online);
		};
	});

	/** 모든 요청의 공통 실패 처리. 처리했으면 true. 연결 문제는 입력을 그대로 두고 이어서 진행한다고 알린다. */
	function common(e: unknown): boolean {
		if (e instanceof ApiError && (e.status === 404 || e.status === 403)) {
			onClosed(e.message);
			return true;
		}
		if (!(e instanceof ApiError)) {
			lost = true;
			return true;
		}
		return false;
	}

	function onCodeInput(event: Event) {
		// 복사한 코드의 공백이나 하이픈은 버리고 숫자만 6자리까지 남긴다
		const input = event.currentTarget as HTMLInputElement;
		code = input.value.replace(/\D/g, '').slice(0, 6);
		input.value = code;
		codeError = null;
	}

	// 붙여 넣은 글에서 6자리 코드를 찾는다. 메일 첫 줄이나 제목을 통째로 복사해도 강좌 이름의 숫자가 섞이지 않게,
	// 앞뒤가 숫자가 아닌 6자리(가운데 공백·하이픈 하나는 허용)만 코드로 본다
	const PASTED_CODE = /(?<!\d)(\d{3})[\s-]?(\d{3})(?!\d)/;

	function onCodePaste(event: ClipboardEvent) {
		const found = event.clipboardData?.getData('text')?.match(PASTED_CODE);
		if (!found) return; // 코드 전체가 아니면 평소처럼 넣고 onCodeInput이 숫자만 남긴다
		event.preventDefault(); // 쳐 둔 숫자 뒤에 이어 붙지 않고 붙여 넣은 코드로 바꾼다
		code = found[1] + found[2];
		(event.currentTarget as HTMLInputElement).value = code;
		codeError = null;
	}

	async function submit(event: SubmitEvent) {
		event.preventDefault();
		if (busy) return;
		if (code.length !== 6) {
			codeError = '6자리를 모두 입력해 주세요.';
			codeInput?.focus();
			return;
		}
		busy = 'verify';
		codeError = null;
		try {
			const res = await verifyCode(token, { email, code, keep_login: keepLogin });
			lost = false;
			if (res.next === 'notice') onVerified(res.nickname);
			else onNotOnRoster(res.message);
		} catch (e) {
			if (common(e)) return;
			lost = false;
			codeError = (e as ApiError).message;
			code = ''; // 틀린 코드는 지우고 바로 다시 쓰게 한다
			await tick();
			codeInput?.focus();
		} finally {
			busy = null;
		}
	}

	async function resend() {
		if (busy || remaining > 0) return;
		busy = 'resend';
		helpError = null;
		info = null;
		try {
			const res = await resendCode(token, email);
			lost = false;
			if (res.next !== 'code') {
				onNotOnRoster(res.message);
				return;
			}
			startCountdown(res.wait_seconds);
			code = '';
			codeError = null;
			notified = false; // 새 코드가 나오면 교수님 목록의 이전 코드는 사라진다. 다시 알릴 수 있다
			info = '새 코드를 보냈습니다. 이전 코드는 쓸 수 없습니다.';
		} catch (e) {
			if (common(e)) return;
			lost = false;
			const err = e as ApiError;
			if (err.status === 429 && typeof err.data?.wait_seconds === 'number') startCountdown(err.data.wait_seconds);
			else helpError = err.message;
		} finally {
			busy = null;
		}
	}

	async function notify() {
		if (busy) return;
		busy = 'notify';
		helpError = null;
		info = null;
		try {
			const res = await notifyProfessor(token, email);
			lost = false;
			notified = true;
			info = res.message || NOTIFIED_FALLBACK;
			await tick();
			codeInput?.focus(); // 교수님이 알려 주는 코드를 같은 칸에 입력한다
		} catch (e) {
			if (common(e)) return;
			lost = false;
			helpError = (e as ApiError).message;
		} finally {
			busy = null;
		}
	}
</script>

<div class="flex flex-col gap-2">
	<h1 tabindex="-1" class="text-2xl leading-tight font-bold outline-none">인증 코드를 입력하세요</h1>
	<!-- '으로/로'는 주소 끝 글자에 따라 달라져 틀리기 쉬워서 조사 없이 쓴다 -->
	<p class="text-sm text-muted-foreground">6자리 코드를 보냈습니다: <span class="break-all">{email}</span></p>
</div>

<div class="alert alert-info">
	<Icon name="info-circle" />
	<div class="alert-title leading-6 font-medium">코드는 지금 이 화면을 연 기기에서 입력해야 합니다.</div>
</div>

<!-- 상태 알림은 한곳에서 읽어 준다: 연결 끊김이 가장 급하다 -->
{#if lost}
	<div role="status" class="alert alert-warning">
		<Icon name="warning-circle" />
		<div class="alert-title leading-6 font-medium">{LOST}</div>
	</div>
{:else if info}
	<div role="status" class="alert alert-info">
		<Icon name="check" />
		<div class="alert-title leading-6 font-medium">{info}</div>
	</div>
{/if}

<!-- maxlength는 두지 않는다: 브라우저가 공백까지 세어 "123 456"의 마지막 숫자를 막는다. 6자리 제한은 onCodeInput이 한다 -->
<form class="flex flex-col gap-5" onsubmit={submit} novalidate>
	<div class="flex flex-col gap-2">
		<label for="join-code" class="label">인증 코드 6자리</label>
		<input
			id="join-code"
			type="text"
			inputmode="numeric"
			autocomplete="one-time-code"
			placeholder="000000"
			class="input h-[72px] text-center font-mono text-4xl font-semibold tracking-[0.3em]"
			bind:this={codeInput}
			value={code}
			oninput={onCodeInput}
			onpaste={onCodePaste}
			aria-invalid={codeError ? 'true' : undefined}
			aria-describedby={codeError ? 'join-code-error' : undefined}
		/>
		{#if codeError}
			<p id="join-code-error" class="flex items-start gap-1.5 text-sm font-medium text-destructive-strong">
				<Icon name="warning-circle" class="mt-0.5 size-4 shrink-0" />{codeError}
			</p>
		{/if}
	</div>

	<label for="join-keep" class="flex min-h-11 cursor-pointer items-center gap-3 text-sm font-medium">
		<input id="join-keep" type="checkbox" class="size-5 accent-primary" bind:checked={keepLogin} />
		이 기기에서 로그인 유지
	</label>

	<button type="submit" class="btn btn-default btn-lg w-full" disabled={busy === 'verify'}>
		{busy === 'verify' ? '확인하는 중…' : '확인하고 계속'}
	</button>
</form>

<section class="card gap-3 py-4" aria-labelledby="join-help-title">
	<div class="card-content flex flex-col gap-3">
		<div class="flex flex-col gap-0.5">
			<h2 id="join-help-title" class="text-sm font-semibold">메일이 오지 않나요?</h2>
			<p class="text-sm text-muted-foreground">스팸함도 확인해 주세요. 계속 오지 않으면 교수님께 알려 주세요.</p>
		</div>
		{#if helpError}
			<p role="alert" class="flex items-start gap-2 text-sm font-medium text-destructive-strong">
				<Icon name="warning-circle" class="mt-0.5 size-4 shrink-0" />{helpError}
			</p>
		{/if}
		<div class="flex flex-col gap-2">
			<button
				type="button"
				class="btn btn-outline w-full"
				disabled={remaining > 0 || busy === 'resend'}
				aria-describedby={remaining > 0 ? 'join-resend-wait' : undefined}
				onclick={resend}
			>
				{busy === 'resend' ? '보내는 중…' : '코드 다시 받기'}
			</button>
			{#if remaining > 0}
				<!-- 남은 초를 글로 보인다(AC32). 1초마다 바뀌어 읽어 주는 도구가 계속 읽지 않도록 알림 영역에 두지 않는다 -->
				<p id="join-resend-wait" class="text-center text-sm text-muted-foreground">
					{remaining}초 뒤에 다시 받을 수 있습니다.
				</p>
			{/if}
			<button type="button" class="btn btn-outline w-full" onclick={onBack}>이메일 다시 입력</button>
			{#if !notified}
				<button type="button" class="btn btn-outline w-full" disabled={busy === 'notify'} onclick={notify}>
					{busy === 'notify' ? '알리는 중…' : '교수님께 알리기'}
				</button>
			{/if}
		</div>
	</div>
</section>
