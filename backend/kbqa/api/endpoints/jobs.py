"""索引任务接口（API-10、API-30）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from kbqa.api.deps import get_db
from kbqa.api.exception_handlers import ApiError, ErrorCode
from kbqa.api.response import ok, page
from kbqa.infra.db.repositories import DocumentRepo, JobRepo

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _job_item(j, title: str | None = None) -> dict:
    return {
        "job_id": j.id, "job_type": j.job_type, "document_id": j.doc_id,
        "document_title": title, "status": j.status, "progress": j.progress,
        "total_steps": j.total_steps, "done_steps": j.done_steps,
        "message": j.message, "error_code": j.error_code, "error_detail": j.error_detail,
        "started_at": j.started_at.isoformat() if j.started_at else None,
        "finished_at": j.finished_at.isoformat() if j.finished_at else None,
    }


@router.get("/{job_id}")
def get_job(job_id: int, db: Session = Depends(get_db)) -> dict:
    j = JobRepo(db).get(job_id)
    if j is None:
        raise ApiError(ErrorCode.DOC_NOT_FOUND, "任务不存在")
    title = DocumentRepo(db).get(j.doc_id).title if j.doc_id else None
    return ok(_job_item(j, title))


@router.get("")
def list_jobs(status: str | None = None, page_no: int = Query(1, ge=1, alias="page"),
              size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)) -> dict:
    rows, total = JobRepo(db).list(status=status, page=page_no, size=size)
    return page([_job_item(j) for j in rows], total, page_no, size)
