import { chromium } from 'playwright'
const b = await chromium.launch({ channel: 'chrome' })
for (const [w, h] of [[1920, 1080], [1280, 720], [1024, 768]]) {
  const p = await (await b.newContext({ viewport: { width: w, height: h } })).newPage()
  await p.goto('http://localhost:8000/slides/2?projector=1&clicks=3'); await p.waitForTimeout(1200)
  const r = await p.evaluate(() => {
    const box = e => { const r = e.getBoundingClientRect(); return { l: Math.round(r.left), r: Math.round(r.right), t: Math.round(r.top), b: Math.round(r.bottom) } }
    const side = box(document.querySelector('#proj-side'))
    const cands = ['#slide-content', '#slide-container', '.slidev-page'].map(s => [s, document.querySelector(s)]).filter(([, e]) => e).map(([s, e]) => [s, box(e)])
    // 슬라이드 글자가 실제로 사이드바 왼쪽에 있는지: 텍스트 노드 범위 기준
    const rng = document.createRange(); const ts = []
    for (const e of document.querySelectorAll('.slidev-page h1, .slidev-page li')) { rng.selectNodeContents(e); const q = rng.getBoundingClientRect(); ts.push(Math.round(q.right)) }
    return { side, cands, textRightMax: Math.max(...ts), sideCoversTop: document.elementFromPoint(side.l + 5, 300)?.closest('#proj-side') != null }
  })
  const slide = r.cands.find(c => c[0] === '#slide-container')?.[1]
  r.overlap = slide ? slide.r > r.side.l + 1 : 'n/a'
  console.log(w + 'x' + h, JSON.stringify(r))
  if (w === 1920) await p.screenshot({ path: 'exp3-1920.png' })
}
await b.close()
