"""解析层的数据结构（见 03_核心机制/01）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

BlockKind = Literal["heading", "paragraph", "table", "code", "list", "quote"]


@dataclass(slots=True)
class Block:
    kind: BlockKind
    text: str
    char_start: int
    char_end: int
    level: int | None = None
    page_no: int | None = None
    para_index: int = 0
    meta: dict = field(default_factory=dict)


@dataclass(slots=True)
class PageSpan:
    page_no: int
    char_start: int
    char_end: int


@dataclass(slots=True)
class ParsedDocument:
    blocks: list[Block]
    plain_text: str
    page_map: list[PageSpan] = field(default_factory=list)
    doc_meta: dict = field(default_factory=dict)

    @property
    def char_count(self) -> int:
        return len(self.plain_text)

    @property
    def page_count(self) -> int | None:
        return len(self.page_map) if self.page_map else None


class ParseError(Exception):
    """解析失败（E-2002）。"""


class EmptyDocumentError(ParseError):
    """提取内容为空（E-2003）。"""


class UnsupportedFormatError(Exception):
    """不支持的扩展名（E-1002）。"""
