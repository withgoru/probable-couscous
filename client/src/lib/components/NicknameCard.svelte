<script lang="ts">
	// 이 강좌에서 쓰는 닉네임(자동으로 정해지고 학생이 바꿀 수 없다, AC29). 안내 화면과 입장 완료 화면이 같이 쓴다
	let { nickname }: { nickname: string } = $props();
</script>

<div class="card py-4">
	<div class="card-content flex items-center gap-3">
		<!-- 첫 글자는 꾸밈이다. 닉네임은 옆 글자가 전달한다 -->
		<span class="avatar size-11" aria-hidden="true"><span class="avatar-fallback text-base">{nickname.charAt(0)}</span></span>
		<div class="flex min-w-0 flex-col">
			<span class="text-xs text-muted-foreground">이 수업에서 쓰는 닉네임</span>
			<span class="text-base font-semibold break-all">{nickname}</span>
		</div>
	</div>
</div>
