<script lang="ts">
	import { ApiError, enterClassroom } from '#lib/api.js';
	import Icon, { type IconName } from '#lib/components/Icon.svelte';
	import NicknameCard from '#lib/components/NicknameCard.svelte';

	// 학생 입장 3: 채팅 이용 안내와 '확인하고 입장'(AC27, AC28). 안내 3줄은 AC27 문장 그대로 쓰고 '익명'이라는 말은 쓰지 않는다(C10)
	let {
		token,
		classroom,
		nickname,
		onEntered,
		onClosed,
		onNeedLogin
	}: {
		token: string;
		classroom: string;
		nickname: string;
		onEntered: (result: { nickname: string; classroom: string; classroom_id: number }) => void;
		onClosed: (message: string) => void; // 보관됐거나 명단에서 빠졌거나 링크가 폐기됐다
		onNeedLogin: (message: string) => void; // 그사이 로그인이 끊겼거나 끝났다
	} = $props();

	const LINES: { icon: IconName; text: string }[] = [
		{ icon: 'eye-closed', text: '다른 학생에게는 닉네임으로만 보입니다.' },
		{ icon: 'key', text: '교수님은 심각한 사안에 한해 사유를 기록하고 작성자를 확인할 수 있습니다.' },
		{ icon: 'shield-check', text: '채팅 내용은 참여 점수에 반영되지 않고 공개되지 않습니다.' }
	];

	let entering = $state(false);
	let problem = $state<string | null>(null);

	async function enter() {
		if (entering) return;
		entering = true;
		problem = null;
		try {
			const res = await enterClassroom(token);
			onEntered({ nickname: res.nickname, classroom: res.classroom, classroom_id: res.classroom_id });
		} catch (e) {
			if (e instanceof ApiError && e.status === 401) onNeedLogin(e.message);
			else if (e instanceof ApiError && (e.status === 403 || e.status === 404)) onClosed(e.message);
			else
				problem =
					e instanceof ApiError ? e.message : '입장하지 못했습니다. 네트워크 연결을 확인하고 다시 시도해 주세요.';
		} finally {
			entering = false;
		}
	}
</script>

<div class="flex flex-col gap-1">
	<span class="text-sm text-muted-foreground">{classroom}</span>
	<h1 tabindex="-1" class="text-2xl leading-tight font-bold outline-none">입장하기 전에 확인해 주세요</h1>
</div>

<NicknameCard {nickname} />

<section class="card gap-4 py-5" aria-labelledby="notice-title">
	<div class="card-header"><h2 id="notice-title" class="card-title">채팅 이용 안내</h2></div>
	<ul class="card-content flex flex-col gap-4 text-sm">
		{#each LINES as line (line.text)}
			<li class="flex gap-3">
				<Icon name={line.icon} class="mt-0.5 size-5 text-muted-foreground" />
				<span>{line.text}</span>
			</li>
		{/each}
	</ul>
</section>

{#if problem}
	<p role="alert" class="flex items-start gap-2 text-sm font-medium text-destructive-strong">
		<Icon name="warning-circle" class="mt-0.5 size-4 shrink-0" />{problem}
	</p>
{/if}

<button type="button" class="btn btn-default btn-lg w-full" disabled={entering} onclick={enter}>
	{entering ? '입장하는 중…' : '확인하고 입장'}
</button>
