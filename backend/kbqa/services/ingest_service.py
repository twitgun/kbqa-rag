"""文档接入编排：校验 → 落盘 → 建文档 → 后台解析/切分/索引。"""

from __future__ import annotations

import logging
from pathlib import Path

from kbqa.api.exception_handlers import ApiError, ErrorCode
from kbqa.core.chunking import ChunkParams
from kbqa.core.ingest.base import ParserRegistry
from kbqa.core.ingest.types import EmptyDocumentError, ParseError
from kbqa.core.indexing import IndexService
from kbqa.infra.db import session as dbsession
from kbqa.infra.db import models as m
from kbqa.infra.db.repositories import ChunkRepo, DocumentRepo
from kbqa.infra.jobs.runner import JobContext, JobRunner
from kbqa.infra.storage.file_store import FileStore
from kbqa.settings import settings

logger = logging.getLogger("kbqa.ingest")

ALLOWED_EXT = {"docx", "pdf", "md", "txt", "xlsx"}
MAX_SIZE_MB = 50


class IngestService:
    def __init__(self, *, store: FileStore, jobs: JobRunner,
                 index_service: IndexService, params: ChunkParams) -> None:
        self.store = store
        self.jobs = jobs
        self.index_service = index_service
        self.params = params

    async def upload(self, *, filename: str, data: bytes, auto_index: bool = True) -> dict:
        ext = Path(filename).suffix.lower().lstrip(".")
        if ext not in ALLOWED_EXT:
            raise ApiError(ErrorCode.UNSUPPORTED_FORMAT,
                           f"不支持 .{ext}，仅支持 {', '.join(sorted(ALLOWED_EXT))}")
        if len(data) > MAX_SIZE_MB * 1024 * 1024:
            raise ApiError(ErrorCode.FILE_TOO_LARGE, f"文件超过 {MAX_SIZE_MB}MB")
        if self.store.free_space_gb() < 1.0:
            raise ApiError(ErrorCode.FILE_TOO_LARGE, "磁盘空间不足")

        sha, rel = self.store.save(data, ext)

        with dbsession.SessionLocal() as db:
            repo = DocumentRepo(db)
            existing = repo.find_by_hash(sha)
            if existing:
                return {"document_id": existing.id, "job_id": None, "is_duplicate": True,
                        "filename": filename, "size": len(data)}
            doc = repo.create(title=Path(filename).stem[:255], original_filename=filename,
                              file_ext=ext, file_hash=sha, file_path=rel,
                              file_size=len(data), status="pending")
            doc_id = doc.id
            db.commit()

        job_id = None
        if auto_index:
            job_id = self.jobs.submit(job_type="ingest", doc_id=doc_id,
                                      fn=lambda ctx: self._do_ingest(ctx, doc_id))
        return {"document_id": doc_id, "job_id": job_id, "is_duplicate": False,
                "filename": filename, "size": len(data)}

    def _do_ingest(self, ctx: JobContext, doc_id: int) -> None:
        with dbsession.SessionLocal() as db:
            repo = DocumentRepo(db)
            doc = repo.get(doc_id)
            if doc is None:
                raise ApiError(ErrorCode.DOC_NOT_FOUND, "文档不存在")
            repo.set_status(doc_id, "parsing")
            db.commit()
            file_path = self.store.path_of(doc.file_path)
            ext = doc.file_ext

        try:
            parsed = ParserRegistry.get(ext).parse(file_path)
        except EmptyDocumentError as exc:
            with dbsession.SessionLocal() as db:
                DocumentRepo(db).mark_failed(doc_id, ErrorCode.EMPTY_DOCUMENT, str(exc))
                db.commit()
            raise
        except ParseError as exc:
            with dbsession.SessionLocal() as db:
                DocumentRepo(db).mark_failed(doc_id, ErrorCode.PARSE_FAILED, str(exc))
                db.commit()
            raise

        with dbsession.SessionLocal() as db:
            DocumentRepo(db).set_status(doc_id, "indexing")
            db.commit()

        with dbsession.SessionLocal() as db:
            doc = DocumentRepo(db).get(doc_id)
            n = self.index_service.index_document(
                db, doc, parsed, self.params,
                progress=lambda done, total, msg: ctx.set_progress(done, total, msg))
            db.commit()
        logger.info("ingest_done doc_id=%s chunks=%s", doc_id, n)

    def delete(self, doc_id: int) -> dict:
        with dbsession.SessionLocal() as db:
            doc = DocumentRepo(db).get(doc_id)
            if doc is None:
                raise ApiError(ErrorCode.DOC_NOT_FOUND, "文档不存在")
            n = ChunkRepo(db).count_by_doc(doc_id)
            rel = doc.file_path
            DocumentRepo(db).delete(doc_id)
            db.commit()

        self.index_service.vector_store.delete_by_doc(doc_id)
        self.index_service.bm25.remove_by_doc(doc_id)
        self.index_service.bm25.persist()
        self.index_service.vector_store.persist()
        self.store.delete(rel)
        return {"document_id": doc_id, "deleted_chunks": n}

    def reindex(self, doc_id: int, params: ChunkParams | None = None) -> int:
        with dbsession.SessionLocal() as db:
            doc = DocumentRepo(db).get(doc_id)
            if doc is None:
                raise ApiError(ErrorCode.DOC_NOT_FOUND, "文档不存在")
            DocumentRepo(db).set_status(doc_id, "indexing")
            db.commit()

        def job(ctx: JobContext) -> None:
            with dbsession.SessionLocal() as db:
                d = DocumentRepo(db).get(doc_id)
                parsed = ParserRegistry.get(d.file_ext).parse(self.store.path_of(d.file_path))
                self.index_service.index_document(
                    db, d, parsed, params or self.params,
                    progress=lambda done, total, msg: ctx.set_progress(done, total, msg))
                db.commit()

        return self.jobs.submit(job_type="reindex", doc_id=doc_id, fn=job)
