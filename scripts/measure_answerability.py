#!/usr/bin/env python
"""量出「可答性判定」逐题结果，用于离线设计触发策略。

不生成答案，只做：检索 → 可答性判定。100 题约 3–4 分钟。
输出每题 (qtype, max_score, verdict)，可据此评估"只在某分数区间才问判定"的策略。

用法：python scripts/measure_answerability.py
"""

from __future__ import annotations

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


async def main() -> int:
    from kbqa.api.deps import get_llm, get_retriever
    from kbqa.core.generation.answerability import AnswerabilityChecker

    with SessionLocal() as db:
        qs = list(db.scalars(
            select(m.EvalQuestion).where(m.EvalQuestion.dataset_id == 5)
            .order_by(m.EvalQuestion.seq)))

    retriever = get_retriever()
    checker = AnswerabilityChecker(get_llm(), ROOT / "backend" / "kbqa" / "prompts")

    rows = []
    for i, q in enumerate(qs, 1):
        res = await retriever.retrieve(q.question)
        verdict = await checker.can_answer(q.question, res.candidates)
        rows.append({"seq": q.seq, "qtype": q.qtype, "question": q.question,
                     "max_score": round(res.max_score, 4),
                     "passed_tau": bool(res.passed),
                     "can_answer": verdict})
        if i % 10 == 0:
            print(f"  {i}/{len(qs)}", flush=True)

    out = ROOT / "experiments" / f"{datetime.now():%Y%m%d-%H%M%S}-answerability.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
