"""问答编排：检索 → 阈值判定 → 生成 → 校验 → 兜底（见 03_核心机制/07）。

设计取舍：编排层**不碰数据库**。上下文由调用方加载后传入，结果由调用方落库。
这样它可以用假依赖完整测试，也便于离线跑评测。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Protocol

from kbqa.core.fallback.handler import FallbackHandler
from kbqa.core.generation.generator import Generator
from kbqa.core.generation.types import Turn
from kbqa.core.retrieval.types import Candidate, RetrievalResult


class Retriever(Protocol):
    async def retrieve(self, query: str, *, enable_rerank: bool = True,
                       debug: bool = False) -> RetrievalResult: ...


class Rewriter(Protocol):
    async def rewrite(self, question: str, history: list[Turn]) -> str: ...


@dataclass(slots=True)
class QaContext:
    history: list[Turn] = field(default_factory=list)
    summary: str | None = None
    session_id: int | None = None


@dataclass(slots=True)
class QaResult:
    question: str
    rewritten_question: str | None
    answer: str
    answer_status: str            # ok | fallback
    fallback_reason: str | None
    citations: list[Candidate] = field(default_factory=list)
    # chunk_uid -> 模型声称引用的原文（用于事后核验，落库留证）
    citation_quotes: dict = field(default_factory=dict)
    nearest: list[Candidate] = field(default_factory=list)
    retrieval: RetrievalResult | None = None
    llm_called: bool = False
    retry_count: int = 0
    error_code: str | None = None
    latency_ms: int = 0
    timing: dict = field(default_factory=dict)
    tokens: dict = field(default_factory=dict)

    @property
    def is_fallback(self) -> bool:
        return self.answer_status == "fallback"


class QaOrchestrator:
    def __init__(self, *, retriever: Retriever, generator: Generator,
                 fallback: FallbackHandler | None = None,
                 rewriter: Rewriter | None = None, tau: float = 0.30,
                 history_turns: int = 3, rewrite_enabled: bool = True,
                 answerability=None, answerability_min_score: float = 0.70) -> None:
        self.retriever = retriever
        self.generator = generator
        self.fallback = fallback or FallbackHandler()
        self.rewriter = rewriter
        self.answerability = answerability
        self.answerability_min_score = answerability_min_score
        self.tau = tau
        self.history_turns = history_turns
        self.rewrite_enabled = rewrite_enabled

    async def ask(self, *, question: str, ctx: QaContext | None = None,
                  mode: str = "L4") -> QaResult:
        t0 = time.perf_counter()
        ctx = ctx or QaContext()
        timing: dict[str, int] = {}

        # 1. 追问改写（仅当有历史）
        rewritten = None
        query = question
        if self.rewrite_enabled and self.rewriter is not None and ctx.history:
            t = time.perf_counter()
            try:
                candidate = await self.rewriter.rewrite(question, ctx.history[-self.history_turns:])
                if candidate and candidate.strip():
                    query = candidate.strip()
                    rewritten = query
            except Exception:  # noqa: BLE001 — 改写失败不阻断主流程
                query = question
            timing["rewrite_ms"] = int((time.perf_counter() - t) * 1000)

        # 2. 检索（L1 纯模型模式跳过）
        if mode == "L1":
            retrieval = RetrievalResult(candidates=[], passed=True, max_score=1.0)
        else:
            retrieval = await self.retriever.retrieve(
                query, enable_rerank=(mode != "L2"), debug=True)
            timing.update(retrieval.timing)

        # 3. 阈值判定（L3/L4 才拦；L1/L2 是对照组，不做拦截）
        if mode in ("L3", "L4") and not retrieval.passed:
            fb = self.fallback.insufficient_evidence(
                retrieval.candidates, retrieval.max_score, self.tau)
            return self._finish_fallback(t0, question, rewritten, fb, retrieval, timing)

        # 3.5 可答性判定（仅在 L4 且开启时）：把"资料不够"挡在生成之前
        if (mode == "L4" and self.answerability is not None
                and retrieval.max_score >= self.answerability_min_score):
            t_ab = time.perf_counter()
            verdict = await self.answerability.can_answer(query, retrieval.candidates)
            timing["answerability_ms"] = int((time.perf_counter() - t_ab) * 1000)
            if verdict is False:
                fb = self.fallback.insufficient_evidence(
                    retrieval.candidates, retrieval.max_score, self.tau)
                return self._finish_fallback(t0, question, rewritten, fb, retrieval,
                                             timing, llm_called=True)

        # 4. 生成（L1/L2 对照组只校验结构，不做引用校验）
        t = time.perf_counter()
        outcome = await self.generator.generate(
            query=query, candidates=retrieval.candidates,
            history=ctx.history if mode != "L1" else [],
            summary=ctx.summary if mode != "L1" else None,
            strict=(mode in ("L3", "L4")),
            plain=(mode == "L1"))
        timing["llm_ms"] = int((time.perf_counter() - t) * 1000)

        # 5. 收口
        if not outcome.ok:
            if outcome.llm_error:
                fb = self.fallback.llm_unavailable(outcome.llm_error)
            else:
                fb = self.fallback.validation_failed(outcome.issues)
            return self._finish_fallback(t0, question, rewritten, fb, retrieval,
                                         timing, outcome, llm_called=True)

        answer = outcome.answer
        used = self._used_candidates(answer, retrieval.candidates)
        quotes = {c.chunk_id: c.quote for c in getattr(answer, "citations", [])}
        timing["total_ms"] = int((time.perf_counter() - t0) * 1000)

        # 模型自己判定资料不足时，按"证据不足"落库，但保留它的说明（比固定话术更有信息量）
        if getattr(answer, "insufficient", False) and mode != "L1":
            fb = self.fallback.insufficient_evidence(
                retrieval.candidates, retrieval.max_score, self.tau)
            fb.answer = answer.answer
            return self._finish_fallback(t0, question, rewritten, fb, retrieval,
                                         timing, outcome, llm_called=True)

        return QaResult(
            question=question,
            rewritten_question=rewritten,
            answer=answer.answer,
            answer_status="ok",
            fallback_reason=None,
            citations=used,
            citation_quotes=quotes,
            retrieval=retrieval,
            llm_called=True,
            retry_count=outcome.retry_count,
            latency_ms=timing["total_ms"],
            timing=timing,
            tokens=outcome.tokens,
        )

    # ---------------- 辅助 ----------------
    @staticmethod
    def _used_candidates(answer, candidates: list[Candidate]) -> list[Candidate]:
        """只返回答案里真正引用到的片段，按引用顺序。"""
        by_id = {c.chunk_uid: c for c in candidates}
        out: list[Candidate] = []
        seen: set[str] = set()
        for cit in getattr(answer, "citations", []):
            if cit.chunk_id in by_id and cit.chunk_id not in seen:
                out.append(by_id[cit.chunk_id])
                seen.add(cit.chunk_id)
        return out

    def _finish_fallback(self, t0: float, question: str, rewritten: str | None,
                         fb, retrieval: RetrievalResult, timing: dict,
                         outcome=None, llm_called: bool = False) -> QaResult:
        timing["total_ms"] = int((time.perf_counter() - t0) * 1000)
        return QaResult(
            question=question,
            rewritten_question=rewritten,
            answer=fb.answer,
            answer_status="fallback",
            fallback_reason=fb.reason,
            citations=[],
            nearest=getattr(fb, "nearest", []),
            retrieval=retrieval,
            llm_called=llm_called or fb.llm_called,
            retry_count=getattr(outcome, "retry_count", 0) if outcome else 0,
            error_code=fb.error_code,
            latency_ms=timing["total_ms"],
            timing=timing,
        )


__all__ = ["QaOrchestrator", "QaContext", "QaResult", "Retriever", "Rewriter"]
