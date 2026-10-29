"""校验层数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, Field


class CitationItem(BaseModel):
    chunk_id: str
    quote: str


class RawAnswer(BaseModel):
    """四个字段均为必填——缺字段属于 V-02 失败，不允许用默认值兜过去。"""

    answer: str = Field(min_length=1, max_length=4000)
    citations: list[CitationItem] = Field(default_factory=list)
    insufficient: bool
    confidence: float = Field(ge=0.0, le=1.0)


@dataclass(slots=True)
class ValidationIssue:
    rule: str
    detail: str

    def __str__(self) -> str:
        return f"{self.rule}:{self.detail}"


@dataclass(slots=True)
class ValidationResult:
    valid: bool
    answer: RawAnswer | None = None
    issues: list[ValidationIssue] = field(default_factory=list)
    raw_excerpt: str = ""

    @property
    def summary(self) -> str:
        return "; ".join(str(i) for i in self.issues)


class ParseError(Exception):
    """V-01：无法从文本中提取 JSON。"""
