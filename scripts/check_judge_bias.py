#!/usr/bin/env python
"""量化判定偏见：同一批答案，一次盲评（抹掉引用标记）、一次非盲评，比较判定差异。

这是"LLM 评审员看到 [1][2] 就倾向判正确"这个威胁的直接测量。
差异越大，说明盲评越必要；差异接近 0，说明该威胁可以忽略。

用法：
  python scripts/check_judge_bias.py --n 30
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))


def latest_results() -> list[dict]:
    files = sorted((ROOT / "experiments").glob("*.jsonl"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    for f in files:
        rows = [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
        if rows and "judge" in rows[0]:
            return rows
    return []


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--out", default=str(ROOT / "experiments" / "judge-bias.json"))
    args = ap.parse_args()

    from kbqa.api.deps import get_llm
    from kbqa.core.evaluation.judge import Judge

    rows = [r for r in latest_results() if not r["is_fallback"] and r.get("answer")]
    if not rows:
        print("没有可用结果")
        return 1
    # 均匀抽样，覆盖不同模式
    step = max(1, len(rows) // args.n)
    sample = rows[::step][: args.n]

    judge = Judge(get_llm(), ROOT / "backend" / "kbqa" / "prompts")
    print(f"样本 {len(sample)} 条，逐条做盲评与非盲评…", flush=True)

    pairs = []
    for i, r in enumerate(sample, 1):
        blind_v = await judge.judge(question=r["question"], answer=r["answer"],
                                    gold_answer=r.get("gold_answer"),
                                    contexts=r.get("contexts") or [],
                                    blind_mode=True)
        plain_v = await judge.judge(question=r["question"], answer=r["answer"],
                                    gold_answer=r.get("gold_answer"),
                                    contexts=r.get("contexts") or [],
                                    blind_mode=False)
        pairs.append({"seq": r["seq"], "mode": r["mode"],
                      "blind": blind_v, "plain": plain_v})
        if i % 10 == 0:
            print(f"  {i}/{len(sample)}", flush=True)

    agree = sum(1 for p in pairs if p["blind"]["verdict"] == p["plain"]["verdict"])
    hall_b = sum(1 for p in pairs if p["blind"]["hallucination"])
    hall_p = sum(1 for p in pairs if p["plain"]["hallucination"])
    shift = Counter()
    for p in pairs:
        if p["blind"]["verdict"] != p["plain"]["verdict"]:
            shift[f"{p['blind']['verdict']}→{p['plain']['verdict']}"] += 1

    print(f"\n判定一致：{agree}/{len(pairs)} = {agree/len(pairs):.1%}")
    print(f"幻觉判定：盲评 {hall_b} 条 / 非盲 {hall_p} 条")
    if shift:
        print("判定漂移：" + "，".join(f"{k} {v} 次" for k, v in shift.most_common()))
    else:
        print("判定漂移：无")
    print("解读：一致率高 → 引用标记偏见可忽略；一致率低 → 盲评必须保留。")

    Path(args.out).write_text(json.dumps({"n": len(pairs), "agree": agree,
                                          "halluc_blind": hall_b, "halluc_plain": hall_p,
                                          "pairs": pairs}, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    print(f"-> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
