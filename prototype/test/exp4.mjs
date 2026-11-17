// 실험 4: N명이 동시에 접속 -> 거의 동시에 출석코드 -> 퀴즈 제출. 응답 지연과 유실 측정
import WebSocket from 'ws'
const N = +process.argv[2] || 200, JIT = +process.argv[3] || 0 // 제출 분산(ms), 0이면 완전 동시
const URL = 'ws://localhost:8000/ws'
const socks = await Promise.all(Array.from({ length: N }, (_, i) => new Promise(r => { const w = new WebSocket(URL); w.on('open', () => r(w)) })))
const pend = new Map()
socks.forEach(w => w.on('message', d => { const m = JSON.parse(d); if (m.t === 'ack' && pend.has(m.ref)) { pend.get(m.ref)(m); pend.delete(m.ref) } }))
const send = (w, msg) => new Promise(res => { const ref = Math.random().toString(36).slice(2); const t0 = performance.now(); pend.set(ref, m => res({ ms: performance.now() - t0, ok: m.ok })); w.send(JSON.stringify({ ...msg, ref })) })
const stat = a => { a = a.map(x => x.ms).sort((x, y) => x - y); return { p50: +a[a.length >> 1].toFixed(1), p95: +a[Math.floor(a.length * .95)].toFixed(1), max: +a.at(-1).toFixed(1) } }
const jit = () => new Promise(r => setTimeout(r, Math.random() * JIT))
const a = await Promise.all(socks.map(async (w, i) => { await jit(); return send(w, { t: 'attend', id: 's' + i, code: '4827' }) }))
const q = await Promise.all(socks.map(async (w, i) => { await jit(); return send(w, { t: 'quiz', id: 's' + i, q: 1, a: 'B' }) }))
const bad = await send(socks[0], { t: 'attend', id: 'x', code: '0000' })
const st = await (await fetch('http://localhost:8000/stats')).json()
console.log(JSON.stringify({ N, JIT, attend: { ...stat(a), acked: a.filter(x => x.ok).length }, quiz: { ...stat(q), acked: q.filter(x => x.ok).length }, wrongCodeRejected: !bad.ok, db: st }))
process.exit(0)
