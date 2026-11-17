// 실험 5: 연결이 끊겼다 복구될 때 놓친 메시지 복원. mode=drop(클라이언트 끊김) | restart(서버 재시작)
import WebSocket from 'ws'
import { spawn } from 'node:child_process'
const N = +process.argv[2] || 200, MODE = process.argv[3] || 'drop', TOTAL = 100
const sleep = ms => new Promise(r => setTimeout(r, ms))
const base = (await (await fetch('http://localhost:8000/stats')).json()).msgs
const prof = new WebSocket('ws://localhost:8000/ws?role=prof'); await new Promise(r => prof.on('open', r))
class C {
  constructor(i) { this.i = i; this.last = base; this.got = []; this.connect() }
  connect() {
    this.ws = new WebSocket(`ws://localhost:8000/ws?since=${this.last}`)
    this.ws.on('message', d => { const m = JSON.parse(d); if (m.t === 'notice') { this.got.push(m.seq); this.last = Math.max(this.last, m.seq) } })
    this.ws.on('error', () => {}); this.ws.on('close', () => { if (this.auto) setTimeout(() => this.connect(), 300 + Math.random() * 500) })
  }
}
const cs = Array.from({ length: N }, (_, i) => new C(i)); await sleep(800)
let sent = 0; const sendOne = () => prof.send(JSON.stringify({ t: 'notice', n: ++sent }))
let proc
if (MODE === 'drop') {
  const dropped = cs.filter((_, i) => i % 2 === 0)
  for (let k = 0; k < TOTAL; k++) {
    if (k === 20) dropped.forEach(c => { c.ws.terminate() })            // 20번째에서 절반 끊김
    if (k === 70) dropped.forEach((c, i) => setTimeout(() => c.connect(), Math.random() * 500)) // 70번째 이후 복구
    sendOne(); await sleep(20)
  }
} else {
  cs.forEach(c => c.auto = true)
  for (let k = 0; k < TOTAL; k++) {
    if (k === 30) { await new Promise(r => { spawn('pkill', ['-f', 'uvicorn server:app']).on('close', r) }); }
    if (k === 60) { proc = spawn(process.cwd() + '/../.venv/bin/uvicorn', ['server:app', '--port', '8000', '--log-level', 'warning'], { cwd: '..', env: { ...process.env, PROTO_DB: 'proto.db' }, stdio: 'ignore', detached: true }); proc.unref(); await sleep(1500); // 교수도 재접속
      prof.removeAllListeners(); const p2 = new WebSocket('ws://localhost:8000/ws?role=prof'); await new Promise(r => p2.on('open', r)); prof.send = m => p2.send(m) }
    if (k >= 30 && k < 60) { sent++; } else sendOne()                   // 서버가 죽은 구간의 교수 메시지는 서버에 도달 못 함(교수 클라이언트 쪽 재시도 범위)
    await sleep(20)
  }
}
await sleep(3000)
const want = (await (await fetch('http://localhost:8000/stats')).json()).msgs - base
let lost = 0, dup = 0, disorder = 0, perfect = 0
for (const c of cs) {
  const s = new Set(c.got); dup += c.got.length - s.size
  const expected = Array.from({ length: want }, (_, k) => base + 1 + k)
  lost += expected.filter(x => !s.has(x)).length
  if (c.got.some((x, i) => i && x < c.got[i - 1])) disorder++
  if (expected.every(x => s.has(x)) && c.got.length === want) perfect++
}
console.log(JSON.stringify({ N, MODE, serverStored: want, lostTotal: lost, duplicates: dup, clientsOutOfOrder: disorder, clientsPerfect: perfect }))
process.exit(0)
