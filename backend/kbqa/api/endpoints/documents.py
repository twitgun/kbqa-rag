"""文档接口（API-01 ~ API-06）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy.orm import Session

from kbqa.api.deps import get_db, get_ingest_service
from kbqa.api.exception_handlers import ApiError, ErrorCode
from kbqa.api.response import ok, page
from kbqa.infra.db.repositories import ChunkRepo, DocumentRepo
from kbqa.services.ingest_service import IngestService

router = APIRouter(prefix="/documents", tags=["documents"])


def _doc_item(d) -> dict:
    return {
        "id": d.id, "title": d.title, "original_filename": d.original_filename,
        "file_ext": d.file_ext, "file_size": d.file_size, "char_count": d.char_count,
        "chunk_count": d.chunk_count, "status": d.status,
        "error_detail": d.error_detail,
        "created_at": d.created_at.isoformat() if d.created_at else None,
    }


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    auto_index: bool = Form(True),
    svc: IngestService = Depends(get_ingest_service),
) -> dict:
    if not file.filename:
        raise ApiError(ErrorCode.INVALID_PARAM, "缺少文件名")
    data = await file.read()
    result = await svc.upload(filename=file.filename, data=data, auto_index=auto_index)
    msg = "该文件已存在，可直接重建索引" if result["is_duplicate"] else "上传成功，已进入索引队列"
    return ok(result, message=msg)


@router.get("")
def list_documents(
    page_no: int = Query(1, ge=1, alias="page"),
    size: int = Query(20, ge=1, le=100),
    status: str | None = None,
    keyword: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    rows, total = DocumentRepo(db).list(page=page_no, size=size, status=status, keyword=keyword)
    return page([_doc_item(d) for d in rows], total, page_no, size)


@router.get("/{doc_id}")
def get_document(doc_id: int, db: Session = Depends(get_db)) -> dict:
    d = DocumentRepo(db).get(doc_id)
    if d is None:
        raise ApiError(ErrorCode.DOC_NOT_FOUND, "文档不存在或已被删除")
    item = _doc_item(d)
    item.update({
        "page_count": d.page_count, "chunk_strategy": d.chunk_strategy,
        "chunk_params": d.chunk_params, "parsed_meta": d.parsed_meta,
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
    })
    return ok(item)


@router.get("/{doc_id}/chunks")
def list_chunks(doc_id: int, page_no: int = Query(1, ge=1, alias="page"),
                size: int = Query(20, ge=1, le=100),
                db: Session = Depends(get_db)) -> dict:
    if DocumentRepo(db).get(doc_id) is None:
        raise ApiError(ErrorCode.DOC_NOT_FOUND, "文档不存在")
    rows, total = ChunkRepo(db).list_by_doc(doc_id, page=page_no, size=size)
    items = [{"chunk_uid": c.chunk_uid, "chunk_index": c.chunk_index, "text": c.text,
              "char_start": c.char_start, "char_end": c.char_end, "char_len": c.char_len,
              "page_no": c.page_no, "section_path": c.section_path,
              "token_count": c.token_count} for c in rows]
    return page(items, total, page_no, size)


@router.post("/{doc_id}/reindex")
def reindex(doc_id: int, svc: IngestService = Depends(get_ingest_service)) -> dict:
    job_id = svc.reindex(doc_id)
    return ok({"job_id": job_id, "document_id": doc_id})


@router.delete("/{doc_id}")
def delete_document(doc_id: int, svc: IngestService = Depends(get_ingest_service)) -> dict:
    return ok(svc.delete(doc_id))
