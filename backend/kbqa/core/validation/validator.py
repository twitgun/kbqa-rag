"""校验编排：V-01 提取 → V-02 Schema → V-03~06 语义规则。"""

from __future__ import annotations

from pydantic import ValidationError

from kbqa.core.retrieval.types import Candidate
from kbqa.core.validation.extractor import extract_json
from kbqa.core.validation.normalize import normalize
from kbqa.core.validation.rules import check_all
from kbqa.core.validation.types import ParseError, RawAnswer, ValidationIssue, ValidationResult


class Validator:
    def __init__(self, verify_quote: bool = True) -> None:
        self.verify_quote = verify_quote

    def validate(self, raw_text: str, candidates: list[Candidate],
                 strict: bool = True) -> ValidationResult:
        """strict=False 时只做 V-01/V-02（结构），跳过引用类规则。

        用于 L1/L2 对照组：它们本就拿不到合法候选，若强制引用校验，
        任何答案都会被判非法，对照组将退化为"永远兜底"。
        """
        try:
            data = extract_json(raw_text)
        except ParseError as exc:
            return ValidationResult(False, None, [ValidationIssue("V-01", str(exc))],
                                    raw_text[:500])

        try:
            answer = RawAnswer.model_validate(data)
        except ValidationError as exc:
            first = exc.errors()[0] if exc.errors() else {"msg": "schema 不匹配"}
            return ValidationResult(False, None, [ValidationIssue("V-02", str(first.get("msg")))],
                                    raw_text[:500])

        if not strict:
            return ValidationResult(valid=True, answer=answer, raw_excerpt=raw_text[:500])

        # 先归一化引用编号：模型按「参考资料编号」写标记，citations 只列用到的条目
        answer, norm_issues = normalize(answer, candidates)
        if norm_issues:
            return ValidationResult(valid=False, answer=None, issues=norm_issues,
                                    raw_excerpt=raw_text[:500])

        issues = check_all(answer, candidates, self.verify_quote)
        return ValidationResult(valid=not issues, answer=answer if not issues else None,
                                issues=issues, raw_excerpt=raw_text[:500])
