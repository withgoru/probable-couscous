import WebSocket from 'ws'
const N = +process.argv[2]
const open = (role) => new Promise(r => { const w = new WebSocket(`ws://localhost:8000/ws?role=${role}`); w.on('open', () => r(w)) })
const prof = await open('prof'); const studs = await Promise.all(Array.from({ length: N }, () => open('student')))
const lat = []
for (let k = 0; k < 20; k++) {
  const t0 = performance.now()
  const got = studs.map(s => new Promise(r => s.once('message', () => r(performance.now() - t0))))
  prof.send(JSON.stringify({ page: k, clicks: 0, clicksTotal: 0 }))
  lat.push(...await Promise.all(got))
}
lat.sort((a, b) => a - b)
console.log(JSON.stringify({ N, samples: lat.length, p50: +lat[lat.length >> 1].toFixed(1), p95: +lat[Math.floor(lat.length * .95)].toFixed(1), max: +lat.at(-1).toFixed(1) }))
process.exit(0)
