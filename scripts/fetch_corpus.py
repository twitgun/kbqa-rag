#!/usr/bin/env python
"""拉取 FastAPI 中文文档语料。

两种来源：
  --source git  : 从 GitHub 仓库取 docs/zh 原始 Markdown（结构最完整，首选项）
  --source web  : 从 fastapi.tiangolo.com/zh 抓渲染页 HTML（GitHub 不通时的兜底）
  --source auto : 先试 git，失败自动回退 web（默认）

用法：
  python scripts/fetch_corpus.py --source auto
  python scripts/fetch_corpus.py --source web --delay 0.2
  python scripts/fetch_corpus.py --source git --repo https://github.com/fastapi/fastapi.git

产物：
  data/corpus_raw/*.html   （web 模式）
  data/corpus_raw/*.md     （git 模式）
  data/corpus_snapshot.json
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "corpus_raw"
SNAPSHOT = DATA / "corpus_snapshot.json"

BASE = "https://fastapi.tiangolo.com"
SITEMAP = f"{BASE}/sitemap.xml"

# 需要的章节（顶层页用 "" 表示）
KEEP_SECTIONS = {"", "tutorial", "advanced", "deployment"}
KEEP_TOP = {"features", "learn", "python-types", "async", "environment-variables",
            "virtual-environments", "index"}

# 明确排除（社区/版本/赞助类，非技术知识）
DROP_PATTERNS = (
    "release-notes", "contributing", "help-fastapi", "benchmarks", "fastapi-people",
    "newsletter", "management", "sponsor", "external-links", "translations",
    "about", "resources", "project-generation", "alternatives", "index.md",
)

UA = "kbqa-corpus-fetcher/1.0 (+graduation project; polite, 5 req/s max)"


def log(msg: str) -> None:
    print(msg, flush=True)


def slug_of(url: str) -> str:
    """https://.../zh/tutorial/cors/ -> tutorial__cors"""
    p = urlparse(url).path.strip("/")
    p = re.sub(r"^zh/?", "", p)
    if not p:
        return "index"
    return p.replace("/", "__")


def is_wanted(url: str) -> bool:
    path = urlparse(url).path.strip("/")
    parts = path.split("/")
    if len(parts) == 1:
        return parts[0] in KEEP_TOP
    if parts[0] not in KEEP_SECTIONS:
        return False
    tail = parts[-1]
    return not any(d in tail for d in DROP_PATTERNS)


# ---------------------------------------------------------------- git 模式
def fetch_git(repo: str, keep_tmp: bool = False) -> int:
    tmp = DATA / ".tmp_repo"
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    log(f"[git] 浅克隆 {repo} ...")
    cmd = ["git", "clone", "--depth", "1", "--filter=blob:none",
           "--sparse", repo, str(tmp)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        log(f"[git] 克隆失败：{r.stderr.strip()[:300]}")
        return 0

    subprocess.run(["git", "-C", str(tmp), "sparse-checkout", "set", "docs/zh"],
                   capture_output=True, text=True)
    src = tmp / "docs" / "zh" / "docs"
    if not src.exists():
        log("[git] 未找到 docs/zh/docs，仓库结构与预期不符")
        return 0

    try:
        commit = subprocess.run(["git", "-C", str(tmp), "rev-parse", "HEAD"],
                                capture_output=True, text=True).stdout.strip()
    except Exception:
        commit = "unknown"

    RAW.mkdir(parents=True, exist_ok=True)
    n = 0
    for md in sorted(src.rglob("*.md")):
        rel = md.relative_to(src).as_posix()
        if any(d in rel for d in DROP_PATTERNS):
            continue
        section = rel.split("/")[0] if "/" in rel else ""
        if section and section not in KEEP_SECTIONS:
            continue
        if not section and md.stem not in KEEP_TOP:
            continue
        dst = RAW / (rel.replace("/", "__"))
        dst.write_text(md.read_text(encoding="utf-8"), encoding="utf-8")
        n += 1

    write_snapshot({"source": "git", "repo": repo, "commit": commit, "files": n})
    if not keep_tmp:
        shutil.rmtree(tmp, ignore_errors=True)
    log(f"[git] 完成，{n} 篇 -> {RAW}")
    return n


# ---------------------------------------------------------------- web 模式
def fetch_web(delay: float = 0.2) -> int:
    log("[web] 读取 sitemap ...")
    with httpx.Client(timeout=30, headers={"User-Agent": UA}, follow_redirects=True) as c:
        sm = c.get(SITEMAP).text
        urls = re.findall(r"<loc>([^<]+)</loc>", sm)
        log(f"[web] sitemap 共 {len(urls)} 条（英文站），映射到 /zh/")

        targets: list[str] = []
        for u in urls:
            path = urlparse(u).path.strip("/")
            if not is_wanted(u):
                continue
            targets.append(f"{BASE}/zh/{path}/" if path else f"{BASE}/zh/")

        targets = sorted(set(targets))
        log(f"[web] 待抓 {len(targets)} 页")

        RAW.mkdir(parents=True, exist_ok=True)
        ok, miss, fail = 0, 0, 0
        for i, u in enumerate(targets, 1):
            name = slug_of(u) + ".html"
            dst = RAW / name
            try:
                r = c.get(u)
                if r.status_code == 404:
                    miss += 1
                    log(f"  [{i}/{len(targets)}] 404（未翻译） {u}")
                    continue
                r.raise_for_status()
                dst.write_text(r.text, encoding="utf-8")
                ok += 1
                log(f"  [{i}/{len(targets)}] ok {name} ({len(r.text)//1024}KB)")
            except Exception as e:
                fail += 1
                log(f"  [{i}/{len(targets)}] 失败 {u}：{e}")
            time.sleep(delay)

    write_snapshot({"source": "web", "base": BASE, "ok": ok, "missing": miss,
                    "failed": fail, "files": ok})
    log(f"[web] 完成：成功 {ok}，404 {miss}，失败 {fail} -> {RAW}")
    return ok


def write_snapshot(payload: dict) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    payload = {
        **payload,
        "fetched_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "license": "MIT (FastAPI docs)",
    }
    SNAPSHOT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"[snapshot] {SNAPSHOT}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["auto", "git", "web"], default="auto")
    ap.add_argument("--repo", default="https://github.com/fastapi/fastapi.git")
    ap.add_argument("--delay", type=float, default=0.2)
    ap.add_argument("--keep-tmp", action="store_true")
    args = ap.parse_args()

    if args.source in ("auto", "git"):
        n = fetch_git(args.repo, args.keep_tmp)
        if n > 0 or args.source == "git":
            return 0 if n > 0 else 1
        log("[auto] git 不可用，回退 web")

    n = fetch_web(args.delay)
    return 0 if n > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
