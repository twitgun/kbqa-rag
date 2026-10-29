"""切分器注册。"""

from __future__ import annotations

from kbqa.core.chunking.base import Chunk, Chunker, ChunkingError, ChunkParams
from kbqa.core.chunking.fixed import FixedWindowChunker
from kbqa.core.chunking.structure import StructureChunker

CHUNKERS: dict[str, Chunker] = {
    "structure": StructureChunker(),
    "fixed": FixedWindowChunker(),
}


def get_chunker(strategy: str) -> Chunker:
    if strategy not in CHUNKERS:
        raise ValueError(f"未知切分策略：{strategy}")
    return CHUNKERS[strategy]


__all__ = ["Chunk", "ChunkParams", "ChunkingError", "CHUNKERS", "get_chunker"]
