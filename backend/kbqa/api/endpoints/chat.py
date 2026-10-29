"""问答接口（API-12）与会话接口（API-13~16）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from kbqa.api.deps import get_db, get_qa_service
from kbqa.api.exception_handlers import ApiError, ErrorCode
from kbqa.api.response import ok, page
from kbqa.infra.db import models as m
from kbqa.services.qa_service import QaService

chat_router = APIRouter(prefix="/chat", tags=["chat"])
session_router = APIRouter(prefix="/sessions", tags=["sessions"])


@chat_router.post("/ask")
async def ask(body: dict, svc: QaService = Depends(get_qa_service)) -> dict:
    question = (body.get("question") or "").strip()
    if not question:
        raise ApiError(ErrorCode.INVALID_PARAM, "问题不能为空")
    if len(question) > 1000:
        raise ApiError(ErrorCode.INVALID_PARAM, "问题过长（上限 1000 字）")
    mode = body.get("mode") or "L4"
    if mode not in ("L1", "L2", "L3", "L4"):
        raise ApiError(ErrorCode.INVALID_PARAM, "mode 只能是 L1~L4")

    data = await svc.ask(question=question, session_id=body.get("session_id"), mode=mode)
    msg = "未在知识库中找到足够依据" if data["fallback_reason"] == "insufficient_evidence" else "ok"
    return ok(data, message=msg)


@session_router.get("")
def list_sessions(db: Session = Depends(get_db),
                  page_no: int = Query(1, ge=1, alias="page"),
                  size: int = Query(20, ge=1, le=100)) -> dict:
    total = int(db.scalar(select(func.count()).select_from(m.Session)) or 0)
    rows = list(db.scalars(select(m.Session).order_by(m.Session.last_active_at.desc())
                           .offset((page_no - 1) * size).limit(size)))
    items = [{"id": s.id, "title": s.title, "message_count": s.message_count,
              "turn_count": s.turn_count, "summary": s.summary,
              "created_at": s.created_at.isoformat() if s.created_at else None,
              "last_active_at": s.last_active_at.isoformat() if s.last_active_at else None}
             for s in rows]
    return page(items, total, page_no, size)


@session_router.post("")
def create_session(body: dict | None = None, db: Session = Depends(get_db)) -> dict:
    s = m.Session(title=(body or {}).get("title") or "新会话")
    db.add(s)
    db.commit()
    return ok({"id": s.id, "title": s.title})


@session_router.get("/{session_id}/messages")
def list_messages(session_id: int, db: Session = Depends(get_db),
                  page_no: int = Query(1, ge=1, alias="page"),
                  size: int = Query(50, ge=1, le=200)) -> dict:
    if db.get(m.Session, session_id) is None:
        raise ApiError(ErrorCode.SESSION_NOT_FOUND, "会话不存在")
    total = int(db.scalar(select(func.count()).select_from(m.Message)
                          .where(m.Message.session_id == session_id)) or 0)
    rows = list(db.scalars(select(m.Message).where(m.Message.session_id == session_id)
                           .order_by(m.Message.created_at)
                           .offset((page_no - 1) * size).limit(size)))
    items = [{"id": x.id, "role": x.msg_role, "content": x.content, "qa_id": x.qa_id,
              "meta": x.meta,
              "created_at": x.created_at.isoformat() if x.created_at else None} for x in rows]
    return page(items, total, page_no, size)


@session_router.delete("/{session_id}")
def delete_session(session_id: int, db: Session = Depends(get_db)) -> dict:
    if db.get(m.Session, session_id) is None:
        raise ApiError(ErrorCode.SESSION_NOT_FOUND, "会话不存在")
    db.delete(db.get(m.Session, session_id))
    db.commit()
    return ok({"deleted": session_id})


@session_router.patch("/{session_id}")
def rename_session(session_id: int, body: dict, db: Session = Depends(get_db)) -> dict:
    s = db.get(m.Session, session_id)
    if s is None:
        raise ApiError(ErrorCode.SESSION_NOT_FOUND, "会话不存在")
    title = (body.get("title") or "").strip()
    if not title:
        raise ApiError(ErrorCode.INVALID_PARAM, "标题不能为空")
    s.title = title[:120]
    db.commit()
    return ok({"id": s.id, "title": s.title})
