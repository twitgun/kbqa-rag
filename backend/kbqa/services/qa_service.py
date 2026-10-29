"""问答服务：加载会话上下文 → 调编排 → 落库 → 返回前端结构。"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from kbqa.config.runtime import load_config
from kbqa.core.generation.types import Turn
from kbqa.core.orchestration import QaContext, QaOrchestrator
from kbqa.infra.db import models as m
from kbqa.infra.db.session import SessionLocal
from kbqa.services.summary_service import SummaryService

logger = logging.getLogger("kbqa.qa")


class QaService:
    def __init__(self, orchestrator: QaOrchestrator) -> None:
        self.orch = orchestrator

    # ---------------- 会话 ----------------
    @staticmethod
    def ensure_session(db, session_id: int | None, question: str) -> m.Session:
        if session_id is not None:
            s = db.get(m.Session, session_id)
            if s is not None:
                return s
        title = question.strip()[:20] + ("…" if len(question.strip()) > 20 else "")
        s = m.Session(title=title or "新会话")
        db.add(s)
        db.flush()
        return s

    @staticmethod
    def load_context(db, session_id: int, turns: int = 3) -> QaContext:
        rows = list(db.scalars(
            select(m.Message).where(m.Message.session_id == session_id)
            .order_by(m.Message.created_at).limit(40)))
        history: list[Turn] = []
        pending = None
        for msg in rows:
            if msg.msg_role == "user":
                pending = msg
            elif msg.msg_role == "assistant" and pending is not None:
                history.append(Turn(question=pending.content, answer=msg.content,
                                    is_fallback=bool((msg.meta or {}).get("is_fallback"))))
                pending = None
        session = db.get(m.Session, session_id)
        return QaContext(history=history[-turns:],
                         summary=getattr(session, "summary", None),
                         session_id=session_id)

    # ---------------- 主流程 ----------------
    async def ask(self, *, question: str, session_id: int | None = None,
                  mode: str = "L4", debug: bool = True) -> dict:
        question = question.strip()
        with SessionLocal() as db:
            session = self.ensure_session(db, session_id, question)
            ctx = self.load_context(db, session.id)
            sid = session.id
            db.commit()

        result = await self.orch.ask(question=question, ctx=ctx, mode=mode)

        with SessionLocal() as db:
            user_msg = m.Message(session_id=sid, msg_role="user", content=question)
            db.add(user_msg)
            db.flush()

            citations = [{
                "index": i, "chunk_uid": c.chunk_uid, "doc_id": c.doc_id,
                "doc_title": c.doc_title, "page_no": c.page_no,
                "section_path": c.section_path, "char_start": c.char_start,
                "char_end": c.char_end, "snippet": c.text[:80],
                "quote": (getattr(result, "citation_quotes", {}) or {}).get(c.chunk_uid),
                "score": round(c.rerank_score if c.rerank_score is not None else c.rrf_score, 4),
            } for i, c in enumerate(result.citations, 1)]

            qa = m.QaRecord(
                trace_id=f"{sid:04d}{int(datetime.now().timestamp() * 1000) % 10**8:08d}",
                session_id=sid, message_id=None, question=question,
                rewritten_question=result.rewritten_question,
                answer=result.answer, answer_status=result.answer_status,
                fallback_reason=result.fallback_reason,
                citations=citations or None,
                retrieved_chunks=[{"chunk_uid": c.chunk_uid, "rrf": round(c.rrf_score, 5),
                                   "vector": c.vector_score, "bm25": c.bm25_score}
                                  for c in (result.retrieval.all_fused if result.retrieval else [])] or None,
                retrieval_meta={
                    "max_score": round(result.retrieval.max_score, 4) if result.retrieval else 0,
                    "tau": round(result.retrieval.tau, 4) if result.retrieval else 0.30,
                    "passed": bool(result.retrieval.passed) if result.retrieval else False,
                    "rerank_degraded": bool(result.retrieval.degraded) if result.retrieval else True,
                },
                llm_called=result.llm_called, retry_count=result.retry_count,
                latency_ms=result.latency_ms, latency_breakdown=result.timing,
                config_snapshot=load_config(), error_code=result.error_code,
                mode=mode,
            )
            db.add(qa)
            db.flush()

            asst = m.Message(session_id=sid, msg_role="assistant", content=result.answer,
                             qa_id=qa.id,
                             meta={"is_fallback": result.is_fallback,
                                   "citations_count": len(citations),
                                   "rewritten_question": result.rewritten_question})
            db.add(asst)
            db.flush()

            s = db.get(m.Session, sid)
            s.message_count = (s.message_count or 0) + 2
            s.turn_count = (s.turn_count or 0) + 1
            s.last_active_at = datetime.now()
            db.commit()

            qa_id, asst_id = qa.id, asst.id
            turn_count = s.turn_count or 0

        # FR-28：轮数达到阈值后压缩早期历史（失败不影响本次回答）
        await self._maybe_summarize(sid, turn_count)

        return {
            "qa_id": qa_id, "session_id": sid, "message_id": asst_id,
            "question": result.question,
            "rewritten_question": result.rewritten_question,
            "answer": result.answer,
            "answer_status": result.answer_status,
            "is_fallback": result.is_fallback,
            "fallback_reason": result.fallback_reason,
            "citations": citations,
            "suggestions": None,
            "retrieval": {
                "max_score": round(result.retrieval.max_score, 4) if result.retrieval else 0.0,
                "tau": round(result.retrieval.tau, 4) if result.retrieval else 0.30,
                "passed": bool(result.retrieval.passed) if result.retrieval else False,
                "rerank_degraded": bool(result.retrieval.degraded) if result.retrieval else True,
                "candidates": [
                    {"chunk_uid": c.chunk_uid,
                     "rrf": round(c.rrf_score, 5),
                     "vector": c.vector_score,
                     "rerank": c.rerank_score}
                    for c in (result.retrieval.all_fused if result.retrieval else [])
                ],
            },
            "latency_ms": result.latency_ms,
            "latency_breakdown": result.timing,
            "tokens": result.tokens,
        }

    async def _maybe_summarize(self, session_id: int, turn_count: int) -> None:
        """FR-28：轮数到达触发点时，把「最近 history_turns 轮之外」的历史压成摘要。

        摘要失败不影响本次问答——它只影响后续几轮的上下文长度。
        """
        config = load_config()
        trigger = int(config.get("conversation.summary_trigger_turns", 6))
        keep = int(config.get("conversation.history_turns", 3))
        max_chars = int(config.get("conversation.summary_max_chars", 200))
        if turn_count < trigger or turn_count % trigger != 0:
            return
        try:
            with SessionLocal() as db:
                ctx = self.load_context(db, session_id, turns=40)
            older = ctx.history[:-keep]
            if not older:
                return
            svc = SummaryService(self.orch.generator.llm,
                                 Path(__file__).resolve().parents[1] / "prompts",
                                 max_chars=max_chars)
            summary = await svc.summarize(older)
            if not summary:
                return
            with SessionLocal() as db:
                s = db.get(m.Session, session_id)
                s.summary = summary
                db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("summarize_skipped: %s", exc)

    def ask_sync(self, *, question: str, session_id: int | None = None,
                 mode: str = "L4", debug: bool = True) -> dict:
        """供后台线程（评测批跑）调用的同步入口。"""
        import asyncio
        return asyncio.run(self.ask(question=question, session_id=session_id,
                                    mode=mode, debug=debug))
