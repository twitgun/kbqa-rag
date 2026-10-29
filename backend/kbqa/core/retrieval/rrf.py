"""RRF 倒数排名融合（见 ADR-008）。

只使用排名、不使用分数，因此对两路分数量纲差异免疫。
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence


def rrf_fuse(vector_ids: Sequence[str], bm25_ids: Sequence[str],
             k: int = 60) -> list[tuple[str, float]]:
    """返回按分数降序的 (chunk_uid, score)，同分按 uid 字典序，保证可复现。"""
    if k < 0:
        raise ValueError("k 不能为负")

    scores: dict[str, float] = defaultdict(float)
    for rank, uid in enumerate(vector_ids, start=1):
        scores[uid] += 1.0 / (k + rank)
    for rank, uid in enumerate(bm25_ids, start=1):
        scores[uid] += 1.0 / (k + rank)

    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
