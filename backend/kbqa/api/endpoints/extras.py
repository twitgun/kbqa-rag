"""补齐缺口接口：格式列表、原文件下载、片段上下文、会话重命名。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from kbqa.api.deps import get_db
from kbqa.api.exception_handlers import ApiError, ErrorCode
from kbqa.api.response import ok
from kbqa.infra.db import models as m
from kbqa.infra.storage.file_store import FileStore
from kbqa.settings import settings

router = APIRouter(tags=["documents"])

FORMATS = [
    {"ext": "md", "label": "Markdown", "parser": "MarkdownParser", "enabled": True},
    {"ext": "docx", "label": "Word", "parser": "DocxParser", "enabled": True},
    {"ext": "pdf", "label": "PDF", "parser": "PdfParser", "enabled": True},
    {"ext": "txt", "label": "纯文本", "parser": "TextParser", "enabled": True},
    {"ext": "xlsx", "label": "Excel", "parser": "XlsxParser", "enabled": True},
]


@router.get("/documents/formats")
def list_formats() -> dict:
    return ok({"formats": FORMATS})


@router.get("/documents/{doc_id}/download")
def download_document(doc_id: int, db: Session = Depends(get_db)):
    doc = db.get(m.Document, doc_id)
    if doc is None:
        raise ApiError(ErrorCode.DOC_NOT_FOUND, "文档不存在")
    path = FileStore(settings.uploads_dir).path_of(doc.file_path)
    if not path.exists():
        raise ApiError(ErrorCode.DOC_NOT_FOUND, "原文件已丢失")
    return FileResponse(
        path=str(path), filename=doc.original_filename,
        media_type="application/octet-stream")


@router.get("/chunks/{chunk_uid}/context")
def chunk_context(chunk_uid: str, before: int = Query(1, ge=0, le=3),
                  after: int = Query(1, ge=0, le=3), db: Session = Depends(get_db)) -> dict:
    chunk = db.scalar(select(m.Chunk).where(m.Chunk.chunk_uid == chunk_uid))
    if chunk is None:
        raise ApiError(ErrorCode.DOC_NOT_FOUND, "片段不存在")

    doc = db.get(m.Document, chunk.doc_id)

    def item(c: m.Chunk) -> dict:
        return {"chunk_uid": c.chunk_uid, "chunk_index": c.chunk_index,
                "text": c.text, "char_start": c.char_start, "char_end": c.char_end,
                "section_path": c.section_path, "page_no": c.page_no}

    prevs = list(db.scalars(
        select(m.Chunk).where(m.Chunk.doc_id == chunk.doc_id,
                              m.Chunk.chunk_index < chunk.chunk_index)
        .order_by(m.Chunk.chunk_index.desc()).limit(before)))
    nexts = list(db.scalars(
        select(m.Chunk).where(m.Chunk.doc_id == chunk.doc_id,
                              m.Chunk.chunk_index > chunk.chunk_index)
        .order_by(m.Chunk.chunk_index).limit(after)))

    return ok({
        "chunk": item(chunk),
        "before": [item(c) for c in reversed(prevs)],
        "after": [item(c) for c in nexts],
        "document": {"id": doc.id, "title": doc.title, "file_ext": doc.file_ext,
                     "page_count": doc.page_count} if doc else None,
    })
