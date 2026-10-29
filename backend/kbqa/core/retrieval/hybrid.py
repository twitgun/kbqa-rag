"""混合检索：向量 + BM25 → RRF → 阈值判定（见 03_核心机制/02）。

没有重排模型时，用"最高余弦相似度"作为 max_score（量纲与 rerank 的 sigmoid 不同，
阈值需用 retrieval.tau 的语义另行标定；接上 reranker 后自动切换）。
"""

from __future__ import annotations

import asyncio
import time
from typing import Callable

from kbqa.core.retrieval.rrf import rrf_fuse
from kbqa.core.retrieval.types import Candidate, RetrievalResult


class HybridRetriever:
    def __init__(self, *, embedder, vector_store, bm25,
                 load_chunks: Callable[[list[str]], dict[str, dict]],
                 mode: str = "hybrid", tau: float = 0.30,
                 tau_rerank: float = 0.30, tau_cosine: float = 0.55,
                 top_k_vector: int = 30, top_k_bm25: int = 30,
                 top_n_fusion: int = 20, top_k_final: int = 5,
                 rrf_k: int = 60, reranker=None,
                 config_loader: Callable[[], dict] | None = None) -> None:
        self.embedder = embedder
        self.vector_store = vector_store
        self.bm25 = bm25
        self.load_chunks = load_chunks
        self.mode = mode
        # 两个量纲对应两个阈值：重排 sigmoid 用 tau_rerank，双塔余弦用 tau_cosine
        self.tau = tau if tau is not None else tau_rerank
        self.tau_rerank = tau_rerank
        self.tau_cosine = tau_cosine
        self.top_k_vector = top_k_vector
        self.top_k_bm25 = top_k_bm25
        self.top_n_fusion = top_n_fusion
        self.top_k_final = top_k_final
        self.rrf_k = rrf_k
        self.reranker = reranker
        self.config_loader = config_loader

    def _cfg(self) -> dict:
        """每次检索读一次运行时配置；页面改参数后无需重启。"""
        if self.config_loader is None:
            return {}
        try:
            return self.config_loader()
        except Exception:  # noqa: BLE001
            return {}

    async def retrieve(self, query: str, *, enable_rerank: bool = True,
                       debug: bool = False) -> RetrievalResult:
        t0 = time.perf_counter()
        query = query[:1000].strip()
        if not query:
            return RetrievalResult(passed=False)

        vector_hits: list[tuple[str, float, dict]] = []
        bm25_hits: list[tuple[str, float]] = []

        cfg = self._cfg()
        mode = str(cfg.get("retrieval.mode", self.mode))
        k_vector = int(cfg.get("retrieval.top_k_vector", self.top_k_vector))
        k_bm25 = int(cfg.get("retrieval.top_k_bm25", self.top_k_bm25))
        n_fusion = int(cfg.get("retrieval.top_n_fusion", self.top_n_fusion))
        rrf_k = int(cfg.get("retrieval.rrf_k", self.rrf_k))

        if mode in ("hybrid", "vector_only"):
            qvec = self.embedder.encode_query(query)
            vector_hits = await asyncio.to_thread(
                self.vector_store.query, qvec, k_vector, None)
        t1 = time.perf_counter()

        if mode in ("hybrid", "bm25_only"):
            bm25_hits = await asyncio.to_thread(self.bm25.search, query, k_bm25)
        t2 = time.perf_counter()

        if mode == "vector_only":
            fused = [(uid, score) for uid, score, _ in vector_hits]
        elif mode == "bm25_only":
            fused = list(bm25_hits)
        else:
            fused = rrf_fuse([u for u, _, _ in vector_hits],
                             [u for u, _ in bm25_hits], k=rrf_k)
        top = fused[:n_fusion]
        t3 = time.perf_counter()

        v_map = {u: (s, i) for i, (u, s, _) in enumerate(vector_hits, 1)}
        b_map = {u: (s, i) for i, (u, s) in enumerate(bm25_hits, 1)}
        metas = await asyncio.to_thread(self.load_chunks, [u for u, _ in top])

        candidates: list[Candidate] = []
        for uid, score in top:
            meta = metas.get(uid)
            if meta is None:
                continue
            v = v_map.get(uid, (None, None))
            b = b_map.get(uid, (None, None))
            candidates.append(Candidate(
                chunk_uid=uid, doc_id=meta["doc_id"], text=meta["text"],
                doc_title=meta.get("doc_title", ""), page_no=meta.get("page_no"),
                section_path=meta.get("section_path", ""),
                char_start=meta.get("char_start", 0), char_end=meta.get("char_end", 0),
                vector_score=v[0], vector_rank=v[1],
                bm25_score=b[0], bm25_rank=b[1], rrf_score=score,
            ))

        degraded = True
        k_final = int(cfg.get("retrieval.top_k_rerank", self.top_k_final))
        rerank_on = enable_rerank and bool(cfg.get("retrieval.rerank_enabled", True))
        if rerank_on and self.reranker is not None and candidates:
            try:
                ranked = await asyncio.to_thread(
                    self.reranker.rerank, query, [c.text for c in candidates], k_final)
                scored = [(candidates[i], s) for i, s in ranked]
                degraded = False
            except Exception:  # noqa: BLE001
                scored = self._fallback_rank(candidates)
        else:
            scored = self._fallback_rank(candidates)

        # 无重排时用最高余弦相似度做阈值判定；有重排则用重排分
        if self.reranker is not None and not degraded:
            max_score = max(s for _, s in scored) if scored else 0.0
            effective_tau = float(cfg.get("retrieval.tau", self.tau_rerank))
        else:
            max_score = max((c.vector_score or 0.0) for c, _ in scored) if scored else 0.0
            effective_tau = float(cfg.get("retrieval.tau_cosine", self.tau_cosine))

        t4 = time.perf_counter()
        return RetrievalResult(
            candidates=[c for c, _ in scored[:k_final]],
            all_fused=candidates if debug else [],
            max_score=float(max_score),
            passed=float(max_score) >= effective_tau,
            tau=float(effective_tau),
            degraded=degraded,
            timing={"vector_ms": int((t1 - t0) * 1000), "bm25_ms": int((t2 - t1) * 1000),
                    "fusion_ms": int((t3 - t2) * 1000), "rerank_ms": int((t4 - t3) * 1000)},
        )

    def _fallback_rank(self, candidates: list[Candidate]) -> list[tuple[Candidate, float]]:
        """无重排：按 RRF 分数归一化排序，同时保留 max_score 用余弦分。"""
        if not candidates:
            return []
        scores = [c.rrf_score for c in candidates]
        lo, hi = min(scores), max(scores)
        span = (hi - lo) or 1.0
        ranked = [(c, (c.rrf_score - lo) / span) for c in candidates]
        ranked.sort(key=lambda x: -x[1])
        return ranked
