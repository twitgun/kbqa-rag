#!/usr/bin/env python
"""把抓下来的 HTML 清洗成可入库的 Markdown，并按规则选出 60 篇。

输入：data/corpus_raw/*.html（web 模式）或 *.md（git 模式）
输出：data/corpus/NN_slug.md + data/corpus_manifest.json

用法：
  python scripts/clean_corpus.py
  python scripts/clean_corpus.py --target-count 60 --min-chars 1500
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup
from markdownify import markdownify as md

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "corpus_raw"
OUT = ROOT / "data" / "corpus"
MANIFEST = ROOT / "data" / "corpus_manifest.json"

# 章节配额（总计 60）
QUOTA = {"top": 4, "tutorial": 28, "advanced": 20, "deployment": 8}

DROP_TOKENS = ("release-notes", "contributing", "help-fastapi", "benchmarks",
               "fastapi-people", "newsletter", "management", "sponsor",
               "external-links", "translations")


def log(msg: str) -> None:
    print(msg, flush=True)


# ---------------------------------------------------------------- HTML → MD
def cell_text(td) -> str:
    t = td.get_text(" ", strip=True).replace("|", "\\|").replace("\n", " ")
    return re.sub(r"\s+", " ", t)


def table_to_md(tbl) -> str:
    rows = tbl.find_all("tr")
    if not rows:
        return ""
    grid = []
    for tr in rows:
        cells = tr.find_all(["th", "td"])
        if cells:
            grid.append([cell_text(c) for c in cells])
    if not grid:
        return ""
    width = max(len(r) for r in grid)
    grid = [r + [""] * (width - len(r)) for r in grid]
    head, body = grid[0], grid[1:]
    lines = ["| " + " | ".join(head) + " |",
             "| " + " | ".join(["---"] * width) + " |"]
    lines += ["| " + " | ".join(r) + " |" for r in body]
    return "\n".join(lines)


def code_lang(el) -> str:
    for node in (el, el.parent, getattr(el.parent, "parent", None)):
        if node is None:
            continue
        cls = " ".join(node.get("class") or [])
        m = re.search(r"language-([A-Za-z0-9+#]+)", cls)
        if m:
            return m.group(1)
    return ""


def guess_lang(body: str) -> str:
    """渲染页不含 language-xxx 类，按内容猜语言（只影响展示，不影响检索）。"""
    if re.search(r"^\s*(from\s+\w+\s+import|import\s+\w+|def\s+\w+\s*\(|class\s+\w+\s*[:(])", body, re.M):
        return "python"
    if re.search(r"^\s*(pip|uvicorn|docker|git|python|uv|npm)\s", body, re.M) or body.lstrip().startswith("$ "):
        return "bash"
    s = body.strip()
    if s.startswith("{") or s.startswith("["):
        return "json"
    if re.search(r"^\s*<[a-zA-Z!/]", body, re.M):
        return "html"
    if ";" in body and "{" in body:
        return "javascript"
    return ""


def add_code_langs(text: str) -> str:
    """给没有语言标注的代码围栏补一个。"""
    def repl(m: re.Match) -> str:
        body = m.group(2)
        lang = guess_lang(body)
        return f"```{lang}\n{body}```"

    return re.sub(r"```([A-Za-z0-9+#]*)\n(.*?)```", repl, text, flags=re.S)


def strip_tags_in_code(text: str) -> str:
    """代码块里的终端颜色标签（<span style=...>、<font color=...>）只去标签留文本。"""
    def fix(m: re.Match) -> str:
        body = re.sub(r"</?(span|font|b|i|u)\b[^>]*>", "", m.group(2))
        return f"```{m.group(1)}\n{body}```"

    return re.sub(r"```([A-Za-z0-9+#]*)\n(.*?)```", fix, text, flags=re.S)


def clean_html(html: str, source_url: str) -> str | None:
    soup = BeautifulSoup(html, "lxml")
    art = soup.find("article", class_=re.compile("md-content__inner")) or soup.find("article")
    if art is None:
        return None

    # 噪声：编辑链接、源码链接、锚点、导航、脚本
    for sel in (".md-content__button", ".md-source-file", ".md-nav", "script",
                "style", "nav", ".headerlink", ".md-tags", ".md-typeset__scrollwrap",
                "input", "label", "svg"):
        for node in art.select(sel):
            node.decompose()

    # 代码 tab 容器：拆掉外层，保留内容（否则会残留 div 与重复 tab 名）
    for sel in ("div.tabbed-set", "div.tabbed-content", "div.tabbed-block",
                "div.tabbed-labels", "div.tabbed-labels", "div.highlight"):
        for node in art.select(sel):
            node.unwrap()

    # 广告/赞助 admonition 整块删除
    for node in art.select("div.admonition, details.admonition, div.tip"):
        text = node.get_text(" ", strip=True)[:80]
        if "赞助" in text or "Sponsor" in text or "sponsored" in text.lower():
            node.decompose()
            continue
        title = node.find(class_=re.compile("admonition-title"))
        if title and ("赞助" in title.get_text() or "Sponsor" in title.get_text()):
            node.decompose()

    # 翻译声明折叠块（每页都有，与内容无关）
    for node in art.find_all("details"):
        head = node.find("summary")
        head_text = head.get_text(" ", strip=True) if head else ""
        if "翻译" in head_text or "AI" in head_text:
            node.decompose()

    # 链接只留文字（避免 markdownify 输出一堆带 target 的链接）
    for a in art.find_all("a"):
        a.unwrap()

    # 表格先转 Markdown，用占位符替换，避免 markdownify 把表格拍平
    tables: list[str] = []
    for i, tbl in enumerate(art.find_all("table")):
        markdown_tbl = table_to_md(tbl)
        if not markdown_tbl:
            continue
        token = f"\n\n@@TABLE{i}@@\n\n"
        tables.append(markdown_tbl)
        tbl.replace_with(soup.new_string(token))

    text = md(str(art), heading_style="ATX", bullets="-")

    for i, t in enumerate(tables):
        text = text.replace(f"@@TABLE{i}@@", t)

    # 收尾清理
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"^\s*\|?\s*\{#[^}]+\}\s*$", "", text, flags=re.M)  # 残留锚点
    text = add_code_langs(text)
    text = strip_tags_in_code(text)
    text = text.strip()

    # 标题：确保以 # 开头
    if not text.startswith("# "):
        first = text.splitlines()[0].strip("# ").strip() if text else "untitled"
        text = f"# {first}\n\n{text}"
    return text


def count_meta(text: str) -> dict:
    return {
        "chars": len(text),
        "headings": len(re.findall(r"^#{1,6} ", text, flags=re.M)),
        "tables": len(re.findall(r"^\|.*\|$", text, flags=re.M)),
        "code_blocks": len(re.findall(r"^```", text, flags=re.M)) // 2,
    }


# ---------------------------------------------------------------- 选篇
def section_of(slug: str) -> str:
    if "__" not in slug:
        return "top"
    return slug.split("__")[0]


def select(docs: list[dict], target: int) -> list[dict]:
    for d in docs:
        d["section"] = section_of(d["slug"])

    def pick(sec: str, n: int) -> list[dict]:
        pool = [d for d in docs if d["section"] == sec and d["chars"] >= 1500]
        pool.sort(key=lambda x: x["slug"])
        taken = pool[:n]
        for d in taken:
            d["_used"] = True
        return taken

    chosen: list[dict] = []
    for sec in ("top", "tutorial", "advanced", "deployment"):
        got = pick(sec, QUOTA.get(sec, 0))
        log(f"  选 {sec}: {len(got)}")
        chosen += got

    if len(chosen) < target:
        rest = [d for d in docs if not d.get("_used") and d["chars"] >= 1500]
        rest.sort(key=lambda x: -x["chars"])
        need = target - len(chosen)
        log(f"  配额不足，按体量补 {need} 篇")
        chosen += rest[:need]

    chosen = chosen[:target]
    order = {"top": 0, "tutorial": 1, "advanced": 2, "deployment": 3}
    chosen.sort(key=lambda x: (order.get(x["section"], 9), x["slug"]))
    return chosen


# ---------------------------------------------------------------- 主流程
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target-count", type=int, default=60)
    ap.add_argument("--min-chars", type=int, default=1500)
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.md"):
        old.unlink()

    htmls = sorted(RAW.glob("*.html"))
    mds = sorted(RAW.glob("*.md"))
    log(f"原始文件：html {len(htmls)} / md {len(mds)}")

    docs: list[dict] = []

    if htmls:
        for f in htmls:
            slug = f.stem
            if any(t in slug for t in DROP_TOKENS):
                continue
            text = clean_html(f.read_text(encoding="utf-8", errors="replace"), f.name)
            if not text or len(text) < args.min_chars:
                continue
            docs.append({"slug": slug, "text": text, **count_meta(text)})
    else:
        for f in mds:
            slug = f.stem
            if any(t in slug for t in DROP_TOKENS):
                continue
            text = f.read_text(encoding="utf-8")
            if len(text) < args.min_chars:
                continue
            docs.append({"slug": slug, "text": text, **count_meta(text)})

    log(f"清洗后有效文档：{len(docs)}")
    if not docs:
        log("没有可用文档，检查 data/corpus_raw")
        return 1

    chosen = select(docs, args.target_count)

    files = []
    for i, d in enumerate(chosen, 1):
        name = f"{i:02d}_{d['slug']}.md"
        (OUT / name).write_text(d["text"], encoding="utf-8")
        files.append({
            "seq": i, "file": name, "slug": d["slug"], "section": d["section"],
            "chars": d["chars"], "headings": d["headings"],
            "tables": d["tables"], "code_blocks": d["code_blocks"],
        })

    total_chars = sum(f["chars"] for f in files)
    manifest = {
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "target_count": args.target_count,
        "total": {"files": len(files), "chars": total_chars,
                  "avg_chars": total_chars // max(1, len(files))},
        "by_section": {s: sum(1 for f in files if f["section"] == s)
                       for s in ("top", "tutorial", "advanced", "deployment")},
        "files": files,
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    log(f"输出 {len(files)} 篇 -> {OUT}")
    log(f"总字符 {total_chars:,}（约 {total_chars/10000:.1f} 万字），均 {total_chars//max(1,len(files)):,} 字/篇")
    log(f"清单 -> {MANIFEST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
