"""数据访问层：只做 CRUD，不写业务逻辑，不自己 commit。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Sequence

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from kbqa.infra.db import models as m


class DocumentRepo:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, **kw) -> m.Document:
        doc = m.Document(**kw)
        self.db.add(doc)
        self.db.flush()
        return doc

    def get(self, doc_id: int) -> m.Document | None:
        return self.db.get(m.Document, doc_id)

    def find_by_hash(self, file_hash: str) -> m.Document | None:
        return self.db.scalar(select(m.Document).where(m.Document.file_hash == file_hash))

    def list(self, *, page: int = 1, size: int = 20, status: str | None = None,
             keyword: str | None = None) -> tuple[list[m.Document], int]:
        stmt = select(m.Document)
        count_stmt = select(func.count()).select_from(m.Document)
        if status:
            stmt = stmt.where(m.Document.status == status)
            count_stmt = count_stmt.where(m.Document.status == status)
        if keyword:
            cond = m.Document.title.like(f"%{keyword}%")
            stmt = stmt.where(cond)
            count_stmt = count_stmt.where(cond)
        total = int(self.db.scalar(count_stmt) or 0)
        stmt = stmt.order_by(m.Document.created_at.desc()).offset((page - 1) * size).limit(size)
        return list(self.db.scalars(stmt)), total

    def set_status(self, doc_id: int, status: str) -> None:
        self.db.execute(update(m.Document).where(m.Document.id == doc_id)
                        .values(status=status))

    def mark_ready(self, doc_id: int, *, chunk_count: int, strategy: str,
                   params: dict, char_count: int, page_count: int | None,
                   parsed_meta: dict) -> None:
        self.db.execute(update(m.Document).where(m.Document.id == doc_id).values(
            status="ready", chunk_count=chunk_count, chunk_strategy=strategy,
            chunk_params=params, char_count=char_count, page_count=page_count,
            parsed_meta=parsed_meta, error_code=None, error_detail=None,
            updated_at=datetime.now()))

    def mark_failed(self, doc_id: int, code: str, detail: str) -> None:
        self.db.execute(update(m.Document).where(m.Document.id == doc_id).values(
            status="failed", error_code=code, error_detail=detail[:2000]))

    def delete(self, doc_id: int) -> None:
        self.db.execute(delete(m.Document).where(m.Document.id == doc_id))


class ChunkRepo:
    def __init__(self, db: Session) -> None:
        self.db = db

    def bulk_insert(self, rows: Sequence[dict[str, Any]]) -> int:
        if not rows:
            return 0
        self.db.execute(m.Chunk.__table__.insert(), list(rows))
        return len(rows)

    def count_by_doc(self, doc_id: int) -> int:
        return int(self.db.scalar(
            select(func.count()).select_from(m.Chunk).where(m.Chunk.doc_id == doc_id)) or 0)

    def list_by_doc(self, doc_id: int, *, page: int = 1, size: int = 20) -> tuple[list[m.Chunk], int]:
        total = self.count_by_doc(doc_id)
        stmt = (select(m.Chunk).where(m.Chunk.doc_id == doc_id)
                .order_by(m.Chunk.chunk_index).offset((page - 1) * size).limit(size))
        return list(self.db.scalars(stmt)), total

    def find_by_uids(self, uids: list[str]) -> dict[str, tuple[m.Chunk, m.Document]]:
        if not uids:
            return {}
        stmt = (select(m.Chunk, m.Document)
                .join(m.Document, m.Document.id == m.Chunk.doc_id)
                .where(m.Chunk.chunk_uid.in_(uids)))
        return {c.chunk_uid: (c, d) for c, d in self.db.execute(stmt).all()}

    def delete_by_doc(self, doc_id: int) -> int:
        res = self.db.execute(delete(m.Chunk).where(m.Chunk.doc_id == doc_id))
        return res.rowcount or 0


class JobRepo:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, *, job_type: str, doc_id: int | None) -> m.IndexJob:
        job = m.IndexJob(job_type=job_type, doc_id=doc_id, status="queued")
        self.db.add(job)
        self.db.flush()
        return job

    def get(self, job_id: int) -> m.IndexJob | None:
        return self.db.get(m.IndexJob, job_id)

    def mark_running(self, job_id: int) -> None:
        self.db.execute(update(m.IndexJob).where(m.IndexJob.id == job_id)
                        .values(status="running", started_at=datetime.now()))

    def set_progress(self, job_id: int, done: int, total: int, message: str) -> None:
        progress = int(done * 100 / total) if total else 0
        self.db.execute(update(m.IndexJob).where(m.IndexJob.id == job_id).values(
            done_steps=done, total_steps=total, progress=min(progress, 99),
            message=message[:500]))

    def finish(self, job_id: int, status: str, *, error_code: str | None = None,
               error_detail: str | None = None) -> None:
        self.db.execute(update(m.IndexJob).where(m.IndexJob.id == job_id).values(
            status=status, progress=100 if status == "succeeded" else 0,
            error_code=error_code, error_detail=(error_detail or "")[:2000] or None,
            finished_at=datetime.now()))

    def repair_stale(self, detail: str = "进程重启中断") -> int:
        res = self.db.execute(
            update(m.IndexJob)
            .where(m.IndexJob.status.in_(["queued", "running"]))
            .values(status="failed", error_detail=detail, finished_at=datetime.now()))
        return res.rowcount or 0

    def list(self, *, status: str | None = None, page: int = 1,
             size: int = 20) -> tuple[list[m.IndexJob], int]:
        stmt = select(m.IndexJob)
        cnt = select(func.count()).select_from(m.IndexJob)
        if status:
            stmt = stmt.where(m.IndexJob.status == status)
            cnt = cnt.where(m.IndexJob.status == status)
        total = int(self.db.scalar(cnt) or 0)
        stmt = stmt.order_by(m.IndexJob.created_at.desc()).offset((page - 1) * size).limit(size)
        return list(self.db.scalars(stmt)), total
