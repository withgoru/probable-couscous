/**
 * 수업 동기화 다리(002 plan "iframe과의 대화").
 *
 * 슬라이드는 수업 화면(같은 출처의 부모 창) 안 iframe에서 돈다. 이 파일은 부모와 postMessage로만 대화하고,
 * 연결이나 인증은 하지 않는다. 부모가 지시한 이동만 하고, 그 밖의 이동(키보드, 스와이프, 주소 바꾸기)은
 * 막은 뒤 방향만 `deck:intent`로 알린다. 따라가기를 풀지, 범위 안인지는 부모가 판단한다(spec AC26).
 *
 * 부모 → 슬라이드
 *   deck:goto   { slide, click }        그 위치로 이동(범위 밖이면 범위 끝으로)
 *   deck:limit  { slide, click } | null 볼 수 있는 마지막 위치(가장 멀리 간 위치). null이면 제한 없음
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

  let allowed = false
  let limit: Position | null = null

  const current = (): Position => ({ slide: nav.currentSlideNo.value, click: nav.clicks.value })

  nav.router.beforeEach((to) => {
    if (allowed)
      return true
    const target = targetOf(to.path, to.query)
    const here = current()
    // 같은 자리로 가는 이동(Slidev가 처음 뜰 때 주소를 맞추는 것)은 넘기려 한 것이 아니다. 막기만 하고 알리지 않는다
    if (target && (target.slide !== here.slide || target.click !== here.click))
      post({ type: 'deck:intent', direction: before(target, here) ? 'prev' : 'next' })
    return false
  })

  async function goto(position: Position) {
    let target = { slide: Math.max(1, Math.floor(position.slide)), click: Math.max(0, Math.floor(position.click)) }
    if (limit && before(limit, target))
      target = { ...limit }
    allowed = true
    try {
      await nav.go(target.slide, target.click, true)
    }
    finally {
      allowed = false
    }
  }

  window.addEventListener('message', (event) => {
    if (event.origin !== origin || event.source !== window.parent)
      return
    const message = event.data ?? {}
    if (message.type === 'deck:goto')
      void goto({ slide: Number(message.slide), click: Number(message.click ?? 0) })
    else if (message.type === 'deck:limit')
      limit = message.limit ? { slide: Number(message.limit.slide), click: Number(message.limit.click) } : null
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
