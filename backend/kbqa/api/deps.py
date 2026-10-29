"""依赖注入：重型对象进程内单例（模型、向量库、BM25、任务队列）。"""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from kbqa.core.chunking import ChunkParams
from kbqa.core.indexing import IndexService
from kbqa.infra.bm25.index import Bm25Index
from kbqa.infra.db.repositories import ChunkRepo, DocumentRepo
from kbqa.infra.db.session import SessionLocal
from kbqa.config.runtime import load_config
from kbqa.core.generation.answerability import AnswerabilityChecker
from kbqa.core.retrieval.hybrid import HybridRetriever
from kbqa.infra.db import models as m
from kbqa.infra.embedding.base import EmbeddingProvider, HashEmbedding
from kbqa.infra.jobs.runner import JobRunner
from kbqa.infra.storage.file_store import FileStore
from kbqa.infra.vectorstore.memory import MemoryVectorStore
from kbqa.services.ingest_service import IngestService
from kbqa.settings import settings


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@lru_cache
def get_embedder() -> EmbeddingProvider:
    """按 settings.embedding_model 加载本地向量模型；缺失时回退到开发替身。"""
    model_dir = settings.model_dir / settings.embedding_model
    has_weights = model_dir.exists() and (
        any(model_dir.glob("*.safetensors")) or (model_dir / "pytorch_model.bin").exists()
    )
    if has_weights:
        try:
            from kbqa.infra.embedding.bge import BgeEmbedding
            return BgeEmbedding(model_dir, device=settings.embedding_device,
                                batch_size=settings.embedding_batch_size)
        except Exception as exc:  # noqa: BLE001
            import logging
            logging.getLogger("kbqa").warning("bge_load_failed: %s", exc)
    return HashEmbedding(dim=256)


@lru_cache
def get_vector_store() -> MemoryVectorStore:
    store = MemoryVectorStore(settings.data_dir / "vectors.pkl")
    store.load()
    return store


@lru_cache
def get_bm25() -> Bm25Index:
    idx = Bm25Index(settings.bm25_file)
    idx.load()
    return idx


@lru_cache
def get_job_runner() -> JobRunner:
    return JobRunner(max_workers=1)


@lru_cache
def get_index_service() -> IndexService:
    return IndexService(
        embedder=get_embedder(),
        vector_store=get_vector_store(),
        bm25=get_bm25(),
        chunk_repo_factory=ChunkRepo,
        doc_repo_factory=DocumentRepo,
    )


@lru_cache
def get_ingest_service() -> IngestService:
    return IngestService(
        store=FileStore(settings.uploads_dir),
        jobs=get_job_runner(),
        index_service=get_index_service(),
        params=ChunkParams(),
    )


def _load_chunks(uids: list[str]) -> dict[str, dict]:
    """检索命中后补全片段与文档信息。用独立 Session，避免与请求事务纠缠。"""
    if not uids:
        return {}
    with SessionLocal() as db:
        stmt = (select(m.Chunk, m.Document)
                .join(m.Document, m.Document.id == m.Chunk.doc_id)
                .where(m.Chunk.chunk_uid.in_(uids)))
        out: dict[str, dict] = {}
        for chunk, doc in db.execute(stmt).all():
            out[chunk.chunk_uid] = {
                "doc_id": doc.id, "doc_title": doc.title, "text": chunk.text,
                "page_no": chunk.page_no, "section_path": chunk.section_path,
                "char_start": chunk.char_start, "char_end": chunk.char_end,
            }
        return out


@lru_cache
def get_reranker():
    """重排模型缺失时返回 None，检索层自动降级为双塔分数。"""
    if not settings.rerank_enabled:
        return None
    model_dir = settings.model_dir / settings.reranker_model
    if not (model_dir.exists() and (
            any(model_dir.glob("*.safetensors")) or (model_dir / "pytorch_model.bin").exists())):
        return None
    try:
        from kbqa.infra.reranker.bge import BgeReranker
        return BgeReranker(model_dir, device=settings.embedding_device,
                           batch_size=settings.rerank_batch_size)
    except Exception as exc:  # noqa: BLE001
        import logging
        logging.getLogger("kbqa").warning("reranker_load_failed: %s", exc)
        return None


@lru_cache
def get_retriever() -> HybridRetriever:
    return HybridRetriever(
        embedder=get_embedder(),
        vector_store=get_vector_store(),
        bm25=get_bm25(),
        load_chunks=_load_chunks,
        mode="hybrid",
        tau_rerank=0.70, tau_cosine=0.50,
        top_k_vector=30, top_k_bm25=30, top_n_fusion=20, top_k_final=5,
        reranker=get_reranker(),
        config_loader=load_config,
    )


@lru_cache
def get_llm():
    from kbqa.infra.llm.deepseek import DeepSeekClient
    return DeepSeekClient(api_key=settings.deepseek_api_key,
                          base_url=settings.deepseek_base_url,
                          model="deepseek-chat", max_retry=1, backoff=0.5)


@lru_cache
def get_prompt_builder():
    from kbqa.core.generation import PromptBuilder
    prompt_dir = Path(__file__).resolve().parents[1] / "prompts"
    return PromptBuilder(prompt_dir)


@lru_cache
def get_generator():
    from kbqa.core.generation import Generator
    from kbqa.core.validation import Validator
    return Generator(get_llm(), get_prompt_builder(), Validator())


@lru_cache
def get_orchestrator():
    from kbqa.core.fallback import FallbackHandler
    from kbqa.core.orchestration import QaOrchestrator
    from kbqa.services.rewrite_service import LlmRewriter
    return QaOrchestrator(
        retriever=get_retriever(), generator=get_generator(),
        fallback=FallbackHandler(), tau=0.30,
        rewriter=LlmRewriter(get_llm(), get_prompt_builder()),
        answerability=(AnswerabilityChecker(get_llm(), Path(__file__).resolve().parents[1] / "prompts")
                       if settings.answerability_check else None),
    )


@lru_cache
def get_qa_service():
    from kbqa.services.qa_service import QaService
    return QaService(get_orchestrator())


@lru_cache
def get_eval_service():
    from kbqa.services.eval_service import EvalService
    return EvalService(get_qa_service(), get_job_runner())
