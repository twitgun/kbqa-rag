"""生成层数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class Turn:
    question: str
    answer: str
    is_fallback: bool = False


@dataclass(slots=True)
class RawCompletion:
    text: str
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0


@dataclass(slots=True)
class GenerationOutcome:
    ok: bool
    answer: object | None = None          # RawAnswer
    issues: list = field(default_factory=list)
    retry_count: int = 0
    raw_excerpt: str = ""
    tokens: dict = field(default_factory=dict)
    latency_ms: int = 0
    llm_error: str | None = None


class LLMUnavailable(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
