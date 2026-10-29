"""追问改写：失败语义与跑题保护。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from kbqa.core.generation import LLMUnavailable, PromptBuilder, RawCompletion, Turn
from kbqa.services.rewrite_service import LlmRewriter

PROMPT_DIR = Path(__file__).resolve().parents[1] / "kbqa" / "prompts"


class FakeLLM:
    def __init__(self, text=None, error=None):
        self.text = text
        self.error = error

    async def complete(self, messages, **kw):
        if self.error:
            raise LLMUnavailable("E-3002", "boom")
        return RawCompletion(text=self.text or "")


def _rw(llm) -> LlmRewriter:
    return LlmRewriter(llm, PromptBuilder(PROMPT_DIR))


HISTORY = [Turn("怎么配置 CORS", "用 CORSMiddleware")]


def test_rewrite_success():
    rw = _rw(FakeLLM("FastAPI 的 CORSMiddleware 在 allow_credentials=True 时如何配置 allow_origins"))
    out = asyncio.run(rw.rewrite("那凭据呢", HISTORY))
    assert "allow_credentials" in out


def test_rewrite_no_history_returns_empty():
    assert asyncio.run(_rw(FakeLLM("x")).rewrite("问题", [])) == ""


def test_rewrite_llm_failure_returns_empty():
    """失败必须返回空串，否则前端会把原句误显示成"已改写"。"""
    assert asyncio.run(_rw(FakeLLM(error=True)).rewrite("那它呢", HISTORY)) == ""


def test_rewrite_off_topic_rejected():
    rw = _rw(FakeLLM("今天北京天气怎么样"))
    assert asyncio.run(rw.rewrite("那凭据呢", HISTORY)) == ""


def test_rewrite_strips_prefix():
    rw = _rw(FakeLLM("改写结果：CORS 的 allow_credentials 怎么配"))
    out = asyncio.run(rw.rewrite("那凭据呢", HISTORY))
    assert out.startswith("CORS") and not out.startswith("改写结果")
