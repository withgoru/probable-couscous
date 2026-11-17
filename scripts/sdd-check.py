#!/usr/bin/env python3
"""스펙 주도 개발 규칙 점검. 외부 패키지 없이 파이썬만 있으면 된다.

환경 변수 (CI가 채운다. 로컬에서는 생략 가능)
  HEAD_REF     PR의 브랜치 이름 (예: feat/001-T003-email-otp)
  BASE_REF     PR이 합쳐질 브랜치 (예: main). 있으면 커밋 기록도 점검
  ALLOW_DRAFT  true면 status: draft 허용 (Draft PR일 때)

점검 규칙
  R1 spec.md, plan.md, tasks.md에 status(draft|approved|stale)가 있다
  R2 draft는 Draft PR 안에서만 허용한다 (main에는 draft가 들어갈 수 없다)
  R3 앞 단계가 approved가 아니면 뒤 단계는 approved일 수 없다 (spec -> plan -> tasks)
  R4 feat/<번호>-T<nnn>-* 브랜치는 spec, plan, tasks가 모두 approved여야 하고,
     (Draft PR이 아니면) tasks.md에서 해당 작업이 체크되어 있어야 한다
  R5 status: approved로 바꾸는 커밋에 Claude 공동 작성자 표시가 있으면 실패한다
     (approved는 사용자만 바꾼다)
"""
import glob
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPECS = os.path.join(ROOT, "docs", "specs")
DOCS = ("spec", "plan", "tasks")
VALID = {"draft", "approved", "stale"}

errors = []


def frontmatter(path):
    text = open(path, encoding="utf-8").read()
    m = re.match(r"---\s*\n(.*?)\n---\s*\n", text, re.S)
    data = {}
    if m:
        for line in m.group(1).splitlines():
            if ":" in line and not line.lstrip().startswith("#"):
                k, v = line.split(":", 1)
                data[k.strip()] = v.split("#", 1)[0].strip()
    return data, text


def spec_dirs():
    out = []
    for d in sorted(glob.glob(os.path.join(SPECS, "[0-9][0-9][0-9]-*"))):
        if os.path.basename(d).startswith("000-"):
            continue
        if os.path.isdir(d):
            out.append(d)
    return out


def collect():
    info = {}
    for d in spec_dirs():
        sid = os.path.basename(d)
        info[sid] = {}
        for name in DOCS:
            p = os.path.join(d, name + ".md")
            if os.path.exists(p):
                fm, text = frontmatter(p)
                info[sid][name] = {"status": fm.get("status", ""), "path": p, "text": text}
    return info


def rel(p):
    return os.path.relpath(p, ROOT)


def check_docs(info, allow_draft):
    for sid, docs in info.items():
        for name, d in docs.items():
            st = d["status"]
            if st not in VALID:
                errors.append(f"R1 {rel(d['path'])}: status가 없거나 올바르지 않습니다 ('{st}'). draft, approved, stale 중 하나여야 합니다.")
            elif st == "draft" and not allow_draft:
                errors.append(f"R2 {rel(d['path'])}: status가 draft입니다. 읽고 approved로 바꾼 뒤 머지하세요. (검토 중이면 Draft PR로 여세요)")
        order = [("plan", "spec"), ("tasks", "plan")]
        for later, earlier in order:
            if later in docs and docs[later]["status"] == "approved":
                if earlier not in docs:
                    errors.append(f"R3 {sid}: {later}.md가 있는데 {earlier}.md가 없습니다.")
                elif docs[earlier]["status"] != "approved":
                    errors.append(f"R3 {sid}: {later}.md는 approved인데 {earlier}.md가 {docs[earlier]['status'] or '(status 없음)'}입니다. 앞 단계를 먼저 승인하세요.")


def check_branch(info, head_ref, allow_draft):
    m = re.match(r"^feat/(\d{3})-T(\d{3})-", head_ref or "")
    if not m:
        return
    number, task = m.group(1), "T" + m.group(2)
    sid = next((s for s in info if s.startswith(number + "-")), None)
    if not sid:
        errors.append(f"R4 브랜치 {head_ref}: 스펙 {number}-* 폴더가 docs/specs/에 없습니다.")
        return
    docs = info[sid]
    for name in DOCS:
        if name not in docs or docs[name]["status"] != "approved":
            cur = docs[name]["status"] if name in docs else "없음"
            errors.append(f"R4 브랜치 {head_ref}: {sid}/{name}.md가 approved가 아닙니다 ({cur}). 승인 전에는 구현하지 않습니다.")
    if allow_draft or "tasks" not in docs:
        return
    text = docs["tasks"]["text"]
    checked = re.search(r"^\s*-\s*\[[xX]\]\s*\*\*" + task + r"\b", text, re.M)
    if not checked:
        errors.append(f"R4 브랜치 {head_ref}: tasks.md에서 {task}가 체크되어 있지 않습니다. 완료한 작업은 체크한 뒤 PR을 Ready로 바꾸세요.")


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


def check_history(base_ref):
    if not base_ref:
        return
    rng = f"origin/{base_ref}..HEAD"
    r = git("log", "--format=%H", rng, "--", "docs/specs")
    if r.returncode != 0:
        print(f"참고: 커밋 기록을 읽지 못해 R5를 건너뜁니다 ({r.stderr.strip()[:80]})")
        return
    for h in r.stdout.split():
        body = git("log", "-1", "--format=%B", h).stdout
        diff = git("show", "-U0", "--format=", h, "--", "docs/specs").stdout
        if re.search(r"^\+status:\s*approved", diff, re.M) and re.search(r"co-authored-by:.*claude", body, re.I):
            errors.append(f"R5 커밋 {h[:7]}: status를 approved로 바꾼 커밋에 Claude 공동 작성자 표시가 있습니다. approved는 사용자가 직접 바꿔야 합니다.")


def main():
    allow_draft = os.environ.get("ALLOW_DRAFT", "").lower() == "true"
    head_ref = os.environ.get("HEAD_REF", "")
    base_ref = os.environ.get("BASE_REF", "")
    info = collect()
    check_docs(info, allow_draft)
    check_branch(info, head_ref, allow_draft)
    check_history(base_ref)
    n = sum(len(v) for v in info.values())
    if errors:
        print(f"sdd-check: 문제 {len(errors)}건 (문서 {n}개 점검)")
        for e in errors:
            print(" -", e)
        sys.exit(1)
    print(f"sdd-check: 이상 없음 (스펙 {len(info)}개, 문서 {n}개 점검)")


if __name__ == "__main__":
    main()
