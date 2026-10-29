#!/usr/bin/env python
"""对已有结果套用「不可答题越界作答」规则，重算指标（不调用任何模型）。

规则：qtype=unanswerable 且系统未兜底、答案也不是拒答措辞 → verdict=错误、hallucination=True。
早期 judge 漏了这条，使幻觉率恒为 0，掩盖了系统对"资料没有的问题硬答"的行为。

用法：
  python scripts/rejudge_rule.py experiments/xxx.jsonl
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from kbqa.core.evaluation.judge import Judge  # noqa: E402
from run_experiment import summarize, to_markdown  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python scripts/rejudge_rule.py <结果.jsonl>")
        return 1
    src = Path(sys.argv[1])
    rows = [json.loads(l) for l in src.read_text(encoding="utf-8").splitlines() if l.strip()]

    changed = 0
    for r in rows:
        if r["qtype"] != "unanswerable" or r["is_fallback"]:
            continue
        if Judge._is_refusal(r["answer"] or ""):
            continue
        if r["judge"].get("verdict") != "错误" or not r["judge"].get("hallucination"):
            r["judge"] = {"verdict": "错误", "hallucination": True, "faithfulness": 0.0,
                          "reason": "对不可答题给出实质答案（越界作答）", "judged_by": "rule"}
            changed += 1

    modes = sorted({r["mode"] for r in rows})
    metrics = summarize(rows, modes)
    from datetime import datetime
    result = {"meta": {"started_at": datetime.now().isoformat(),
                       "dataset_id": 0, "rejudged_from": src.name, "rule_applied": changed,
                       "model": "rule-fix", "embedder": "-", "rerank": False, "elapsed_s": 0,
                       "total": len({r["question_id"] for r in rows}), "modes": modes},
              "metrics": metrics}

    out = src.with_name(src.stem + "-rulefix.json")
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    src.with_name(src.stem + "-rulefix.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    md = out.with_suffix(".md")
    md.write_text(to_markdown(result), encoding="utf-8")

    print(f"应用规则 {changed} 条 → {out.name}")
    print(md.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
