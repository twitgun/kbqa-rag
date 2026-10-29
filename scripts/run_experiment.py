#!/usr/bin/env python
"""对照实验：同一批题、不同配置，出可复现的对比数据。

默认跑 L1（纯模型，不检索）与 L4（全机制）：
- 每个题目走一遍 QaService（即线上链路）；
- 用 LLM judge 打分（verdict / hallucination / faithfulness）；
- 结果落到 experiments/<时间戳>.json 与 .md，便于对比与留痕。

用法：
  python scripts/run_experiment.py --dataset-id 5 --modes L1 L4
  python scripts/run_experiment.py --modes L4 --limit 10    # 小样本试跑
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import select  # noqa: E402

from kbqa.infra.db import models as m  # noqa: E402
from kbqa.infra.db.session import SessionLocal  # noqa: E402


def load_questions(dataset_id: int, limit: int | None = None) -> list[dict]:
    with SessionLocal() as db:
        rows = list(db.scalars(
            select(m.EvalQuestion).where(m.EvalQuestion.dataset_id == dataset_id)
            .order_by(m.EvalQuestion.seq)))
    out = [{"id": q.id, "seq": q.seq, "question": q.question, "qtype": q.qtype,
            "gold_answer": q.gold_answer} for q in rows]
    return out[:limit] if limit else out


def chunk_texts(uids: list[str]) -> dict[str, str]:
    if not uids:
        return {}
    with SessionLocal() as db:
        rows = db.execute(select(m.Chunk.chunk_uid, m.Chunk.text)
                          .where(m.Chunk.chunk_uid.in_(uids))).all()
    return {u: t for u, t in rows}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """比例的 Wilson 95% 置信区间——小样本下比正态近似可靠。"""
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return round(max(0.0, centre - half), 3), round(min(1.0, centre + half), 3)


def summarize(rows: list[dict], modes: list[str]) -> dict:
    out: dict[str, dict] = {}
    for mode in modes:
        items = [r for r in rows if r["mode"] == mode]
        ans = [i for i in items if i["qtype"] == "answerable"]
        unans = [i for i in items if i["qtype"] == "unanswerable"]

        answered = [i for i in items if not i["is_fallback"]]
        answered_ans = [i for i in answered if i["qtype"] == "answerable"]
        verdicts = [i["judge"]["verdict"] for i in ans if i.get("judge")]
        correct = sum(1 for v in verdicts if v == "正确")
        partial = sum(1 for v in verdicts if v == "部分正确")

        halluc_all = sum(1 for i in items if (i.get("judge") or {}).get("hallucination"))
        # 条件幻觉率：只在"真的作答了"的题里算，否则"多拒答"会被误当成"少幻觉"
        halluc_answered = sum(1 for i in answered
                              if (i.get("judge") or {}).get("hallucination"))

        faith = [i["judge"]["faithfulness"] for i in items
                 if (i.get("judge") or {}).get("faithfulness") is not None]
        lat = [i["latency_ms"] for i in items]

        ci_correct = wilson(correct, len(ans)) if ans else None
        ci_halluc = wilson(halluc_answered, len(answered)) if answered else None

        out[mode] = {
            "n": len(items), "answerable": len(ans), "unanswerable": len(unans),
            "answered": len(answered),
            "correct": correct,
            "accuracy": round(correct / len(ans), 3) if ans else None,
            "accuracy_ci95": ci_correct,
            "partial_rate": round(partial / len(ans), 3) if ans else None,
            "hallucination_rate_all": round(halluc_all / len(items), 3) if items else None,
            "hallucination_rate_answered": round(halluc_answered / len(answered), 3)
            if answered else None,
            "hallucination_ci95": ci_halluc,
            "faithfulness": round(statistics.mean(faith), 3) if faith else None,
            "abstain_on_unanswerable": round(
                sum(1 for i in unans if i["is_fallback"]) / len(unans), 3) if unans else None,
            "false_abstain_on_answerable": round(
                sum(1 for i in ans if i["is_fallback"]) / len(ans), 3) if ans else None,
            "p50_ms": int(statistics.median(lat)) if lat else None,
            "max_ms": max(lat) if lat else None,
        }
    return out


def to_markdown(res: dict) -> str:
    modes = list(res["metrics"])
    cols = [("n", "样本"), ("answered", "作答数"), ("accuracy", "正确率"), ("partial_rate", "部分正确"),
            ("hallucination_rate_answered", "幻觉率(仅作答)"), ("faithfulness", "忠实度"),
            ("abstain_on_unanswerable", "不可答拒答率"),
            ("false_abstain_on_answerable", "可答误拒率"),
            ("p50_ms", "P50(ms)"), ("max_ms", "最大(ms)")]
    lines = [f"# 对照实验 {res['meta']['started_at'][:19]}", "",
             f"- 数据集：#{res['meta']['dataset_id']}（{res['meta']['total']} 题）",
             f"- 模式：{', '.join(modes)}",
             f"- 模型：{res['meta']['model']}",
             f"- 向量模型：{res['meta']['embedder']}；重排：{'开' if res['meta']['rerank'] else '关'}",
             f"- 耗时：{res['meta']['elapsed_s']}s", "",
             "| 指标 | " + " | ".join(modes) + " |",
             "|---" * (len(modes) + 1) + "|"]
    for key, label in cols:
        cells = []
        for md in modes:
            v = res["metrics"][md].get(key)
            cells.append("—" if v is None else str(v))
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset-id", type=int, default=5)
    ap.add_argument("--modes", nargs="+", default=["L1", "L4"])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--no-judge", action="store_true")
    ap.add_argument("--rejudge", default="", help="对已有 jsonl 重新盲评，不重新生成答案")
    args = ap.parse_args()

    from kbqa.api.deps import get_llm, get_qa_service, get_reranker
    from kbqa.config.runtime import load_config
    from kbqa.core.evaluation.judge import Judge

    qa = get_qa_service()
    llm = get_llm()
    judge = Judge(llm, ROOT / "backend" / "kbqa" / "prompts")

    questions = load_questions(args.dataset_id, args.limit or None)
    cfg = load_config()
    started = datetime.now()
    t0 = time.time()

    # ---- 重评模式：只重新判定，不重新生成（用于盲评对照） ----
    if args.rejudge:
        src = Path(args.rejudge)
        rows = [json.loads(l) for l in src.read_text(encoding="utf-8").splitlines() if l.strip()]
        print(f"重评 {len(rows)} 条（盲评）...", flush=True)
        for idx, row in enumerate(rows, 1):
            row["judge"] = await judge.judge(
                question=row["question"], answer=row["answer"],
                gold_answer=row["gold_answer"], contexts=row.get("contexts") or [],
                is_fallback=row["is_fallback"], blind_mode=True)
            if idx % 20 == 0:
                print(f"  {idx}/{len(rows)}", flush=True)

        modes = sorted({r["mode"] for r in rows})
        result = {"meta": {"started_at": started.isoformat(),
                           "dataset_id": args.dataset_id, "total": len(questions),
                           "modes": modes, "rejudged_from": src.name,
                           "model": getattr(llm, "model", "deepseek-chat"),
                           "rerank": get_reranker() is not None,
                           "elapsed_s": int(time.time() - t0)},
                  "metrics": summarize(rows, modes)}
        stem = f"{started:%Y%m%d-%H%M%S}-rejudged-blind"
        (out_dir := ROOT / "experiments").mkdir(exist_ok=True)
        (out_dir / f"{stem}.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
        (out_dir / f"{stem}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        (out_dir / f"{stem}.md").write_text(to_markdown(result), encoding="utf-8")
        print(to_markdown(result))
        return 0

    rows: list[dict] = []
    out_dir = ROOT / "experiments"
    out_dir.mkdir(exist_ok=True)
    stem = f"{started:%Y%m%d-%H%M%S}-{'_'.join(args.modes)}"
    raw_path = out_dir / f"{stem}.jsonl"

    with raw_path.open("w", encoding="utf-8") as fh:
        for mode in args.modes:
            print(f"\n=== {mode} ===", flush=True)
            for idx, q in enumerate(questions, 1):
                res = await qa.ask(question=q["question"], mode=mode)
                ctx_uids = [c["chunk_uid"] for c in
                            res["retrieval"].get("candidates") or []]
                contexts = list(chunk_texts(ctx_uids).values())

                verdict = {"verdict": None, "hallucination": None,
                           "faithfulness": None, "reason": "skip"}
                if not args.no_judge:
                    verdict = await judge.judge(
                        question=q["question"], answer=res["answer"],
                        gold_answer=q["gold_answer"], contexts=contexts,
                        is_fallback=res["is_fallback"])

                row = {
                    "seq": q["seq"], "question_id": q["id"], "qtype": q["qtype"],
                    "question": q["question"], "gold_answer": q["gold_answer"],
                    "mode": mode, "answer": res["answer"],
                    "is_fallback": res["is_fallback"],
                    "fallback_reason": res["fallback_reason"],
                    "citations": len(res["citations"]),
                    "citation_detail": [{"chunk_uid": c.get("chunk_uid"),
                                         "quote": (c.get("quote") or "")[:200]}
                                        for c in (res["citations"] or [])],
                    "contexts": [c[:400] for c in contexts[:3]],
                    "max_score": res["retrieval"].get("max_score"),
                    "tau": res["retrieval"].get("tau"),
                    "latency_ms": res["latency_ms"], "judge": verdict,
                }
                rows.append(row)
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                fh.flush()
                print(f"[{idx}/{len(questions)}] {mode} q{q['seq']} "
                      f"{row['judge']['verdict']} hall={row['judge']['hallucination']} "
                      f"{res['latency_ms']}ms", flush=True)

    result = {
        "meta": {
            "started_at": started.isoformat(), "dataset_id": args.dataset_id,
            "total": len(questions), "modes": args.modes,
            "model": getattr(llm, "model", "deepseek-chat"),
            "embedder": getattr(getattr(qa.orch, "retriever", None), "embedder", None)
            and getattr(qa.orch.retriever.embedder, "name", "?"),
            "rerank": get_reranker() is not None,
            "tau": cfg.get("retrieval.tau"), "tau_cosine": cfg.get("retrieval.tau_cosine"),
            "elapsed_s": int(time.time() - t0),
        },
        "metrics": summarize(rows, args.modes),
    }
    (out_dir / f"{stem}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / f"{stem}.md").write_text(to_markdown(result), encoding="utf-8")

    print("\n" + to_markdown(result))
    print(f"结果 -> {out_dir / stem}.json / .md / .jsonl")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
