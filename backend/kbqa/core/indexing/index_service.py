"""索引服务：切分 → 向量化 → 写向量库 + BM25 → 写 chunks 表。"""

from __future__ import annotations

from typing import Callable

from kbqa.core.chunking import ChunkParams, get_chunker
from kbqa.core.ingest.types import ParsedDocument
from kbqa.infra.bm25.index import Bm25Index, tokenize
from kbqa.infra.db import models as m
from kbqa.infra.db.repositories import ChunkRepo, DocumentRepo
from kbqa.infra.embedding.base import EmbeddingProvider
from kbqa.infra.vectorstore.memory import MemoryVectorStore

Progress = Callable[[int, int, str], None]


class IndexService:
    def __init__(self, *, embedder: EmbeddingProvider, vector_store: MemoryVectorStore,
                 bm25: Bm25Index, chunk_repo_factory, doc_repo_factory) -> None:
        self.embedder = embedder
        self.vector_store = vector_store
        self.bm25 = bm25
        self.chunk_repo_factory = chunk_repo_factory
        self.doc_repo_factory = doc_repo_factory

    def index_document(self, db, doc: m.Document, parsed: ParsedDocument,
                       params: ChunkParams, progress: Progress | None = None) -> int:
        report = progress or (lambda done, total, msg: None)
        chunker = get_chunker(params.strategy)

        chunks = chunker.chunk(parsed, params)
        report(1, 4, f"切分完成，{len(chunks)} 个片段")

        uids = [f"d{doc.id}_c{c.chunk_index:05d}" for c in chunks]
        texts = [c.text for c in chunks]
        vectors = self.embedder.encode_documents(texts)
        report(2, 4, "向量化完成")

        metas = [{"doc_id": doc.id, "page_no": c.page_no, "status": "ready"} for c in chunks]
        self.vector_store.upsert(uids, vectors, metas, texts)
        self.bm25.add_batch(uids, [doc.id] * len(uids), texts)
        self.bm25.persist()
        self.vector_store.persist()
        report(3, 4, "向量与 BM25 写入完成")

        chunk_repo = self.chunk_repo_factory(db)
        chunk_repo.delete_by_doc(doc.id)          # 重建时先清旧片段
        rows = [{
            "chunk_uid": uid, "doc_id": doc.id, "chunk_index": c.chunk_index,
            "text": c.text, "char_start": c.char_start, "char_end": c.char_end,
            "char_len": c.char_end - c.char_start,   # 原文跨度，不含【path】前缀
            "page_no": c.page_no, "section_path": c.section_path[:500],
            "token_count": len(tokenize(c.text)), "chunk_strategy": params.strategy,
        } for uid, c in zip(uids, chunks)]
        chunk_repo.bulk_insert(rows)

        doc_repo = self.doc_repo_factory(db)
        doc_repo.mark_ready(doc.id, chunk_count=len(chunks), strategy=params.strategy,
                            params={"strategy": params.strategy,
                                    "target_size": params.target_size,
                                    "max_size": params.max_size,
                                    "min_size": params.min_size,
                                    "overlap": params.overlap},
                            char_count=parsed.char_count,
                            page_count=parsed.page_count,
                            parsed_meta=parsed.doc_meta)
        report(4, 4, "完成")
        return len(chunks)
