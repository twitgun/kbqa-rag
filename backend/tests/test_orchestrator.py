"""问答编排的分支测试：阈值拦截、正常作答、校验失败、模型异常、改写降级。"""

from __future__ import annotations

import asyncio
import json

from kbqa.core.fallback import FallbackHandler
from kbqa.core.generation import Generator, LLMUnavailable, PromptBuilder, RawCompletion, Turn
from kbqa.core.orchestration import QaContext, QaOrchestrator
from kbqa.core.retrieval.types import Candidate, RetrievalResult
from kbqa.core.validation import Validator
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parents[1] / "kbqa" / "prompts"

CAND = [
    Candidate(chunk_uid="d1_c00001", doc_id=1,
              text="allow_origins 不能设置为 [\"*\"]，当 allow_credentials 为 True 时。",
              doc_title="CORS", section_path="教程 > CORS"),
    Candidate(chunk_uid="d1_c00002", doc_id=1, text="CORSMiddleware 用于配置跨域。",
              doc_title="CORS", section_path="教程 > CORS"),
]

GOOD = json.dumps({
    "answer": "不能设为 *，必须显式列出 [1]",
    "citations": [{"chunk_id": "d1_c00001", "quote": "allow_origins 不能设置为"}],
    "insufficient": False, "confidence": 0.9}, ensure_ascii=False)


class FakeRetriever:
    def __init__(self, passed: bool, max_score: float = 0.8, candidates=None):
        self.passed = passed
        self.max_score = max_score
        self.candidates = candidates if candidates is not None else CAND
        self.called = 0

    async def retrieve(self, query, *, enable_rerank=True, debug=False):
        self.called += 1
        return RetrievalResult(candidates=self.candidates, max_score=self.max_score,
                               passed=self.passed, timing={"vector_ms": 10})


class FakeLLM:
    def __init__(self, texts, raise_error: str | None = None):
        self._texts = list(texts)
        self._raise = raise_error
        self.calls = 0

    async def complete(self, messages, **kw):
        self.calls += 1
        if self._raise:
            raise LLMUnavailable(self._raise, "boom")
        return RawCompletion(text=self._texts.pop(0), prompt_tokens=5, completion_tokens=3)


def _orch(retriever, llm) -> QaOrchestrator:
    gen = Generator(llm, PromptBuilder(PROMPT_DIR), Validator())
    return QaOrchestrator(retriever=retriever, generator=gen,
                          fallback=FallbackHandler(), tau=0.30)


def test_tau_block_skips_llm():
    llm = FakeLLM([GOOD])
    orch = _orch(FakeRetriever(passed=False, max_score=0.10), llm)
    r = asyncio.run(orch.ask(question="库外问题"))

    assert r.is_fallback and r.fallback_reason == "insufficient_evidence"
    assert r.llm_called is False
    assert llm.calls == 0, "证据不足时不应调用模型"
    assert r.error_code == "E-3001"


def test_normal_answer_returns_only_used_citations():
    orch = _orch(FakeRetriever(passed=True), FakeLLM([GOOD]))
    r = asyncio.run(orch.ask(question="怎么配 CORS"))

    assert r.answer_status == "ok" and not r.is_fallback
    assert len(r.citations) == 1 and r.citations[0].chunk_uid == "d1_c00001"
    assert r.retry_count == 0
    assert r.timing["total_ms"] >= 0


def test_validation_failure_falls_back():
    orch = _orch(FakeRetriever(passed=True), FakeLLM(["坏输出", "还是坏"]))
    r = asyncio.run(orch.ask(question="q"))

    assert r.is_fallback and r.fallback_reason == "validation_failed"
    assert r.error_code == "E-3004"


def test_llm_error_falls_back_with_e3002():
    orch = _orch(FakeRetriever(passed=True), FakeLLM([], raise_error="E-3002"))
    r = asyncio.run(orch.ask(question="q"))

    assert r.is_fallback and r.fallback_reason == "llm_unavailable"
    assert r.error_code == "E-3002"


def test_l1_mode_skips_retrieval():
    retriever = FakeRetriever(passed=True)
    orch = _orch(retriever, FakeLLM([GOOD]))
    r = asyncio.run(orch.ask(question="q", mode="L1"))

    assert retriever.called == 0
    assert r.answer_status == "ok"


def test_rewrite_failure_falls_back_to_original():
    class BadRewriter:
        async def rewrite(self, question, history):
            raise RuntimeError("改写服务挂了")

    orch = _orch(FakeRetriever(passed=True), FakeLLM([GOOD]))
    orch.rewriter = BadRewriter()
    ctx = QaContext(history=[Turn("上一问", "上一答")])
    r = asyncio.run(orch.ask(question="那它呢", ctx=ctx))

    assert r.rewritten_question is None       # 改写失败 → 用原问题
    assert r.answer_status == "ok"            # 不阻断主流程


def test_rewrite_applied_when_success():
    class GoodRewriter:
        async def rewrite(self, question, history):
            return "FastAPI 的 CORSMiddleware 在 allow_credentials 时如何配置"

    orch = _orch(FakeRetriever(passed=True), FakeLLM([GOOD]))
    orch.rewriter = GoodRewriter()
    ctx = QaContext(history=[Turn("怎么配 CORS", "用 CORSMiddleware")])
    r = asyncio.run(orch.ask(question="那凭据呢", ctx=ctx))

    assert r.rewritten_question is not None
    assert "allow_credentials" in r.rewritten_question


def test_fallback_message_is_fixed_template():
    orch = _orch(FakeRetriever(passed=False, max_score=0.0), FakeLLM([GOOD]))
    r = asyncio.run(orch.ask(question="q"))
    assert "未在当前知识库中找到足够依据" in r.answer
    assert "你可以尝试" in r.answer
