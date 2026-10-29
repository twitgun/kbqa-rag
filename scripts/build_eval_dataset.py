#!/usr/bin/env python
"""用 LLM 基于真实语料生成评测集（70 可答 + 30 不可答）。

设计要点：
- 可答题：从片段里挑事实生成问题，gold_answer 必须来自片段（防"答案不在库里"）；
- 不可答题分两类：
  * near  近域——话题相关但语料没讲（最能考验阈值与提示词）；
  * far   远域——常识/生活类，用来验证最简单的拒答；
- 生成后做去重与基本质量校验，坏样本丢弃并记录。

用法：
  python scripts/build_eval_dataset.py --answerable 70 --near 20 --far 10
  python scripts/build_eval_dataset.py --dry-run --answerable 3
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import select  # noqa: E402

from kbqa.infra.db import models as m  # noqa: E402
from kbqa.infra.db.session import SessionLocal  # noqa: E402

GEN_PROMPT = """你是评测集构造器。下面是一段 FastAPI 中文文档片段。

【片段】
{text}

请生成 **1 个** 用户会真实提出的、且**仅凭这段片段就能回答**的问题，以及对应的答案。

要求：
- 问题要像一个真实用户在问，不要出现"根据上述片段"之类的措辞；
- 问题不能直接照抄片段标题，要能独立理解；
- 答案必须完全来自片段，简明扼要，不超过 120 字；
- 输出 JSON：{{"question": "...", "answer": "...", "difficulty": "easy|medium|hard"}}

只输出 JSON。"""

NEAR_PROMPT = """你在为一个「FastAPI 中文文档」知识库设计**无法回答**的测试问题。

下面是该知识库里的三段内容（节选）：
{text}

请设计 1 个与 FastAPI / Python Web 开发**话题相关**、但这三段内容（以及一般 FastAPI 官方文档）**无法回答**的问题。

要求：
- 问题要自然，像用户真的会问的；
- 不能是常识题，要有点专业度（例如某具体版本特性、内部实现细节、官方未提供的功能）；
- 输出 JSON：{{"question": "...", "why_unanswerable": "..."}}

只输出 JSON。"""

FAR_PROMPT = """请生成 1 个与「FastAPI / 编程 / 知识库」**完全无关**的生活类问题。
输出 JSON：{"question": "..."}
只输出 JSON。"""


def _clean_json(text: str) -> dict | None:
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    m_ = re.search(r"\{.*\}", text, re.S)
    if not m_:
        return None
    try:
        return json.loads(m_.group(0))
    except json.JSONDecodeError:
        return None


async def _ask(llm, prompt: str) -> dict | None:
    for _ in range(3):
        try:
            r = await llm.complete([{"role": "user", "content": prompt}],
                                   temperature=0.8, max_tokens=400, timeout=40,
                                   json_mode=False)
            return _clean_json(r.text)
        except Exception:  # noqa: BLE001
            await asyncio.sleep(1)
    return None


def _pick_chunks(answerable: int, near: int) -> list[dict]:
    """按文档分散抽样，避免全来自同一篇。"""
    with SessionLocal() as db:
        rows = db.execute(
            select(m.Chunk.chunk_uid, m.Chunk.text, m.Chunk.doc_id,
                   m.Document.title, m.Chunk.section_path)
            .join(m.Document, m.Document.id == m.Chunk.doc_id)
            .where(m.Document.status == "ready")
        ).all()

    by_doc: dict[int, list] = {}
    for r in rows:
        if len(r.text) < 200:          # 太短不利于出题
            continue
        by_doc.setdefault(r.doc_id, []).append(r)

    docs = sorted(by_doc)
    random.shuffle(docs)
    need = answerable + near
    picked: list = []
    i = 0
    while len(picked) < need and docs:
        d = docs[i % len(docs)]
        pool = by_doc[d]
        if pool:
            picked.append(pool.pop(random.randrange(len(pool))))
        i += 1
        if i > 10_000:
            break
    return [{"chunk_uid": p.chunk_uid, "text": p.text, "doc_id": p.doc_id,
             "title": p.title, "section_path": p.section_path} for p in picked]


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--answerable", type=int, default=70)
    ap.add_argument("--near", type=int, default=20)
    ap.add_argument("--far", type=int, default=10)
    ap.add_argument("--out", default=str(ROOT / "data" / "eval_set_v1.jsonl"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from kbqa.api.deps import get_llm

    llm = get_llm()
    random.seed(20261028)
    picks = _pick_chunks(args.answerable, args.near)
    items: list[dict] = []
    seq = 1
    seen_questions: set[str] = set()

    # ---- 可答题 ----
    for p in picks[: args.answerable]:
        data = await _ask(llm, GEN_PROMPT.format(text=p["text"][:1500]))
        if not data or not data.get("question") or not data.get("answer"):
            continue
        q = data["question"].strip()
        if q in seen_questions or len(q) < 6:
            continue
        seen_questions.add(q)
        items.append({
            "seq": seq, "question": q, "qtype": "answerable",
            "gold_answer": data["answer"].strip()[:400],
            "gold_chunk_ids": [p["chunk_uid"]], "gold_doc_ids": [f"d{p['doc_id']}"],
            "difficulty": data.get("difficulty", "medium"),
            "category": (p["section_path"] or p["title"] or "").split(">")[0].strip()[:40], "notes": "",
        })
        seq += 1
        print(f"[可答 {len(items)}/{args.answerable}] {q[:40]}", flush=True)

    # ---- 近域不可答 ----
    for p in picks[args.answerable: args.answerable + args.near]:
        data = await _ask(llm, NEAR_PROMPT.format(text=p["text"][:1200]))
        if not data or not data.get("question"):
            continue
        q = data["question"].strip()
        if q in seen_questions or len(q) < 6:
            continue
        seen_questions.add(q)
        items.append({
            "seq": seq, "question": q, "qtype": "unanswerable",
            "gold_answer": None, "gold_chunk_ids": [], "gold_doc_ids": [],
            "difficulty": "hard", "category": "近域陷阱",
            "notes": data.get("why_unanswerable", "")[:200],
        })
        seq += 1
        print(f"[近域 {seq-1-args.answerable}] {q[:40]}", flush=True)

    # ---- 远域不可答 ----
    for _ in range(args.far):
        data = await _ask(llm, FAR_PROMPT)
        if not data or not data.get("question"):
            continue
        q = data["question"].strip()
        if q in seen_questions or len(q) < 4:
            continue
        seen_questions.add(q)
        items.append({
            "seq": seq, "question": q, "qtype": "unanswerable",
            "gold_answer": None, "gold_chunk_ids": [], "gold_doc_ids": [],
            "difficulty": "easy", "category": "远域", "notes": "",
        })
        seq += 1

    out = Path(args.out)
    if not args.dry_run:
        out.write_text("\n".join(json.dumps(i, ensure_ascii=False) for i in items) + "\n",
                       encoding="utf-8")

    ans = sum(1 for i in items if i["qtype"] == "answerable")
    print(f"\n生成 {len(items)} 题：可答 {ans} / 不可答 {len(items)-ans}")
    print(f"输出 -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
