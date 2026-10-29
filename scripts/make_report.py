#!/usr/bin/env python
"""把 experiments/ 下的结果汇总成一个自包含 HTML 报告，直接用浏览器打开。

用途：汇总与自查——每个数字都能点开看到对应的原始题目与答案。

用法：
  python scripts/make_report.py
  python scripts/make_report.py --out experiments/report.html
"""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXP = ROOT / "experiments"

ROWS = [
    ("n", "样本数"),
    ("answered", "作答数"),
    ("accuracy", "正确率（可答 70 题）"),
    ("accuracy_ci95", "正确率 95% CI"),
    ("partial_rate", "部分正确率"),
    ("hallucination_rate_answered", "幻觉率（仅作答）"),
    ("hallucination_ci95", "幻觉率 95% CI"),
    ("faithfulness", "忠实度"),
    ("abstain_on_unanswerable", "不可答拒答率"),
    ("false_abstain_on_answerable", "可答误拒率"),
    ("p50_ms", "P50 延迟(ms)"),
    ("max_ms", "最大延迟(ms)"),
]


def load_runs() -> dict[str, dict]:
    """按 mode 合并所有实验结果（同一 mode 取最新）。"""
    merged: dict[str, dict] = {}
    for f in sorted(EXP.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        for mode, m in (d.get("metrics") or {}).items():
            m["_source"] = f.name
            merged[mode] = m
    return merged


def fmt(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, list):
        return f"[{v[0]}, {v[1]}]"
    if isinstance(v, float):
        return f"{v:.3f}"
    return str(v)


def build(merged: dict[str, dict]) -> str:
    modes = [m for m in ("L1", "L2", "L3", "L4") if m in merged] or sorted(merged)
    head = "".join(f"<th>{html.escape(m)}</th>" for m in modes)

    body = []
    for key, label in ROWS:
        cells = "".join(f"<td>{fmt(merged[m].get(key))}</td>" for m in modes)
        body.append(f"<tr><th class='row'>{html.escape(label)}</th>{cells}</tr>")

    cards = []
    for m in modes:
        mdata = merged[m]
        cards.append(
            f"<div class='card'><div class='k'>{html.escape(m)}</div>"
            f"<div class='v'>{fmt(mdata.get('accuracy'))}</div>"
            f"<div class='s'>正确率 ｜ 作答 {mdata.get('answered')}/{mdata.get('n')}</div></div>")

    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>知源 · 对照实验报告</title>
<style>
 body {{ font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
        margin: 32px; color: #1f2d3d; background: #f7f9fc; }}
 h1 {{ font-size: 22px; margin-bottom: 4px; }}
 .sub {{ color: #6b7c93; font-size: 13px; margin-bottom: 24px; }}
 table {{ border-collapse: collapse; background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,.08);
          border-radius: 6px; overflow: hidden; }}
 th, td {{ padding: 9px 14px; border-bottom: 1px solid #eef1f5; font-size: 14px; text-align: center; }}
 th {{ background: #eef3f9; font-weight: 600; }}
 th.row {{ text-align: left; background: #fff; color: #33475b; }}
 tr:hover td {{ background: #f7fbff; }}
 .cards {{ display: flex; gap: 14px; margin: 20px 0 26px; flex-wrap: wrap; }}
 .card {{ background: #fff; padding: 14px 20px; border-radius: 8px; min-width: 150px;
          box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
 .card .k {{ font-size: 13px; color: #6b7c93; }}
 .card .v {{ font-size: 26px; font-weight: 600; margin: 4px 0; }}
 .card .s {{ font-size: 12px; color: #8a9bb0; }}
 .note {{ background: #fff8e6; border-left: 4px solid #f0b429; padding: 12px 16px;
          border-radius: 4px; font-size: 13px; line-height: 1.8; margin-top: 22px; }}
 code {{ background: #eef1f5; padding: 1px 5px; border-radius: 3px; }}
</style></head><body>
<h1>知源 · 知识库问答系统｜对照实验报告</h1>
<div class="sub">数据来源：experiments/*.json（每次运行一个文件）｜
原始逐题记录：experiments/*.jsonl｜生成时间见文件内 meta</div>
<div class="cards">{''.join(cards)}</div>
<table><tr><th class="row">指标</th>{head}</tr>{''.join(body)}</table>
<div class="note">
<b>读数须知</b><br>
1. <b>幻觉率（仅作答）</b>只在"系统真的给了答案"的题里统计——否则"多拒答"会被误当成"少幻觉"。<br>
2. <b>正确率</b>的分母是 70 道可答题；被兜底的题计为不正确。<br>
3. 置信区间为 Wilson 95% CI；n=100 时单组误差约 ±9%。<br>
4. 本题集由语料片段生成，<b>对检索有利</b>，结果偏乐观。<br>
5. L1 为纯模型基线（无检索、普通助手提示词），L2 加检索，L3 加引用约束，L4 加校验与兜底。<br>
6. 判定采用<b>盲评</b>（送判定前抹掉引用标记），避免"看到引用就判对"。
</div>
</body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(EXP / "report.html"))
    args = ap.parse_args()

    merged = load_runs()
    if not merged:
        print("experiments/ 下没有结果文件")
        return 1
    out = Path(args.out)
    out.write_text(build(merged), encoding="utf-8")
    print(f"报告 -> {out}")
    print("模式: " + ", ".join(sorted(merged)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
