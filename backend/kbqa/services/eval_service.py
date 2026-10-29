"""评测服务：导入数据集 → 批量跑 → 算指标 → 出报告（FR-38~42）。

设计：编排层复用 `QaService.ask`，保证"评测跑的就是线上链路"，否则数字不可信。
"""

from __future__ import annotations

import asyncio

import json
import logging
from collections import Counter
from datetime import datetime

from sqlalchemy import func, select

from kbqa.core.evaluation import compute_run_metrics
from kbqa.infra.db import models as m
from kbqa.infra.db.session import SessionLocal
from kbqa.services.qa_service import QaService

logger = logging.getLogger("kbqa.eval")

VALID_MODES = ("L1", "L2", "L3", "L4")


class DatasetImportError(Exception):
    pass


def parse_jsonl(text: str) -> tuple[list[dict], list[dict]]:
    """解析评测集 JSONL，返回 (合法题, 错误列表)。坏行跳过并记行号。"""
    good: list[dict] = []
    errors: list[dict] = []
    seen: set[int] = set()

    for lineno, raw in enumerate(text.splitlines(), 1):
        raw = raw.strip()
        if not raw:
            continue
        try:
            item = json.loads(raw)
        except json.JSONDecodeError as exc:
            errors.append({"line": lineno, "reason": f"JSON 解析失败：{exc.msg}"})
            continue

        seq = item.get("seq")
        if not isinstance(seq, int):
            errors.append({"line": lineno, "reason": "seq 缺失或不是整数"})
            continue
        if seq in seen:
            errors.append({"line": lineno, "reason": f"seq={seq} 重复"})
            continue
        if not (item.get("question") or "").strip():
            errors.append({"line": lineno, "reason": "question 为空"})
            continue
        qtype = item.get("qtype")
        if qtype not in ("answerable", "unanswerable"):
            errors.append({"line": lineno, "reason": f"qtype 非法：{qtype}"})
            continue
        if qtype == "answerable" and not (item.get("gold_answer") or "").strip():
            errors.append({"line": lineno, "reason": "有答案题缺少 gold_answer"})
            continue

        seen.add(seq)
        good.append(item)

    return good, errors


