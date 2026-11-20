<script lang="ts">
	import '../app.css';
	import { afterNavigate, goto } from '$app/navigation';
	import { page } from '$app/state';
	import { urlOutOfSync } from '#lib/auth.js';
	import AppHeader from '#lib/components/AppHeader.svelte';

	let { data, children } = $props();

	// 로그아웃한 뒤 뒤로 가기를 누르면 브라우저가 이전 주소(/courses)로 돌아가고, 가드가 로그인 화면으로 보낸다.
	// 이때 SvelteKit은 화면이 이미 로그인 화면이라 주소를 고치지 않아 주소와 화면이 어긋난다. 주소만 맞춘다.
	afterNavigate(() => {
		if (urlOutOfSync(page.url, location)) {
			goto(page.url.pathname + page.url.search, { shallow: true, replace: true });
		}
	});
</script>

<!-- 로그인 후 모든 화면에 공통 메뉴바. 수업 중 화면에는 따로 넣지 않는다 -->
{#if data.me}
	<AppHeader me={data.me} />
{/if}

{@render children()}
