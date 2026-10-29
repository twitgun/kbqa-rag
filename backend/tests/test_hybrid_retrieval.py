"""HybridRetriever：融合、阈值、通道切换。用假依赖，不需要模型与数据库。"""

from __future__ import annotations

import asyncio

import numpy as np

from kbqa.core.retrieval.hybrid import HybridRetriever

META = {
    "a": {"doc_id": 1, "doc_title": "CORS", "text": "跨域配置", "section_path": "CORS > 中间件"},
    "b": {"doc_id": 1, "doc_title": "CORS", "text": "同源策略", "section_path": "CORS > 源"},
    "c": {"doc_id": 2, "doc_title": "依赖", "text": "Depends 用法", "section_path": "依赖 > 基础"},
}


class FakeEmbedder:
    dim = 4

    def encode_query(self, text):
        return np.ones(4, dtype=np.float32)

    def encode_documents(self, texts):
        return np.stack([np.ones(4, dtype=np.float32) for _ in texts])


class FakeStore:
    def __init__(self, hits):
        self.hits = hits

    def query(self, vec, top_k, where=None):
        return self.hits[:top_k]


class FakeBm25:
    def __init__(self, hits):
        self.hits = hits

    def search(self, query, top_k=30):
        return self.hits[:top_k]


def _retriever(store_hits, bm25_hits, *, tau=0.30, mode="hybrid", reranker=None):
    return HybridRetriever(
        embedder=FakeEmbedder(), vector_store=FakeStore(store_hits),
        bm25=FakeBm25(bm25_hits), load_chunks=lambda uids: {u: META[u] for u in uids if u in META},
        mode=mode, tau=tau, reranker=reranker,
    )


def test_hybrid_fuses_and_orders():
    r = _retriever([("a", 0.9, {}), ("b", 0.5, {})], [("b", 8.0), ("c", 3.0)])
    res = asyncio.run(r.retrieve("跨域", enable_rerank=False))

    uids = [c.chunk_uid for c in res.candidates]
    assert "b" in uids                     # 两路都命中的 b 应当靠前
    assert res.candidates[0].chunk_uid == "b"
    assert res.degraded is True            # 没有 reranker → 降级


def test_tau_blocks_when_low_similarity():
    r = _retriever([("a", 0.10, {})], [("a", 1.0)], tau=0.30)
    res = asyncio.run(r.retrieve("无关问题", enable_rerank=False))
    assert res.passed is False
    assert res.max_score == 0.10


def test_tau_passes_when_high_similarity():
    r = _retriever([("a", 0.82, {})], [("a", 9.0)], tau=0.30)
    res = asyncio.run(r.retrieve("CORS", enable_rerank=False))
    assert res.passed is True and res.max_score == 0.82


def test_bm25_only_mode_skips_vector():
    class ExplodingStore:
        def query(self, *a, **kw):
            raise AssertionError("bm25_only 不应访问向量库")

    r = HybridRetriever(embedder=FakeEmbedder(), vector_store=ExplodingStore(),
                        bm25=FakeBm25([("c", 5.0)]),
                        load_chunks=lambda uids: {u: META[u] for u in uids},
                        mode="bm25_only", tau=0.0)
    res = asyncio.run(r.retrieve("Depends", enable_rerank=False))
    assert [c.chunk_uid for c in res.candidates] == ["c"]


def test_missing_chunk_meta_is_skipped():
    r = _retriever([("zzz", 0.9, {}), ("a", 0.8, {})], [])
    res = asyncio.run(r.retrieve("q", enable_rerank=False))
    assert [c.chunk_uid for c in res.candidates] == ["a"]


def test_empty_query_returns_not_passed():
    r = _retriever([], [])
    res = asyncio.run(r.retrieve("   ", enable_rerank=False))
    assert res.passed is False and res.candidates == []
