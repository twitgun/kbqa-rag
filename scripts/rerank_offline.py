#!/usr/bin/env python
"""离线重排打分：只加载重排模型，对**已存的候选片段**重新打分。

为什么要单独写：本机 15.7GB 内存，M3（2.2GB）+ 重排（2.2GB）同时驻留会 OOM。
而生产路径本来就是"对融合后的 top-N 候选重排"，所以直接复用已召回的候选即可，
结论等价，内存只需一份模型。

用法：
  python scripts/rerank_offline.py --dataset-id 5
"""

from __future__ import annotations

import argparse
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset-id", type=int, default=5)
    ap.add_argument("--mode", default="L4", help="复用哪个模式的召回候选")
    ap.add_argument("--max-cands", type=int, default=8)
    args = ap.parse_args()

    import numpy as np
    from sentence_transformers import CrossEncoder

    from kbqa.settings import settings

    model_dir = settings.model_dir / settings.reranker_model
    if not model_dir.exists():
        print("重排模型不存在")
        return 1
    reranker = CrossEncoder(str(model_dir), device="cpu", max_length=512,
                            local_files_only=True)
    print(f"重排模型已加载: {model_dir.name}", flush=True)

    with SessionLocal() as db:
        qs = list(db.scalars(
            select(m.EvalQuestion).where(m.EvalQuestion.dataset_id == args.dataset_id)
            .order_by(m.EvalQuestion.seq)))
        chunks = dict(db.execute(select(m.Chunk.chunk_uid, m.Chunk.text)).all())
        recs = list(db.scalars(select(m.QaRecord).where(m.QaRecord.mode == args.mode)))
        by_q: dict[str, list[str]] = {}
        for r in recs:
            uids = [c.get("chunk_uid") for c in (r.retrieved_chunks or [])
                    if c.get("chunk_uid")]
            if uids:
                by_q[r.question] = uids

    rows = []
    miss = 0
    for i, q in enumerate(qs, 1):
        uids = by_q.get(q.question, [])[: args.max_cands]
        texts = [chunks[u] for u in uids if u in chunks]
        if not texts:
            miss += 1
            row = {"seq": q.seq, "qtype": q.qtype, "question": q.question,
                   "max_score": 0.0, "n_cands": 0}
        else:
            raw = np.asarray(reranker.predict([[q.question, t] for t in texts],
                                              batch_size=8, show_progress_bar=False),
                             dtype=np.float32).reshape(-1)
            # CrossEncoder 自带 Sigmoid（activation_fn），raw 已是 [0,1]，不能再套一层
            row = {"seq": q.seq, "qtype": q.qtype, "question": q.question,
                   "max_score": round(float(raw.max()), 4), "n_cands": len(texts)}
        rows.append(row)
        if i % 10 == 0:
            print(f"  {i}/{len(qs)}", flush=True)

    pos = [r["max_score"] for r in rows if r["qtype"] == "answerable"]
    neg = [r["max_score"] for r in rows if r["qtype"] == "unanswerable"]
    a = auc(pos, neg)
    sweep = []
    for t in [0.50, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90]:
        tp = sum(1 for x in pos if x >= t)
        fp = sum(1 for x in neg if x >= t)
        sweep.append({"tau": t, "tpr": round(tp / len(pos), 3), "fpr": round(fp / len(neg), 3),
                      "false_reject": len(pos) - tp, "false_accept": fp})

    print(f"\n可答 {len(pos)}：min={min(pos):.3f} 中位={sorted(pos)[len(pos)//2]:.3f} max={max(pos):.3f}")
    print(f"不可答 {len(neg)}：min={min(neg):.3f} 中位={sorted(neg)[len(neg)//2]:.3f} max={max(neg):.3f}")
    print(f"AUC = {a:.3f}（离线重排，仅对已召回候选打分，缺候选 {miss} 题）\n")
    print("  τ     TPR    FPR   误拒  误放")
    for s in sweep:
        print(f"  {s['tau']:.2f}  {s['tpr']:.3f}  {s['fpr']:.3f}  {s['false_reject']:3d}  {s['false_accept']:3d}")

    out = ROOT / "experiments" / f"{datetime.now():%Y%m%d-%H%M%S}-score-rerank-offline.json"
    out.write_text(json.dumps({"auc": round(a, 4), "n_pos": len(pos), "n_neg": len(neg),
                               "max_cands": args.max_cands, "sweep": sweep, "rows": rows},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
