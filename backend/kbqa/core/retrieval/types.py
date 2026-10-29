"""检索层数据结构（见 03_核心机制/02）。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class Candidate:
    chunk_uid: str
    doc_id: int
    text: str
    vector_score: float | None = None
    vector_rank: int | None = None
    bm25_score: float | None = None
    bm25_rank: int | None = None
    rrf_score: float = 0.0
    rerank_score: float | None = None
    # 展示用
    doc_title: str = ""
    page_no: int | None = None
    section_path: str = ""
    char_start: int = 0
    char_end: int = 0

    @property
    def score(self) -> float:
        return self.rerank_score if self.rerank_score is not None else self.rrf_score


@dataclass(slots=True)
class RetrievalResult:
    candidates: list[Candidate] = field(default_factory=list)
    all_fused: list[Candidate] = field(default_factory=list)
    max_score: float = 0.0
    passed: bool = False
    tau: float = 0.0
    degraded: bool = False
    timing: dict[str, int] = field(default_factory=dict)
