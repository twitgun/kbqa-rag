"""切分参数与片段结构（见 03_核心机制/01、04_函数级详细设计/03）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol


@dataclass(slots=True)
class ChunkParams:
    strategy: Literal["structure", "fixed"] = "structure"
    target_size: int = 800
    max_size: int = 1500
    min_size: int = 120
    overlap: int = 120
    preserve_table: bool = True

    def validate(self) -> None:
        if self.overlap >= self.target_size / 2:
            raise ValueError("overlap 必须小于 target_size 的一半")
        if not (self.min_size < self.target_size < self.max_size):
            raise ValueError("需满足 min_size < target_size < max_size")
        if self.overlap < 0:
            raise ValueError("overlap 不能为负")


@dataclass(slots=True)
class Chunk:
    text: str
    char_start: int
    char_end: int
    chunk_index: int = 0
    section_path: str = "正文"
    page_no: int | None = None
    para_start: int | None = None
    para_end: int | None = None
    token_count: int = 0
    strategy: str = "structure"
    meta: dict = field(default_factory=dict)

    @property
    def char_len(self) -> int:
        """原文跨度（不含【path】前缀）。"""
        return self.char_end - self.char_start


class Chunker(Protocol):
    def chunk(self, doc, params: ChunkParams) -> list[Chunk]: ...


class ChunkingError(Exception):
    """切分后无片段。"""
