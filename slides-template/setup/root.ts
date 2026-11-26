/**
 * 수업 동기화 다리(002 plan "iframe과의 대화").
 *
 * 슬라이드는 수업 화면(같은 출처의 부모 창) 안 iframe에서 돈다. 이 파일은 부모와 postMessage로만 대화하고,
 * 연결이나 인증은 하지 않는다. 부모가 지시한 이동만 하고, 그 밖의 이동(키보드, 스와이프, 주소 바꾸기)은
 * 막은 뒤 방향만 `deck:intent`로 알린다. 따라가기를 풀지, 넘겨 볼 수 있는지는 부모가 판단한다(spec AC26, AC27).
 *
 * 부모 → 슬라이드
 *   deck:goto   { slide, click }        그 위치로 이동
 *   deck:mode   { mode }                follow | browse | present (표시용. 이동 규칙은 같다)
 * 슬라이드 → 부모
 *   deck:ready  { total }               처음 그릴 준비가 됨
 *   deck:moved  { slide, click, clicksTotal, total }  위치가 바뀜(clicksTotal은 현재 슬라이드의 단계 수)
 *   deck:intent { direction }           next | prev. 사용자가 넘기려 했지만 막았다
 */
import { useNav } from '@slidev/client'
import { defineRootSetup } from '@slidev/types'
import { watch } from 'vue'

type Position = { slide: number, click: number }

const HIDE_CONTROLS = `
#page-root nav, #slidev-goto-dialog { display: none !important; }
`

function before(a: Position, b: Position): boolean {
  return a.slide < b.slide || (a.slide === b.slide && a.click < b.click)
}

function targetOf(path: string, query: Record<string, unknown>): Position | null {
  const slide = Number(path.replace(/^\//, '').split('/')[0])
  if (!Number.isInteger(slide) || slide < 1)
    return null
  const raw = Array.isArray(query.clicks) ? query.clicks[0] : query.clicks
  const click = Number(raw ?? 0)
  return { slide, click: Number.isFinite(click) && click > 0 ? Math.floor(click) : 0 }
}

export default defineRootSetup(() => {
  if (window.parent === window)
    return // 혼자 열었을 때(교수가 미리 볼 때)는 평소의 Slidev로 둔다

  const nav = useNav()
  const origin = location.origin
  const post = (message: Record<string, unknown>) => window.parent.postMessage(message, origin)

  const style = document.createElement('style')
  style.textContent = HIDE_CONTROLS
  document.head.appendChild(style)

  // 부모가 지시해 진행 중인 이동의 목적지와 그 수. 지시가 겹쳐도(교수가 빠르게 두 번 넘김) 앞의 것이 끝나며
  // 뒤의 것을 막지 않게 수로 센다. 그 사이 사용자가 밀거나 키를 눌러 생긴 다른 곳으로의 이동은 여전히 막는다
  // (비공개 묶음을 따라가는 학생이 혼자 넘기지 않게)
  const ordered = new Map<string, number>()
  const keyOf = (p: Position) => `${p.slide}:${p.click}`

  const current = (): Position => ({ slide: nav.currentSlideNo.value, click: nav.clicks.value })

  nav.router.beforeEach((to) => {
    const target = targetOf(to.path, to.query)
    if (target && ordered.has(keyOf(target)))
      return true
    const here = current()
    // 같은 자리로 가는 이동(Slidev가 처음 뜰 때 주소를 맞추는 것)은 넘기려 한 것이 아니다. 막기만 하고 알리지 않는다
    if (target && (target.slide !== here.slide || target.click !== here.click))
      post({ type: 'deck:intent', direction: before(target, here) ? 'prev' : 'next' })
    return false
  })

  async function goto(position: Position) {
    const target = { slide: Math.max(1, Math.floor(position.slide)), click: Math.max(0, Math.floor(position.click)) }
    const key = keyOf(target)
    ordered.set(key, (ordered.get(key) ?? 0) + 1)
    try {
      await nav.go(target.slide, target.click, true)
    }
    finally {
      const left = (ordered.get(key) ?? 1) - 1
      if (left > 0)
        ordered.set(key, left)
      else
        ordered.delete(key)
    }
  }

  window.addEventListener('message', (event) => {
    if (event.origin !== origin || event.source !== window.parent)
      return
    const message = event.data ?? {}
    if (message.type === 'deck:goto')
      void goto({ slide: Number(message.slide), click: Number(message.click ?? 0) })
    else if (message.type === 'deck:mode')
      document.documentElement.dataset.classroomMode = String(message.mode)
  })

  watch(
    [nav.currentSlideNo, nav.clicks, nav.clicksTotal],
    ([slide, click, clicksTotal]) => post({ type: 'deck:moved', slide, click, clicksTotal, total: nav.total.value }),
    { immediate: true },
  )
  post({ type: 'deck:ready', total: nav.total.value })
})
