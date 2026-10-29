"""提示词组装、生成器重试、DeepSeek 客户端（用 MockTransport，不发真实请求）。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from kbqa.core.generation import Generator, LLMUnavailable, PromptBuilder, RawCompletion, Turn
from kbqa.core.generation.prompt_builder import extract_keywords, truncate
from kbqa.core.retrieval.types import Candidate
from kbqa.core.validation import Validator
from kbqa.infra.llm.deepseek import DeepSeekClient

PROMPT_DIR = Path(__file__).resolve().parents[1] / "kbqa" / "prompts"

CAND = [
    Candidate(chunk_uid="d1_c00001", doc_id=1, text="allow_origins 不能设置为 [\"*\"]，当 allow_credentials 为 True 时。",
              doc_title="CORS - FastAPI", section_path="教程 > CORS > 凭据", char_start=0, char_end=40),
    Candidate(chunk_uid="d1_c00002", doc_id=1, text="CORSMiddleware 用于配置跨域。",
              doc_title="CORS - FastAPI", section_path="教程 > CORS", char_start=41, char_end=60),
]


def _builder(**kw) -> PromptBuilder:
    return PromptBuilder(PROMPT_DIR, **kw)


# ---------------------------------------------------------------- PromptBuilder
def test_builder_injects_chunk_ids():
    msgs = _builder().build(query="怎么配置 CORS", candidates=CAND)
    user = msgs[-1]["content"]
    assert "chunk_id=d1_c00001" in user
    assert "[1]" in user and "[2]" in user
    assert "怎么配置 CORS" in user
    assert msgs[0]["role"] == "system"


def test_builder_skips_fallback_turns():
    history = [Turn("上一问", "兜底话术", is_fallback=True), Turn("正常问", "正常答")]
    msgs = _builder().build(query="追问", candidates=CAND, history=history)
    joined = "".join(m["content"] for m in msgs)
    assert "上一问" not in joined
    assert "正常问" in joined


def test_builder_shrinks_to_budget():
    # 10 个片段 × 600 字，远超 4000 token 预算；应裁掉低分片段但仍保留至少 1 个
    many = [Candidate(chunk_uid=f"d1_c{i:05d}", doc_id=1, text="内容" * 300) for i in range(10)]
    b = _builder(max_context_tokens=4000)
    msgs = b.build(query="q", candidates=many)

    kept = msgs[-1]["content"].count("chunk_id=")
    assert 1 <= kept < 10, f"应被裁剪，实际保留 {kept}"
    assert b.estimate_tokens(msgs) <= 4000


def test_builder_keeps_all_when_within_budget():
    many = [Candidate(chunk_uid=f"d1_c{i:05d}", doc_id=1, text="短内容") for i in range(3)]
    msgs = _builder(max_context_tokens=6000).build(query="q", candidates=many)
    assert msgs[-1]["content"].count("chunk_id=") == 3


def test_truncate_and_keywords():
    assert truncate("abcdef", 3) == "abc……"
    kws = extract_keywords("allow_credentials 怎么配")
    assert "allow_credentials" in kws


# ---------------------------------------------------------------- Generator
class FakeLLM:
    def __init__(self, texts):
        self._texts = list(texts)
        self.calls = 0

    async def complete(self, messages, **kw) -> RawCompletion:
        self.calls += 1
        return RawCompletion(text=self._texts.pop(0), prompt_tokens=10, completion_tokens=5)


GOOD = json.dumps({"answer": "不能设为 *，必须显式列出 [1]",
                   "citations": [{"chunk_id": "d1_c00001", "quote": "allow_origins 不能设置为"}],
                   "insufficient": False, "confidence": 0.9}, ensure_ascii=False)
BAD = "这不是 JSON"


def _gen(texts, **kw) -> Generator:
    return Generator(FakeLLM(texts), _builder(), Validator(), **kw)


def test_generator_success_first_try():
    out = asyncio.run(_gen([GOOD]).generate(query="q", candidates=CAND))
    assert out.ok and out.retry_count == 0 and out.answer is not None


def test_generator_retries_once_and_succeeds():
    out = asyncio.run(_gen([BAD, GOOD]).generate(query="q", candidates=CAND))
    assert out.ok and out.retry_count == 1


def test_generator_fails_after_retry():
    out = asyncio.run(_gen([BAD, BAD]).generate(query="q", candidates=CAND))
    assert not out.ok and out.retry_count == 1 and out.issues


def test_generator_no_retry_when_disabled():
    out = asyncio.run(_gen([BAD], max_retry=0).generate(query="q", candidates=CAND))
    assert not out.ok and out.retry_count == 0


class RaisingLLM:
    async def complete(self, *a, **kw):
        raise LLMUnavailable("E-3002", "timeout")


def test_generator_llm_error():
    out = asyncio.run(Generator(RaisingLLM(), _builder(), Validator())
                      .generate(query="q", candidates=CAND))
    assert not out.ok and out.llm_error == "E-3002"


# ---------------------------------------------------------------- DeepSeek client
def _client(handler, **kw) -> DeepSeekClient:
    return DeepSeekClient(api_key="sk-test", base_url="https://api.test",
                          transport=httpx.MockTransport(handler), backoff=0.0, **kw)


def _ok_body(text: str) -> dict:
    return {"model": "deepseek-chat",
            "choices": [{"message": {"content": text}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 7}}


def test_client_success():
    async def run():
        c = _client(lambda req: httpx.Response(200, json=_ok_body("hello")))
        try:
            return await c.complete([{"role": "user", "content": "hi"}])
        finally:
            await c.aclose()

    r = asyncio.run(run())
    assert r.text == "hello" and r.prompt_tokens == 12


def test_client_retries_429_then_ok():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, text="rate limited")
        return httpx.Response(200, json=_ok_body("ok"))

    async def run():
        c = _client(handler)
        try:
            return await c.complete([{"role": "user", "content": "hi"}])
        finally:
            await c.aclose()

    assert asyncio.run(run()).text == "ok"
    assert calls["n"] == 2


def test_client_timeout_raises():
    def handler(req):
        raise httpx.TimeoutException("boom", request=req)

    async def run():
        c = _client(handler)
        try:
            return await c.complete([{"role": "user", "content": "hi"}])
        finally:
            await c.aclose()

    with pytest.raises(LLMUnavailable) as ei:
        asyncio.run(run())
    assert ei.value.code == "E-3002"


def test_client_401_no_retry():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(401, text="bad key")

    async def run():
        c = _client(handler)
        try:
            return await c.complete([{"role": "user", "content": "hi"}])
        finally:
            await c.aclose()

    with pytest.raises(LLMUnavailable) as ei:
        asyncio.run(run())
    assert ei.value.code == "E-3003" and calls["n"] == 1


def test_client_empty_key_does_not_send_illegal_header():
    """没配 key 时必须直接抛 LLMUnavailable，而不是构造出 'Bearer ' 非法头。"""
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(200, json=_ok_body("should not reach"))

    async def run():
        c = DeepSeekClient(api_key="", base_url="https://api.test",
                           transport=httpx.MockTransport(handler))
        try:
            return await c.complete([{"role": "user", "content": "hi"}])
        finally:
            await c.aclose()

    with pytest.raises(LLMUnavailable) as ei:
        asyncio.run(run())
    assert ei.value.code == "E-3003"
    assert "DEEPSEEK_API_KEY" in str(ei.value)
    assert calls["n"] == 0, "没 key 时不应发起网络请求"


def test_retry_prompt_hides_rule_codes():
    """重试提示词只能给「人话」，否则模型会把 V-04 这种代号抄进答案。"""
    from pathlib import Path

    from kbqa.core.generation import PromptBuilder
    from kbqa.core.validation import ValidationIssue

    b = PromptBuilder(Path(__file__).resolve().parents[1] / "kbqa" / "prompts")
    msgs = b.build_retry(query="怎么配置 CORSMiddleware？", candidates=[], issues=[
        ValidationIssue("V-04", "引用标记 [3] 超出 citations 数量 2")])
    body = "\n".join(m["content"] for m in msgs)

    assert "V-04" not in body and "V-0" not in body, "内部规则编号不得进入提示词"
    assert "引用标记 [3]" in body, "纠错信息要保留"
    assert "怎么配置 CORSMiddleware" in body, "重试必须带上原问题，否则模型会答错问题"
    assert "未通过校验" in body