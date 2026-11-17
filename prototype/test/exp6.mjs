import { chromium } from 'playwright'
const b = await chromium.launch({ channel: 'chrome' })
for (const [w, h] of [[1920, 1080], [1366, 768]]) {
  const p = await (await b.newContext({ viewport: { width: w, height: h } })).newPage()
  const errs = []; p.on('pageerror', e => errs.push(String(e)))
  await p.goto('http://localhost:8000/slides/presenter/2'); await p.waitForTimeout(1500)
  const r = await p.evaluate(() => {
    const box = e => { if (!e) return null; const r = e.getBoundingClientRect(); return { l: Math.round(r.left), r: Math.round(r.right), t: Math.round(r.top), b: Math.round(r.bottom) } }
    const panel = box(document.querySelector('#chat-panel'))
    // presenter 내부에서 가장 오른쪽까지 간 요소(패널 제외)
    let maxR = 0, over = []
    for (const e of document.querySelectorAll('body *')) { if (e.closest('#chat-panel')) continue; const q = e.getBoundingClientRect(); if (q.width && q.height && q.right <= innerWidth + 1) maxR = Math.max(maxR, q.right); if (q.width > 40 && q.height > 40 && q.right > panel.l + 1 && q.left < panel.l && q.right <= innerWidth) over.push(e.tagName + '.' + String(e.className).slice(0, 30)) }
    const slides = [...document.querySelectorAll('.slidev-slide-container, #slide-content')].map(box)
    return { panel, presenterRightMax: Math.round(maxR), crossing: over.slice(0, 5), slides: slides.slice(0, 3), viewport: innerWidth }
  })
  console.log(w + 'x' + h, JSON.stringify(r), errs)
  // 단축키: 방향키로 이동, 입력창 타이핑은 슬라이드를 넘기지 않는다
  const where = () => p.evaluate(() => location.pathname.split('/').pop() + ':' + (new URLSearchParams(location.search).get('clicks') || 0))
  await p.keyboard.press('ArrowRight'); await p.waitForTimeout(300); const a1 = await where()
  await p.click('#chat-panel input'); await p.keyboard.press('ArrowRight'); await p.keyboard.type('ok'); await p.waitForTimeout(300)
  console.log('  nav', a1, 'afterTypingInChat', await where(), 'value=', await p.inputValue('#chat-panel input'))
  await p.screenshot({ path: `exp6-${w}.png` })
}
await b.close()
