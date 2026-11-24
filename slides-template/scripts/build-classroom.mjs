#!/usr/bin/env node
/**
 * 수업 도구에 올릴 슬라이드 묶음(zip)을 만든다(002 plan "슬라이드 형식").
 *
 *   npm run build:classroom                         # 이 폴더의 slides.md → classroom-deck.zip
 *   npm run build:classroom -- ../강의/3주차/slides.md   # 다른 곳의 슬라이드
 *   npm run build:classroom -- slides.md --out 3주차.zip
 *
 * 하는 일
 * 1. 슬라이드 폴더를 `.build/deck/`에 복사하고 이 템플릿의 동기화 다리(`setup/root.ts`)를 넣는다.
 *    슬라이드 폴더에 다른 `setup/root.ts`가 있어도 다리로 바꾼다(다리가 없으면 수업 화면이 따라가지 못한다).
 * 2. 머리말에 수업용 설정이 있는지 확인한다(routerMode: hash, 외부 글꼴·파비콘 끄기).
 * 3. 고정 기준 경로 `/__deck__/`, 노트 빼고 빌드한다. 서버가 올릴 때 묶음별 경로로 바꾼다.
 * 4. 슬라이드별 제목과 노트를 `classroom-deck.json`에 따로 담는다(교수 화면에만 나간다).
 * 5. 빌드 결과와 노트 파일을 zip 하나로 묶는다.
 */
import { spawnSync } from 'node:child_process'
import { cpSync, existsSync, mkdirSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs'
import { basename, dirname, join, relative, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'
import { load } from '@slidev/parser/fs'
import { zipSync } from 'fflate'

const TEMPLATE = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const STAGE = join(TEMPLATE, '.build')
const BASE = '/__deck__/'
const META_NAME = 'classroom-deck.json'
const SKIP = new Set(['node_modules', 'dist', '.build', '.slidev', '.git'])
const DROP_FROM_BUILD = new Set(['404.html', '_redirects']) // hash 방식이라 쓰지 않는다
const FIXED_TIME = new Date('2026-01-01T00:00:00Z') // 같은 입력이면 같은 zip

function fail(message) {
  rmSync(STAGE, { recursive: true, force: true })
  console.error(`\n오류: ${message}\n`)
  process.exit(1)
}

function parseArgs(argv) {
  const args = { entry: join(TEMPLATE, 'slides.md'), out: null }
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--entry')
      args.entry = resolve(argv[++i])
    else if (argv[i] === '--out')
      args.out = resolve(argv[++i])
    else if (!argv[i].startsWith('--'))
      args.entry = resolve(argv[i])
  }
  args.out ??= join(dirname(args.entry), 'classroom-deck.zip')
  return args
}

function checkHeadmatter(headmatter) {
  const problems = []
  if (headmatter.routerMode !== 'hash')
    problems.push('routerMode: hash')
  if (headmatter.fonts?.provider !== 'none')
    problems.push('fonts:\n  provider: none')
  if (headmatter.favicon !== false)
    problems.push('favicon: false')
  if (problems.length) {
    fail(`슬라이드 맨 위 머리말(--- 사이)에 다음 설정을 넣어 주세요. 템플릿의 slides.md 머리말을 그대로 복사하면 됩니다.\n\n${problems.join('\n')}`)
  }
}

function listFiles(root) {
  const files = []
  const walk = (dir) => {
    for (const name of readdirSync(dir)) {
      const full = join(dir, name)
      if (statSync(full).isDirectory())
        walk(full)
      else
        files.push(full)
    }
  }
  walk(root)
  return files.sort()
}

const { entry, out } = parseArgs(process.argv.slice(2))
if (!existsSync(entry))
  fail(`슬라이드 파일을 찾을 수 없습니다: ${entry}`)

// 1. 복사하고 다리 넣기
rmSync(STAGE, { recursive: true, force: true })
const deckDir = join(STAGE, 'deck')
const keep = src => !SKIP.has(basename(src)) && !src.endsWith('.zip')
mkdirSync(deckDir, { recursive: true })
for (const name of readdirSync(dirname(entry))) { // 항목별로 복사한다(이 폴더 자신을 빌드할 때 .build로 되돌아 복사하지 않게)
  const src = join(dirname(entry), name)
  if (keep(src))
    cpSync(src, join(deckDir, name), { recursive: true, filter: keep })
}
mkdirSync(join(deckDir, 'setup'), { recursive: true })
cpSync(join(TEMPLATE, 'setup', 'root.ts'), join(deckDir, 'setup', 'root.ts'))
const stagedEntry = join(deckDir, basename(entry))

// 2. 머리말 확인과 노트 뽑기
const data = await load(deckDir, stagedEntry)
checkHeadmatter(data.headmatter ?? {})
const slides = data.slides
  .filter(slide => !slide.frontmatter?.hide && !slide.frontmatter?.disabled)
  .map((slide, i) => ({ no: i + 1, title: slide.title ?? '', note: (slide.note ?? '').trim() }))
const meta = { format: 1, slide_count: slides.length, slides }

// 3. 빌드
const distDir = join(STAGE, 'dist')
const slidev = join(TEMPLATE, 'node_modules', '.bin', process.platform === 'win32' ? 'slidev.cmd' : 'slidev')
const result = spawnSync(slidev, ['build', stagedEntry, '--base', BASE, '--without-notes', '--out', distDir], {
  cwd: TEMPLATE,
  stdio: 'inherit',
  shell: process.platform === 'win32',
})
if (result.status !== 0)
  fail('Slidev 빌드에 실패했습니다. 위의 오류를 확인해 주세요. npm run dev로 슬라이드가 열리는지 먼저 확인하면 좋습니다.')

// 5. 묶기
const entries = {}
for (const file of listFiles(distDir)) {
  const name = relative(distDir, file).split(sep).join('/')
  if (!DROP_FROM_BUILD.has(name))
    entries[name] = [readFileSync(file), { mtime: FIXED_TIME }]
}
if (!entries['index.html'] || !entries['index.html'][0].toString('utf8').includes(BASE))
  fail('빌드 결과에 index.html이 없거나 기준 경로가 맞지 않습니다.')
entries[META_NAME] = [Buffer.from(`${JSON.stringify(meta, null, 2)}\n`), { mtime: FIXED_TIME }]
mkdirSync(dirname(out), { recursive: true })
writeFileSync(out, zipSync(entries, { level: 9 }))
rmSync(STAGE, { recursive: true, force: true })

const size = (statSync(out).size / 1024 / 1024).toFixed(2)
console.log(`\n만들었습니다: ${out}\n슬라이드 ${meta.slide_count}장, ${size}MB. 수업 도구의 관리 페이지 '이 회차의 자료'에서 올려 주세요.`)
