// 실험 1·2·3: 실제 브라우저로 교수 presenter + N개 학생 화면
import { chromium } from 'playwright'
const N = +process.argv[2] || 5
const base = 'http://localhost:8000/slides'
const b = await chromium.launch({ channel: 'chrome' })
const ctx = await b.newContext({ viewport: { width: 320, height: 240 } })
const prof = await ctx.newPage()
await prof.goto(`${base}/presenter/1`)
const studs = []
for (let i = 0; i < N; i++) {
  const p = await ctx.newPage()
  await p.goto(`${base}/1`)
  studs.push(p)
}
await prof.waitForTimeout(1500)
// 각 학생에 폴러 설치: 현재 (page,clicks) 변화를 시각과 함께 기록
for (const p of studs) await p.evaluate(() => {
  window.__log = []
  const cur = () => `${location.pathname.split('/').filter(Boolean).pop()}:${new URLSearchParams(location.search).get('clicks') || 0}`
  let last = cur()
  const loop = () => { const c = cur(); if (c !== last) { last = c; window.__log.push([c, performance.timeOrigin + performance.now()]) } requestAnimationFrame(loop) }
  loop()
})
await prof.bringToFront()
const steps = ['2:0', '2:1', '2:2', '2:3', '3:0']
const lat = []
for (const want of steps) {
  const t0 = Date.now()
  await prof.keyboard.press('ArrowRight')
  await prof.waitForTimeout(2500)
  for (const p of studs) {
    const log = await p.evaluate(() => window.__log)
    const hit = log.find(([c]) => c === want)
    lat.push(hit ? hit[1] - t0 : null)
  }
  await prof.evaluate(() => 0)
}
const ok = lat.filter(x => x != null).sort((a, b) => a - b)
const lost = lat.length - ok.length
console.log(JSON.stringify({ N, samples: lat.length, lost, p50: ok[Math.floor(ok.length / 2)], p95: ok[Math.floor(ok.length * .95)], max: ok.at(-1) }))
// 학생 최종 위치 확인
console.log('final', await studs[0].evaluate(() => location.pathname + location.search))
await b.close()
