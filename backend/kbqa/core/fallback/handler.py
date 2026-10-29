"""兜底处理器：把失败转成结构化、可展示、可统计的结果。"""

from __future__ import annotations

from kbqa.core.fallback.messages import MESSAGES
from kbqa.core.fallback.types import FallbackResult
from kbqa.core.retrieval.types import Candidate
from kbqa.core.validation.types import ValidationIssue


def _compose(reason: str) -> tuple[str, list[str]]:
    msg, tips = MESSAGES[reason]
    body = msg + "\n\n你可以尝试：\n" + "\n".join(f"{i}. {t}" for i, t in enumerate(tips, 1))
    return body, tips


class FallbackHandler:
    def insufficient_evidence(self, candidates: list[Candidate], max_score: float,
                              tau: float) -> FallbackResult:
        body, tips = _compose("insufficient_evidence")
        # 只有"差得不太远"才展示近似片段，否则反而误导
        nearest: list[Candidate] = []
        if candidates and max_score >= tau * 0.5:
            nearest = candidates[:3]
        return FallbackResult(
            reason="insufficient_evidence",
            answer=body,
            suggestions=tips,
            nearest=nearest,
            llm_called=False,
            error_code="E-3001",
        )

    def llm_unavailable(self, error_code: str = "E-3002") -> FallbackResult:
        body, tips = _compose("llm_unavailable")
        return FallbackResult(
            reason="llm_unavailable",
            answer=body,
            suggestions=tips,
            llm_called=True,
            retryable=True,
            keep_question=True,
            error_code=error_code,
        )

    def validation_failed(self, issues: list[ValidationIssue]) -> FallbackResult:
        body, tips = _compose("validation_failed")
        return FallbackResult(
            reason="validation_failed",
            answer=body,
            suggestions=tips,
            issues=[str(i) for i in issues],
            llm_called=True,
            error_code="E-3004",
        )
