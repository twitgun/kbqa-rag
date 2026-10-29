#!/usr/bin/env python
"""把抽检结果算成 Kappa：judge 与人工判定的一致性。

两种用法：
  1) 生成可填写的 CSV（带 judge 判定，留一列给人工）
       python scripts/kappa.py --make
  2) 填完后计算一致性
       python scripts/kappa.py --score experiments/human-check.csv

填法：在 human_verdict 列填 正确 / 部分正确 / 错误（或 1 / 2 / 3），
      不确定就留空——留空的题不计入 Kappa。
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "experiments" / "human-check.csv"

MAP = {"正确": "正确", "部分正确": "部分正确", "错误": "错误",
       "1": "正确", "2": "部分正确", "3": "错误",
       "对": "正确", "错": "错误", "√": "正确", "✓": "正确", "×": "错误"}


def latest_rows() -> list[dict]:
    files = sorted((ROOT / "experiments").glob("*.jsonl"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    for f in files:
        rows = [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
        if rows and "judge" in rows[0]:
            return rows
    return []


def make(n: int = 20) -> int:
    rows = [r for r in latest_rows() if not r["is_fallback"]]
    if not rows:
        print("没有可抽检的结果")
        return 1
    random.seed(20261029)
    sample = random.sample(rows, min(n, len(rows)))
    with CSV_PATH.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["seq", "mode", "qtype", "question", "gold_answer",
                    "system_answer", "judge_verdict", "human_verdict", "note"])
        for r in sample:
            w.writerow([r["seq"], r["mode"], r["qtype"], r["question"],
                        (r.get("gold_answer") or "")[:400], r["answer"][:600],
                        r["judge"]["verdict"], "", ""])
    print(f"已生成 {CSV_PATH}（{len(sample)} 行）")
    print("在 human_verdict 列填 正确 / 部分正确 / 错误，然后运行 --score")
    return 0


def kappa(a: list[str], b: list[str]) -> float:
    if not a or len(a) != len(b):
        return 0.0
    n = len(a)
    labels = sorted(set(a) | set(b))
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    pe = sum((a.count(l) / n) * (b.count(l) / n) for l in labels)
    return 1.0 if pe >= 1 else (po - pe) / (1 - pe)


def score() -> int:
    if not CSV_PATH.exists():
        print(f"找不到 {CSV_PATH}，先运行 --make")
        return 1
    gold, pred, skipped = [], [], 0
    with CSV_PATH.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            raw = (row.get("human_verdict") or "").strip()
            if not raw:
                skipped += 1
                continue
            h = MAP.get(raw)
            if h is None:
                print(f"  行 seq={row['seq']} 的值「{raw}」无法识别，已跳过")
                continue
            gold.append(h)
            pred.append(row["judge_verdict"])

    if not gold:
        print("没有有效的人工判定")
        return 1

    agree = sum(1 for x, y in zip(gold, pred) if x == y)
    k = kappa(gold, pred)
    print(f"有效 {len(gold)} 条（留空 {skipped} 条）")
    print(f"一致 {agree}/{len(gold)} = {agree/len(gold):.1%}")
    print(f"Cohen's Kappa = {k:.3f}")
    if k >= 0.8:
        print("结论：几乎完全一致，自动判定可信。")
    elif k >= 0.6:
        print("结论：一致性可接受，可能有个别争议样本。")
    else:
        print("结论：一致性不足，需复核 judge 提示词或改人工全判。")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--make", action="store_true")
    ap.add_argument("--score", action="store_true")
    ap.add_argument("--n", type=int, default=20)
    args = ap.parse_args()
    if args.make:
        return make(args.n)
    return score()


if __name__ == "__main__":
    sys.exit(main())
