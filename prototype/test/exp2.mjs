import { chromium } from 'playwright'
const base = 'http://localhost:8000/slides'
const b = await chromium.launch({ channel: 'chrome' })
const ctx = await b.newContext({ viewport: { width: 400, height: 300 } })
const prof = await ctx.newPage(); await prof.goto(`${base}/presenter/1`)
const st = await ctx.newPage(); await st.goto(`${base}/1`)
const where = p => p.evaluate(() => location.pathname.split('/').pop() + ':' + (new URLSearchParams(location.search).get('clicks') || 0))
const r = {}
await prof.bringToFront(); await prof.waitForTimeout(800)
await prof.keyboard.press('ArrowRight'); await prof.waitForTimeout(500)
r.followed = await where(st)                       // 기대 2:0
await st.bringToFront()
await st.click('#follow-btn')
await st.keyboard.press('ArrowRight'); await st.keyboard.press('ArrowRight'); await st.keyboard.press('ArrowRight'); await st.keyboard.press('ArrowRight'); await st.waitForTimeout(300)
r.studentFree = await where(st)                    // 학생이 앞서 감 (2:3)
await prof.bringToFront()
await prof.keyboard.press('ArrowRight'); await prof.waitForTimeout(400)  // 교수 2:1
r.profMoved = await where(prof)
r.studentStaysAfterProfMoved = await where(st)     // 기대: 그대로 (교수가 움직여도 안 끌려감)
await st.bringToFront(); await st.waitForTimeout(200)
await st.click('#follow-btn'); await st.waitForTimeout(500)
r.afterReturn = await where(st)                    // 기대: 2:1 (교수 최신)
await prof.bringToFront(); await prof.keyboard.press('ArrowRight'); await prof.waitForTimeout(500)
r.followsAgain = await where(st)                   // 기대: 2:2
console.log(JSON.stringify(r, null, 1)); await b.close()
