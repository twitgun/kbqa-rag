#!/usr/bin/env python
"""用探针集标定证据阈值 τ（实现 03_核心机制/02 §6.3 的五步法）。

原理：可答题与不可答题的 max_score 分布如果分得开，就存在一个阈值把两类分开；
分不开（AUC 低）说明当前打分方式不适合做拒答判定——这正是"必须加重排"的证据。

用法：
  python scripts/calibrate_tau.py
  python scripts/calibrate_tau.py --probe data/tau_probe.json --json-out data/tau_calib.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))


def auc(pos: list[float], neg: list[float]) -> float:
    """用 Mann-Whitney U 计算 AUC：随机取一个正样本和一个负样本，正样本分数更高的概率。"""
    if not pos or not neg:
        return 0.0
    wins = 0.0
    for p in pos:
        for n in neg:
            wins += 1.0 if p > n else 0.5 if p == n else 0.0
    return wins / (len(pos) * len(neg))


def best_threshold(pos: list[float], neg: list[float]) -> tuple[float, float, float]:
    """扫描候选阈值，返回 (tau, TPR, FPR)，使 Youden 指数最大。"""
    cands = sorted(set(pos + neg))
    if len(cands) < 2:
        return 0.5, 0.0, 0.0
    grid = [round((a + b) / 2, 4) for a, b in zip(cands, cands[1:])]
    best = (grid[0], 0.0, 1.0)
    for t in grid:
        tpr = sum(1 for x in pos if x >= t) / len(pos)
        fpr = sum(1 for x in neg if x >= t) / len(neg)
        if tpr - fpr > best[1] - best[2]:
            best = (t, tpr, fpr)
    return best


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", default=str(ROOT / "data" / "tau_probe.json"))
    ap.add_argument("--json-out", default="")
    ap.add_argument("--no-rerank", action="store_true", help="强制关闭重排，用于对照")
    args = ap.parse_args()

    from kbqa.api.deps import get_retriever

    probe = json.loads(Path(args.probe).read_text(encoding="utf-8"))
    r = get_retriever()
    print(f"embedder={getattr(r.embedder, 'name', '')} dim={r.embedder.dim} "
          f"reranker={'on' if r.reranker else 'off'} tau_cosine={r.tau_cosine}")

    rows = []
    for item in probe["items"]:
        res = asyncio.run(r.retrieve(item["question"], enable_rerank=not args.no_rerank))
        rows.append({"question": item["question"], "answerable": item["answerable"],
                     "kind": item["kind"], "max_score": round(res.max_score, 4),
                     "passed": res.passed})

    pos = [x["max_score"] for x in rows if x["answerable"]]
    neg = [x["max_score"] for x in rows if not x["answerable"]]
    a = auc(pos, neg)
    tau, tpr, fpr = best_threshold(pos, neg)

    print(f"\n可答题 max_score: min={min(pos):.3f} 均值={sum(pos)/len(pos):.3f} max={max(pos):.3f}")
    print(f"不可答 max_score: min={min(neg):.3f} 均值={sum(neg)/len(neg):.3f} max={max(neg):.3f}")
    print(f"AUC={a:.3f}（1.0 完美可分，0.5 等于瞎猜）")
    print(f"Youden 最优点：tau={tau:.4f}  TPR={tpr:.2f}  FPR={fpr:.2f}")

    print("\n逐题：")
    for x in sorted(rows, key=lambda z: -z["max_score"]):
        mark = "可答" if x["answerable"] else "不可答"
        flag = "[OK]" if (x["passed"] == x["answerable"]) else "[X] "
        print(f"  {x['max_score']:.4f} {mark:6s} {flag} {x['question']}")

    if a < 0.7:
        print("\n[结论] AUC < 0.7：当前打分方式无法可靠区分「能答」与「不能答」，"
              "单靠阈值拒答不可靠，必须引入重排（Cross-Encoder）。")
    elif a < 0.85:
        print("\n[结论] AUC 中等：阈值可用但误判仍多，建议加重排以提升可分性。")
    else:
        print("\n[结论] AUC 较高：单阈值可用，仍需按 FPR 约束选点。")

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(
            {"auc": a, "suggested_tau": tau, "tpr": tpr, "fpr": fpr,
             "embedder": getattr(r.embedder, "name", ""), "rows": rows},
            ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON -> {args.json_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
