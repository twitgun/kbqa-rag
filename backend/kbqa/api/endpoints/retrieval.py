"""检索测试接口（API-11）：不调用 LLM，只暴露召回与分数，便于调试。"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from kbqa.api.deps import get_retriever
from kbqa.api.response import ok
from kbqa.core.retrieval.hybrid import HybridRetriever

router = APIRouter(prefix="/retrieval", tags=["retrieval"])


@router.post("/search")
async def search(body: dict, retriever: HybridRetriever = Depends(get_retriever)) -> dict:
    query = (body.get("query") or "").strip()
    if not query:
        from kbqa.api.exception_handlers import ApiError, ErrorCode
        raise ApiError(ErrorCode.INVALID_PARAM, "query 不能为空")

    top_k = int(body.get("top_k", 10))
    enable_rerank = bool(body.get("enable_rerank", True))

    result = await retriever.retrieve(query, enable_rerank=enable_rerank, debug=True)

    items = []
    for rank, c in enumerate(result.all_fused[:max(top_k, 10)], 1):
        items.append({
            "rank": rank, "chunk_uid": c.chunk_uid, "doc_id": c.doc_id,
            "doc_title": c.doc_title, "section_path": c.section_path,
            "text": c.text[:400], "page_no": c.page_no,
            "vector_score": round(c.vector_score, 4) if c.vector_score is not None else None,
            "vector_rank": c.vector_rank,
            "bm25_score": round(c.bm25_score, 2) if c.bm25_score is not None else None,
            "bm25_rank": c.bm25_rank,
            "rrf_score": round(c.rrf_score, 5),
        })

    return ok({
        "query": query,
        "mode": retriever.mode,
        "candidates": items,
        "debug": {
            "max_score": round(result.max_score, 4),
            "tau": round(result.tau, 4),
            "passed": result.passed,
            "rerank_degraded": result.degraded,
            "elapsed_ms": sum(result.timing.values()),
            "timing": result.timing,
        },
    })
