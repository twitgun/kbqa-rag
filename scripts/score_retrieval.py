#!/usr/bin/env python
"""只跑检索层打分，不调用生成模型——用于在真实题集上标定 τ。

输出每个问题的 max_score（可分别开/关重排），并直接给出 AUC 与 τ 扫描表。
没有生成成本，100 题约 10~20 分钟（取决于是否开重排）。

用法：
  python scripts/score_retrieval.py --dataset-id 5 --rerank        # 开重排
  python scripts/score_retrieval.py --dataset-id 5 --no-rerank     # 只看双塔
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import select  # noqa: E402

from kbqa.infra.db import models as m  # noqa: E402
from kbqa.infra.db.session import SessionLocal  # noqa: E402


def auc(pos: list[float], neg: list[float]) -> float:
    if not pos or not neg:
        return 0.0
    wins = sum(1.0 if p > n else 0.5 if p == n else 0.0 for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def sweep(pos: list[float], neg: list[float]) -> list[dict]:
    rows = []
    for t in [0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80]:
        tp = sum(1 for x in pos if x >= t)
        fp = sum(1 for x in neg if x >= t)
        fpr = fp / len(neg) if neg else 0.0
        tpr = tp / len(pos) if pos else 0.0
        rows.append({"tau": t, "tpr": round(tpr, 3), "fpr": round(fpr, 3),
                     "false_reject": len(pos) - tp, "false_accept": fp})
    return rows


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset-id", type=int, default=5)
    ap.add_argument("--rerank", dest="rerank", action="store_true")
    ap.add_argument("--no-rerank", dest="rerank", action="store_false")
    ap.set_defaults(rerank=False)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    from kbqa.api.deps import get_retriever

    with SessionLocal() as db:
        qs = list(db.scalars(
            select(m.EvalQuestion).where(m.EvalQuestion.dataset_id == args.dataset_id)
            .order_by(m.EvalQuestion.seq)))
    if args.limit:
        qs = qs[: args.limit]

    r = get_retriever()
    print(f"embedder={getattr(r.embedder, 'name', '')} reranker={'on' if r.reranker else 'off'} "
          f"题目 {len(qs)} 道", flush=True)

    rows = []
    for i, q in enumerate(qs, 1):
        res = await r.retrieve(q.question, enable_rerank=args.rerank)
        rows.append({"seq": q.seq, "qtype": q.qtype, "question": q.question,
                     "max_score": round(res.max_score, 4), "passed": res.passed,
                     "rerank_degraded": res.degraded})
        if i % 10 == 0:
            print(f"  {i}/{len(qs)}", flush=True)

    pos = [x["max_score"] for x in rows if x["qtype"] == "answerable"]
    neg = [x["max_score"] for x in rows if x["qtype"] == "unanswerable"]
    a = auc(pos, neg)
    table = sweep(pos, neg)

    print(f"\n可答 {len(pos)}：min={min(pos):.3f} 中位={sorted(pos)[len(pos)//2]:.3f} max={max(pos):.3f}")
    print(f"不可答 {len(neg)}：min={min(neg):.3f} 中位={sorted(neg)[len(neg)//2]:.3f} max={max(neg):.3f}")
    print(f"AUC = {a:.3f}（重排 {'开' if args.rerank else '关'}）\n")
    print("  τ     TPR    FPR   误拒  误放")
    for t in table:
        print(f"  {t['tau']:.2f}  {t['tpr']:.3f}  {t['fpr']:.3f}  {t['false_reject']:3d}  {t['false_accept']:3d}")

    out = ROOT / "experiments" / f"{datetime.now():%Y%m%d-%H%M%S}-score-{'rerank' if args.rerank else 'dense'}.json"
    out.write_text(json.dumps({"rerank": args.rerank, "auc": round(a, 4),
                               "n_pos": len(pos), "n_neg": len(neg),
                               "sweep": table, "rows": rows},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n-> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
