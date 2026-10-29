#!/usr/bin/env python
"""测两件事：
1) 重排压到 top-8 / max_length=256 后，单次延迟是多少（能否进 5s 预算）；
2) 「top1 - top2 的差值（margin）」能否比 max 更好地分开近域不可答题。

只做检索+重排，不调生成，无 API 成本。
用法：python scripts/rerank_margin.py --limit 40
"""

from __future__ import annotations

import argparse
import json
import sys
import time
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
    w = sum(1.0 if p > n else 0.5 if p == n else 0.0 for p in pos for n in neg)
    return w / (len(pos) * len(neg))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset-id", type=int, default=5)
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--cands", type=int, default=8)
    ap.add_argument("--max-length", type=int, default=256)
    ap.add_argument("--model", default="", help="模型目录名，默认用 settings.reranker_model")
    args = ap.parse_args()

    import numpy as np
    from sentence_transformers import CrossEncoder

    from kbqa.settings import settings

    model_dir = settings.model_dir / (args.model or settings.reranker_model)
    t0 = time.time()
    ce = CrossEncoder(str(model_dir), device="cpu", max_length=args.max_length,
                      local_files_only=True)
    print(f"模型加载 {time.time()-t0:.1f}s（max_length={args.max_length}）", flush=True)

    with SessionLocal() as db:
        all_q = list(db.scalars(
            select(m.EvalQuestion).where(m.EvalQuestion.dataset_id == args.dataset_id)
            .order_by(m.EvalQuestion.seq)))
        chunks = dict(db.execute(select(m.Chunk.chunk_uid, m.Chunk.text)).all())
        recs = list(db.scalars(select(m.QaRecord).where(m.QaRecord.mode == "L4")))
        by_q: dict[str, list[str]] = {}
        for r in recs:
            uids = [c.get("chunk_uid") for c in (r.retrieved_chunks or []) if c.get("chunk_uid")]
            if uids:
                by_q[r.question] = uids

    # 分层抽样：可答与不可答各占一半，否则 AUC 无从计算
    half = max(1, args.limit // 2)
    qs = ([q for q in all_q if q.qtype == "answerable"][:half]
          + [q for q in all_q if q.qtype == "unanswerable"][:half])

    rows = []
    lat: list[int] = []
    for i, q in enumerate(qs, 1):
        texts = [chunks[u] for u in by_q.get(q.question, [])[: args.cands] if u in chunks]
        if len(texts) < 2:
            continue
        t1 = time.perf_counter()
        scores = np.asarray(ce.predict([[q.question, t] for t in texts],
                                       batch_size=8, show_progress_bar=False),
                            dtype=np.float32).reshape(-1)
        lat.append(int((time.perf_counter() - t1) * 1000))
        s = np.sort(scores)[::-1]
        rows.append({"seq": q.seq, "qtype": q.qtype, "max": float(s[0]),
                     "top2": float(s[1]), "margin": float(s[0] - s[1])})
        if i % 10 == 0:
            print(f"  {i}/{len(qs)}  最近一次 {lat[-1]}ms", flush=True)

    pos = [r for r in rows if r["qtype"] == "answerable"]
    neg = [r for r in rows if r["qtype"] == "unanswerable"]
    lat.sort()
    print(f"\n样本 {len(rows)}（可答 {len(pos)} / 不可答 {len(neg)}）")
    print(f"重排延迟：P50 {lat[len(lat)//2]}ms  P95 {lat[int(len(lat)*0.95)]}ms  max {lat[-1]}ms")
    print(f"AUC(max)    = {auc([r['max'] for r in pos], [r['max'] for r in neg]):.3f}")
    print(f"AUC(margin) = {auc([r['margin'] for r in pos], [r['margin'] for r in neg]):.3f}")
    p_neg = [r["margin"] for r in neg]
    p_pos = [r["margin"] for r in pos]
    print(f"margin 可答 中位 {sorted(p_pos)[len(p_pos)//2]:.3f} / 不可答 中位 {sorted(p_neg)[len(p_neg)//2]:.3f}")

    out = ROOT / "experiments" / f"{datetime.now():%Y%m%d-%H%M%S}-rerank-margin.json"
    out.write_text(json.dumps({"cands": args.cands, "max_length": args.max_length,
                               "latency_ms": {"p50": lat[len(lat)//2],
                                              "p95": lat[int(len(lat)*0.95)]},
                               "auc_max": None, "rows": rows}, ensure_ascii=False,
                              indent=2), encoding="utf-8")
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
