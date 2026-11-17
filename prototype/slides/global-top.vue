<script setup lang="ts">
// 실험 3: 프로젝터 오버레이. ?projector=1 일 때만 오른쪽 사이드바를 붙이고 슬라이드 영역을 줄인다.
import { onMounted, ref } from 'vue'
const on = ref(false)
const code = ref('4827')
const follow = ref(true)
const student = ref(false)
function toggle(e: Event) {
  (e.currentTarget as HTMLElement).blur() // 포커스가 남으면 방향키가 막힌다
  const st = (window as any).__proto
  follow.value = !follow.value
  st.follow = follow.value
  if (follow.value) st.applyLatest() // 돌아오기: 교수 최신 위치로 이동
}
onMounted(() => {
  on.value = new URLSearchParams(location.search).has('projector')
  student.value = !on.value && !location.pathname.includes('/presenter')
  if (on.value) document.documentElement.style.setProperty('--side', '280px')
})
</script>
<template>
  <Teleport to="body"><aside v-if="on" id="proj-side" aria-label="출석코드">
    <p>출석코드</p>
    <strong>{{ code }}</strong>
  </aside></Teleport>
  <button v-if="student" id="follow-btn" @click="toggle">{{ follow ? '직접 넘겨 보기' : '교수 화면으로 돌아가기' }}</button>
</template>
<style>
#follow-btn { position: fixed; left: 8px; top: 8px; z-index: 9999; min-height: 44px; padding: 0 12px; background: #0a2463; color: #fffaff; border-radius: 6px; }
#proj-side { position: fixed; top: 0; right: 0; bottom: 0; width: 280px; background: #1e1b18; color: #fffaff;
  z-index: 9999; display: flex; flex-direction: column; align-items: center; justify-content: center; }
#proj-side strong { font-size: 64px; letter-spacing: 8px; }
html[style*="--side"] #app, html[style*="--side"] #slideshow { width: calc(100vw - var(--side)) !important; }
</style>
