"""兜底结果结构。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from kbqa.core.retrieval.types import Candidate

FallbackReason = Literal["insufficient_evidence", "llm_unavailable", "validation_failed"]


@dataclass(slots=True)
class FallbackResult:
    reason: FallbackReason
    answer: str
    suggestions: list[str] = field(default_factory=list)
    nearest: list[Candidate] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    llm_called: bool = False
    retryable: bool = False
    keep_question: bool = False
    error_code: str = ""

    @property
    def is_fallback(self) -> bool:
        return True
