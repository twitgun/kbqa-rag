"""生成器：调用 LLM → 校验 → 失败带纠错重试一次。"""

from __future__ import annotations

import time
from typing import Protocol

from kbqa.core.generation.prompt_builder import PromptBuilder
from kbqa.core.generation.types import GenerationOutcome, LLMUnavailable, RawCompletion, Turn
from kbqa.core.retrieval.types import Candidate
from kbqa.core.validation.validator import Validator


class LLMClient(Protocol):
    async def complete(self, messages: list[dict], *, temperature: float = 0.1,
                       max_tokens: int = 1024, timeout: int = 45,
                       json_mode: bool = True) -> RawCompletion: ...


class Generator:
    def __init__(self, llm: LLMClient, builder: PromptBuilder, validator: Validator, *,
                 temperature: float = 0.1, max_tokens: int = 1024,
                 timeout: int = 45, max_retry: int = 1) -> None:
        self.llm = llm
        self.builder = builder
        self.validator = validator
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.max_retry = max_retry

    async def generate(self, *, query: str, candidates: list[Candidate],
                       history: list[Turn] | None = None,
                       summary: str | None = None,
                       strict: bool = True, plain: bool = False) -> GenerationOutcome:
        t0 = time.perf_counter()
        messages = self.builder.build(query=query, candidates=candidates, plain=plain,
                                      history=history, summary=summary)

        try:
            raw = await self.llm.complete(messages, temperature=self.temperature,
                                          max_tokens=self.max_tokens,
                                          timeout=self.timeout, json_mode=True)
        except LLMUnavailable as exc:
            return GenerationOutcome(ok=False, llm_error=exc.code,
                                     latency_ms=int((time.perf_counter() - t0) * 1000))

        result = self.validator.validate(raw.text, candidates, strict=strict)
        if result.valid:
            return GenerationOutcome(
                ok=True, answer=result.answer, retry_count=0,
                tokens={"prompt": raw.prompt_tokens, "completion": raw.completion_tokens},
                latency_ms=int((time.perf_counter() - t0) * 1000))

        if self.max_retry < 1:
            return GenerationOutcome(ok=False, issues=result.issues, retry_count=0,
                                     raw_excerpt=result.raw_excerpt,
                                     latency_ms=int((time.perf_counter() - t0) * 1000))

        retry_messages = self.builder.build_retry(query=query, candidates=candidates, plain=plain, issues=result.issues)
        try:
            raw2 = await self.llm.complete(retry_messages, temperature=0.0,
                                           max_tokens=self.max_tokens,
                                           timeout=self.timeout, json_mode=True)
        except LLMUnavailable as exc:
            return GenerationOutcome(ok=False, issues=result.issues, retry_count=1,
                                     raw_excerpt=result.raw_excerpt, llm_error=exc.code,
                                     latency_ms=int((time.perf_counter() - t0) * 1000))

        result2 = self.validator.validate(raw2.text, candidates, strict=strict)
        latency = int((time.perf_counter() - t0) * 1000)
        if result2.valid:
            return GenerationOutcome(ok=True, answer=result2.answer, retry_count=1,
                                     tokens={"prompt": raw2.prompt_tokens,
                                             "completion": raw2.completion_tokens},
                                     latency_ms=latency)

        return GenerationOutcome(ok=False, issues=result2.issues, retry_count=1,
                                 raw_excerpt=result2.raw_excerpt, latency_ms=latency)