class EvalService:
    def __init__(self, qa: QaService, jobs) -> None:
        self.qa = qa
        self.jobs = jobs

    # ---------------- 数据集 ----------------
    def import_dataset(self, *, name: str, text: str,
                       description: str | None = None) -> dict:
        items, errors = parse_jsonl(text)
        if not items:
            raise DatasetImportError("没有可导入的题目：" + (errors[0]["reason"] if errors else ""))

        with SessionLocal() as db:
            exists = db.scalar(select(m.EvalDataset).where(m.EvalDataset.name == name))
            if exists:
                raise DatasetImportError(f"数据集 {name} 已存在")

            answerable = sum(1 for i in items if i["qtype"] == "answerable")
            ds = m.EvalDataset(
                name=name, description=description,
                question_count=len(items), answerable_count=answerable,
                unanswerable_count=len(items) - answerable)
            db.add(ds)
            db.flush()
            for item in items:
                db.add(m.EvalQuestion(
                    dataset_id=ds.id, seq=item["seq"], question=item["question"].strip(),
                    qtype=item["qtype"], gold_answer=item.get("gold_answer"),
                    gold_chunk_ids=item.get("gold_chunk_ids") or [],
                    gold_doc_ids=item.get("gold_doc_ids") or [],
                    difficulty=(item.get("difficulty") or "")[:10],
                    category=(item.get("category") or "")[:40],
                    notes=(item.get("notes") or "")[:500]))
            db.commit()
            ds_id = ds.id

        return {"dataset_id": ds_id, "question_count": len(items),
                "answerable_count": answerable,
                "unanswerable_count": len(items) - answerable,
                "skipped": len(errors), "errors": errors[:20]}

    # ---------------- 评测批次 ----------------
    def create_run(self, *, dataset_id: int, name: str, modes: list[str]) -> int:
        modes = [x for x in modes if x in VALID_MODES]
        if not modes:
            raise DatasetImportError("至少选一个有效模式（L1~L4）")

        with SessionLocal() as db:
            ds = db.get(m.EvalDataset, dataset_id)
            if ds is None:
                raise DatasetImportError("数据集不存在")
            total = ds.question_count * len(modes)
            run = m.EvalRun(dataset_id=dataset_id, name=name, modes=modes,
                            status="queued", total=total, config_snapshot={})
            db.add(run)
            db.commit()
            run_id = run.id

        self.jobs.submit(job_type="eval", doc_id=None,
                         fn=lambda ctx: self._run(ctx, run_id))
        return run_id

    def _run(self, ctx, run_id: int) -> None:
        with SessionLocal() as db:
            run = db.get(m.EvalRun, run_id)
            modes, dataset_id = list(run.modes), run.dataset_id
            run.status = "running"
            run.started_at = datetime.now()
            db.commit()

            qs = list(db.scalars(select(m.EvalQuestion)
                                 .where(m.EvalQuestion.dataset_id == dataset_id)
                                 .order_by(m.EvalQuestion.seq)))
            questions = [{"id": q.id, "seq": q.seq, "question": q.question,
                          "qtype": q.qtype, "gold_answer": q.gold_answer,
                          "gold_chunk_ids": list(q.gold_chunk_ids or [])} for q in qs]

        done = 0
        total = len(questions) * len(modes)
        # 整批复用一个事件循环：httpx.AsyncClient 绑定在创建它的 loop 上，
        # 若每题都用 asyncio.run() 新建/关闭 loop，第二题起就会 "Event loop is closed"。
        loop = asyncio.new_event_loop()
        try:
            for mode in modes:
                for q in questions:
                    try:
                        res = loop.run_until_complete(
                            self.qa.ask(question=q["question"], mode=mode))
                        retrieved = [c["chunk_uid"] for c in
                                     (res.get("retrieval", {}).get("candidates") or [])]
                        with SessionLocal() as db:
                            db.add(m.EvalItem(
                                run_id=run_id, question_id=q["id"], mode=mode,
                                answer=res["answer"], citations=res["citations"],
                                is_fallback=res["is_fallback"],
                                fallback_reason=res["fallback_reason"],
                                retrieved_chunk_ids=retrieved,
                                latency_ms=res["latency_ms"]))
                            db.commit()
                    except Exception as exc:  # noqa: BLE001
                        logger.exception("eval item failed run=%s q=%s", run_id, q["id"])
                        with SessionLocal() as db:
                            db.add(m.EvalItem(run_id=run_id, question_id=q["id"], mode=mode,
                                              error=f"{type(exc).__name__}: {exc}"[:500]))
                            run = db.get(m.EvalRun, run_id)
                            run.failed = (run.failed or 0) + 1
                            db.commit()
                    done += 1
                    with SessionLocal() as db:
                        run = db.get(m.EvalRun, run_id)
                        run.finished = done
                        db.commit()
                    ctx.set_progress(done, total, f"{mode} {q['seq']}")
        finally:
            loop.close()

        report = self.report(run_id)
        with SessionLocal() as db:
            run = db.get(m.EvalRun, run_id)
            run.metrics = report["metrics"]
            run.status = "succeeded" if not run.failed else "partial"
            run.finished_at = datetime.now()
            db.commit()

    # ---------------- 报告 ----------------
    def report(self, run_id: int) -> dict:
        with SessionLocal() as db:
            run = db.get(m.EvalRun, run_id)
            if run is None:
                raise DatasetImportError("评测批次不存在")
            items = list(db.scalars(select(m.EvalItem).where(m.EvalItem.run_id == run_id)))
            qs = list(db.scalars(select(m.EvalQuestion)
                                 .where(m.EvalQuestion.dataset_id == run.dataset_id)))
            ds = db.get(m.EvalDataset, run.dataset_id)

        questions = {q.id: {"qtype": q.qtype} for q in qs}
        rows = [{"question_id": i.question_id, "mode": i.mode,
                 "is_fallback": i.is_fallback, "judge": i.judge,
                 "recall5": float(i.recall5) if i.recall5 is not None else None,
                 "mrr10": float(i.mrr10) if i.mrr10 is not None else None,
                 "latency_ms": i.latency_ms} for i in items]
        metrics = compute_run_metrics(rows, questions)

        by_mode = metrics["by_mode"]
        return {
            "run_id": run_id, "dataset": ds.name if ds else None,
            "status": run.status, "total": run.total, "finished": run.finished,
            "metrics": by_mode,
            "charts": {
                "accuracy": {m_: by_mode[m_]["accuracy"] for m_ in by_mode},
                "hallucination": {m_: by_mode[m_]["hallucination_rate"] for m_ in by_mode},
            },
        }
