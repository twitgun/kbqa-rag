"""六条校验规则（V-01 ~ V-06），见 03_核心机制/04。"""

from __future__ import annotations

import re

from kbqa.core.retrieval.types import Candidate
from kbqa.core.validation.types import CitationItem, RawAnswer, ValidationIssue

_MARKER = re.compile(r"\[(\d+)\]")
_ASSERTIVE = re.compile(
    r"(根据|依据).{0,12}(资料|文档|内容).{0,40}(是|为|可以|支持|需要|必须|应当|应该|会|能)"
)
_SOFT_STARTS = ("未找到", "没有找到", "无法回答", "建议你", "你可以尝试", "未在")


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text)


def has_factual_claim(text: str) -> bool:
    """粗判是否包含实质事实陈述（用于 V-05 引用必要性）。"""
    if len(text) < 15:
        return False
    return not any(text.lstrip().startswith(s) for s in _SOFT_STARTS)


def has_assertive_conclusion(text: str) -> bool:
    return bool(_ASSERTIVE.search(text))


def check_citations(answer: RawAnswer, candidates: list[Candidate]) -> list[ValidationIssue]:
    """V-03 引用合法 + V-05 quote 真实性。"""
    issues: list[ValidationIssue] = []
    by_id = {c.chunk_uid: c for c in candidates}
    for i, cit in enumerate(answer.citations):
        chunk = by_id.get(cit.chunk_id)
        if chunk is None:
            issues.append(ValidationIssue("V-03", f"citations[{i}].chunk_id={cit.chunk_id} 不在本轮召回集"))
            continue
        probe = _norm(cit.quote)[:30]
        if probe and probe not in _norm(chunk.text):
            issues.append(ValidationIssue("V-05", f"citations[{i}].quote 非原文摘录"))
    return issues


def check_markers(answer: RawAnswer) -> list[ValidationIssue]:
    """V-04 答案中的 [n] 不得超过 citations 数量。"""
    markers = {int(m) for m in _MARKER.findall(answer.answer)}
    if not markers:
        return []
    n = len(answer.citations)
    bad = sorted(m for m in markers if m < 1 or m > n)
    if bad:
        return [ValidationIssue("V-04", f"引用标记 {bad} 超出 citations 数量 {n}")]
    return []


def check_necessity(answer: RawAnswer) -> list[ValidationIssue]:
    """V-05 不充分为 false 且含事实陈述时，必须有引用。"""
    if not answer.insufficient and not answer.citations and has_factual_claim(answer.answer):
        return [ValidationIssue("V-05", "答案含事实陈述但未提供引用")]
    return []


def check_consistency(answer: RawAnswer) -> list[ValidationIssue]:
    """V-06 insufficient=true 时不应给确定性结论。"""
    if answer.insufficient and has_assertive_conclusion(answer.answer):
        return [ValidationIssue("V-06", "insufficient=true 但答案含确定性结论")]
    return []


def check_all(answer: RawAnswer, candidates: list[Candidate],
              verify_quote: bool = True) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    issues += check_citations(answer, candidates) if verify_quote else _only_ids(answer, candidates)
    issues += check_markers(answer)
    issues += check_necessity(answer)
    issues += check_consistency(answer)
    return issues


def _only_ids(answer: RawAnswer, candidates: list[Candidate]) -> list[ValidationIssue]:
    valid = {c.chunk_uid for c in candidates}
    out = []
    for i, cit in enumerate(answer.citations):
        if cit.chunk_id not in valid:
            out.append(ValidationIssue("V-03", f"citations[{i}].chunk_id={cit.chunk_id} 不在本轮召回集"))
    return out


__all__ = [
    "check_all", "check_citations", "check_markers", "check_necessity",
    "check_consistency", "has_factual_claim", "has_assertive_conclusion",
    "CitationItem", "RawAnswer", "ValidationIssue",
]
