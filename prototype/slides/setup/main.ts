// 자체 sync 애드온: Slidev 공유 상태(page/clicks)를 FastAPI WebSocket에 연결한다.
// 학생(viewer)은 받기만 한다. 따라가기/직접 보기는 syncDirections.viewerReceive로 전환한다.
import { addSyncMethod, disableBuiltinSync } from '@slidev/client'
import { defineAppSetup } from '@slidev/types'

declare global { interface Window { __proto: any } }

export default defineAppSetup(() => {
  const q = new URLSearchParams(location.search)
  const isProf = location.pathname.includes('/presenter')
  const role = isProf ? 'prof' : 'student'
  const dirs = JSON.parse(localStorage.getItem('slidev-sync-directions') || '{}')
  localStorage.setItem('slidev-sync-directions', JSON.stringify({ ...dirs, viewerSend: false, viewerReceive: true, presenterSend: true, presenterReceive: false }))

  disableBuiltinSync() // BroadcastChannel/localStorage 동기화 끔
  const stats: any = { received: [], follow: true }
  window.__proto = stats
  let ws: WebSocket
  const onUpdateRef: { fn?: (d: any) => void } = {}
  let latest: any = null
  stats.latest = () => latest
  stats.applyLatest = () => latest && onUpdateRef.fn?.(latest)

  addSyncMethod({
    init(channelKey, onUpdate, _state, persist) {
      if (persist || !channelKey.endsWith('shared')) return undefined
      onUpdateRef.fn = (d) => onUpdate(d)
      ws = new WebSocket(`ws://${location.host.replace(/:\d+$/, '')}:${q.get('wsport') || 8000}/ws?role=${role}`)
      ws.onmessage = (e) => {
        const d = JSON.parse(e.data)
        stats.received.push({ page: d.page, clicks: d.clicks, t: Date.now() })
        latest = d
        if (stats.follow || isProf) onUpdate(d)
      }
      return (state) => {
        if (role === 'prof' && ws?.readyState === 1)
          ws.send(JSON.stringify({ page: state.page, clicks: state.clicks, clicksTotal: state.clicksTotal, lastUpdate: state.lastUpdate, sent: Date.now() }))
      }
    },
  })
})

// 실험 6: presenter 화면에 채팅 패널을 붙인다 (오른쪽 360px, presenter 영역은 그만큼 줄임)
if (location.pathname.includes('/presenter')) {
  window.addEventListener('DOMContentLoaded', () => {
    const aside = document.createElement('aside')
    aside.id = 'chat-panel'
    aside.setAttribute('aria-label', '학생 질문')
    aside.innerHTML = `<h2>질문</h2><ul><li><b>하늘</b> 3번째 줄이 이해가 안 돼요</li><li><b>바다</b> 예시 하나 더 보여주세요</li></ul><input aria-label="답글" placeholder="답글 입력" />`
    const st = document.createElement('style')
    st.textContent = `#chat-panel{position:fixed;top:0;right:0;bottom:0;width:360px;background:#fffaff;color:#1e1b18;border-left:1px solid #8a8480;z-index:9999;padding:12px;display:flex;flex-direction:column;gap:8px}
    #chat-panel input{min-height:44px;border:1px solid #8a8480;padding:0 8px}
    #app{width:calc(100vw - 360px)!important}`
    document.head.append(st); document.body.append(aside)
  })
}
