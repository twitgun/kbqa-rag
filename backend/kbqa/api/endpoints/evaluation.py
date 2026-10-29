"""评测接口（API-20 ~ API-25）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from kbqa.api.deps import get_db, get_eval_service
from kbqa.api.exception_handlers import ApiError, ErrorCode
from kbqa.api.response import ok, page
from kbqa.infra.db import models as m
from kbqa.services.eval_service import DatasetImportError, EvalService

router = APIRouter(prefix="/eval", tags=["evaluation"])


@router.post("/datasets/import")
async def import_dataset(
    file: UploadFile = File(...),
    name: str = Form(...),
    description: str = Form(""),
    svc: EvalService = Depends(get_eval_service),
) -> dict:
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ApiError(ErrorCode.INVALID_PARAM, "文件不是 UTF-8 编码") from None
    try:
        result = svc.import_dataset(name=name, text=text, description=description or None)
    except DatasetImportError as exc:
        raise ApiError(ErrorCode.INVALID_PARAM, str(exc)) from exc
    return ok(result)


@router.get("/datasets")
def list_datasets(db: Session = Depends(get_db)) -> dict:
    rows = list(db.scalars(select(m.EvalDataset).order_by(m.EvalDataset.id.desc())))
    items = [{"id": d.id, "name": d.name, "description": d.description,
              "question_count": d.question_count,
              "answerable_count": d.answerable_count,
              "unanswerable_count": d.unanswerable_count} for d in rows]
    return ok({"items": items, "total": len(items)})


@router.post("/runs")
def create_run(body: dict, svc: EvalService = Depends(get_eval_service)) -> dict:
    dataset_id = body.get("dataset_id")
    modes = body.get("modes") or ["L4"]
    name = body.get("name") or f"run-{dataset_id}"
    if not isinstance(dataset_id, int):
        raise ApiError(ErrorCode.INVALID_PARAM, "dataset_id 必须是整数")
    try:
        run_id = svc.create_run(dataset_id=dataset_id, name=name, modes=modes)
    except DatasetImportError as exc:
        raise ApiError(ErrorCode.INVALID_PARAM, str(exc)) from exc
    return ok({"run_id": run_id, "status": "queued"})


@router.get("/runs")
def list_runs(db: Session = Depends(get_db),
              page_no: int = Query(1, ge=1, alias="page"),
              size: int = Query(20, ge=1, le=100)) -> dict:
    total = int(db.scalar(select(func.count()).select_from(m.EvalRun)) or 0)
    rows = list(db.scalars(select(m.EvalRun).order_by(m.EvalRun.id.desc())
                           .offset((page_no - 1) * size).limit(size)))
    items = [{"run_id": r.id, "name": r.name, "dataset_id": r.dataset_id,
              "status": r.status, "total": r.total, "finished": r.finished,
              "failed": r.failed,
              "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]
    return page(items, total, page_no, size)


@router.get("/runs/{run_id}")
def get_run(run_id: int, db: Session = Depends(get_db)) -> dict:
    r = db.get(m.EvalRun, run_id)
    if r is None:
        raise ApiError(ErrorCode.INVALID_PARAM, "评测批次不存在")
    return ok({"run_id": r.id, "name": r.name, "status": r.status,
               "total": r.total, "finished": r.finished, "failed": r.failed,
               "modes": r.modes, "metrics": r.metrics,
               "started_at": r.started_at.isoformat() if r.started_at else None,
               "finished_at": r.finished_at.isoformat() if r.finished_at else None})


@router.get("/runs/{run_id}/items")
def list_items(run_id: int, mode: str | None = None, db: Session = Depends(get_db),
               page_no: int = Query(1, ge=1, alias="page"),
               size: int = Query(50, ge=1, le=200)) -> dict:
    stmt = select(m.EvalItem).where(m.EvalItem.run_id == run_id)
    cnt = select(func.count()).select_from(m.EvalItem).where(m.EvalItem.run_id == run_id)
    if mode:
        stmt = stmt.where(m.EvalItem.mode == mode)
        cnt = cnt.where(m.EvalItem.mode == mode)
    total = int(db.scalar(cnt) or 0)
    rows = list(db.scalars(stmt.order_by(m.EvalItem.id)
                           .offset((page_no - 1) * size).limit(size)))
    items = [{"id": i.id, "question_id": i.question_id, "mode": i.mode,
              "answer": i.answer, "is_fallback": i.is_fallback,
              "fallback_reason": i.fallback_reason, "judge": i.judge,
              "latency_ms": i.latency_ms, "error": i.error} for i in rows]
    return page(items, total, page_no, size)


@router.get("/runs/{run_id}/report")
def get_report(run_id: int, svc: EvalService = Depends(get_eval_service)) -> dict:
    try:
        return ok(svc.report(run_id))
    except DatasetImportError as exc:
        raise ApiError(ErrorCode.INVALID_PARAM, str(exc)) from exc


REPORT_COLUMNS = [
    ("accuracy", "正确率"), ("partial", "部分正确"), ("error", "错误率"),
    ("hallucination_rate", "幻觉率"), ("faithfulness", "忠实度"),
    ("abstention_accuracy", "正确拒答"), ("false_abstention", "误拒率"),
    ("recall5", "Recall@5"), ("mrr10", "MRR@10"),
    ("p50_ms", "P50(ms)"), ("p95_ms", "P95(ms)"),
]


@router.get("/runs/{run_id}/export")
def export_report(run_id: int, fmt: str = Query("markdown", pattern="^(markdown|md)$"),
                  svc: EvalService = Depends(get_eval_service)):
    """导出 Markdown 报告，便于归档与分享。"""
    from fastapi.responses import Response

    try:
        report = svc.report(run_id)
    except DatasetImportError as exc:
        raise ApiError(ErrorCode.INVALID_PARAM, str(exc)) from exc

    metrics: dict = report["metrics"]
    modes = sorted(metrics)

    lines = [
        f"# 评测报告 · {report.get('dataset') or ''}",
        "",
        f"- 批次：{run_id}",
        f"- 状态：{report.get('status')}",
        f"- 样本：{report.get('finished')}/{report.get('total')}",
        "",
        "## 总体指标",
        "",
        "| 指标 | " + " | ".join(modes) + " |",
        "|---" * (len(modes) + 1) + "|",
    ]
    for key, label in REPORT_COLUMNS:
        cells = []
        for mode in modes:
            v = metrics[mode].get(key)
            cells.append("—" if v is None else str(v))
        lines.append(f"| {label} | " + " | ".join(cells) + " |")

    lines += ["", "## 分题型样本数", "",
              "| 模式 | 可答 | 不可答 |",
              "|---|---|---|"]
    for mode in modes:
        lines.append(f"| {mode} | {metrics[mode].get('answerable')} | "
                     f"{metrics[mode].get('unanswerable')} |")

    body = "\n".join(lines) + "\n"
    return Response(content=body, media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition":
                             f'attachment; filename="eval_report_{run_id}.md"'})
