"""问答日志接口（API-17 ~ API-19）。"""

from __future__ import annotations

import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from kbqa.api.deps import get_db
from kbqa.api.exception_handlers import ApiError, ErrorCode
from kbqa.api.response import ok, page
from kbqa.infra.db import models as m

router = APIRouter(prefix="/logs", tags=["logs"])


def _filters(stmt, *, is_fallback: bool | None, reason: str | None,
             keyword: str | None, start: str | None, end: str | None, has_feedback: bool | None):
    if is_fallback is not None:
        stmt = stmt.where(m.QaRecord.answer_status == ("fallback" if is_fallback else "ok"))
    if reason:
        stmt = stmt.where(m.QaRecord.fallback_reason == reason)
    if keyword:
        stmt = stmt.where(m.QaRecord.question.like(f"%{keyword}%"))
    if start:
        stmt = stmt.where(m.QaRecord.created_at >= datetime.fromisoformat(start))
    if end:
        stmt = stmt.where(m.QaRecord.created_at <= datetime.fromisoformat(end))
    if has_feedback:
        sub = select(m.Feedback.qa_id)
        stmt = stmt.where(m.QaRecord.id.in_(sub))
    return stmt


@router.get("/qa")
def list_logs(
    db: Session = Depends(get_db),
    page_no: int = Query(1, ge=1, alias="page"),
    size: int = Query(20, ge=1, le=100),
    is_fallback: bool | None = None,
    reason: str | None = None,
    keyword: str | None = None,
    start: str | None = None,
    end: str | None = None,
    has_feedback: bool | None = None,
) -> dict:
    stmt = select(m.QaRecord)
    cnt = select(func.count()).select_from(m.QaRecord)
    kwargs = dict(is_fallback=is_fallback, reason=reason, keyword=keyword,
                  start=start, end=end, has_feedback=has_feedback)
    stmt = _filters(stmt, **kwargs)
    cnt = _filters(cnt, **kwargs)

    total = int(db.scalar(cnt) or 0)
    rows = list(db.scalars(stmt.order_by(m.QaRecord.id.desc())
                           .offset((page_no - 1) * size).limit(size)))

    fb = {f.qa_id: f.rating for f in db.scalars(
        select(m.Feedback).where(m.Feedback.qa_id.in_([r.id for r in rows] or [0])))}

    items = [{
        "id": r.id, "trace_id": r.trace_id, "question": r.question,
        "answer_preview": (r.answer or "")[:120],
        "answer_status": r.answer_status, "fallback_reason": r.fallback_reason,
        "latency_ms": r.latency_ms, "mode": r.mode, "rating": fb.get(r.id),
        "max_score": (r.retrieval_meta or {}).get("max_score"),
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in rows]
    return page(items, total, page_no, size)


@router.get("/qa/{qa_id}")
def get_log(qa_id: int, db: Session = Depends(get_db)) -> dict:
    r = db.get(m.QaRecord, qa_id)
    if r is None:
        raise ApiError(ErrorCode.QA_NOT_FOUND, "问答记录不存在")
    return ok({
        "id": r.id, "trace_id": r.trace_id, "session_id": r.session_id,
        "question": r.question, "rewritten_question": r.rewritten_question,
        "answer": r.answer, "answer_status": r.answer_status,
        "fallback_reason": r.fallback_reason, "citations": r.citations,
        "retrieved_chunks": r.retrieved_chunks, "retrieval_meta": r.retrieval_meta,
        "llm_called": r.llm_called, "retry_count": r.retry_count,
        "latency_ms": r.latency_ms, "latency_breakdown": r.latency_breakdown,
        "config_snapshot": r.config_snapshot, "error_code": r.error_code,
        "mode": r.mode,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    })


COLUMNS = ["id", "trace_id", "question", "rewritten_question", "answer", "answer_status",
           "fallback_reason", "max_score", "latency_ms", "mode", "created_at"]


@router.get("/qa/export")
def export_logs(db: Session = Depends(get_db), fmt: str = Query("csv", pattern="^(csv|jsonl)$")):
    rows = list(db.scalars(select(m.QaRecord).order_by(m.QaRecord.id.desc()).limit(50000)))

    def gen():
        if fmt == "csv":
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(COLUMNS)
            yield "\ufeff" + buf.getvalue()          # BOM：Excel 打开中文不乱码
            for r in rows:
                buf = io.StringIO()
                csv.writer(buf).writerow([
                    r.id, r.trace_id, r.question, r.rewritten_question or "",
                    (r.answer or "").replace("\n", " "), r.answer_status,
                    r.fallback_reason or "", (r.retrieval_meta or {}).get("max_score"),
                    r.latency_ms, r.mode,
                    r.created_at.isoformat() if r.created_at else "",
                ])
                yield buf.getvalue()
        else:
            import json
            for r in rows:
                yield json.dumps({
                    "id": r.id, "trace_id": r.trace_id, "question": r.question,
                    "answer": r.answer, "answer_status": r.answer_status,
                    "fallback_reason": r.fallback_reason, "latency_ms": r.latency_ms,
                    "mode": r.mode,
                }, ensure_ascii=False) + "\n"

    filename = f"qa_logs_{datetime.now():%Y%m%d_%H%M%S}.{fmt}"
    return StreamingResponse(
        gen(),
        media_type="text/csv; charset=utf-8" if fmt == "csv" else "application/x-ndjson",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'})
