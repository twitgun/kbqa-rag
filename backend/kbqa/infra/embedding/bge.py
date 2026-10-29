"""BGE 系列向量化（生产实现，见 ADR-006）。

默认目标是 BGE-M3；带宽不足时可先用 bge-small-zh-v1.5（512 维）顶上，
两者接口一致，切换只改 `settings.embedding_model`。
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

logger = logging.getLogger("kbqa.embedding")


class BgeEmbedding:
    def __init__(self, model_path: Path, device: str = "cpu", batch_size: int = 8,
                 max_length: int = 512) -> None:
        from sentence_transformers import SentenceTransformer

        self.model_path = Path(model_path)
        self.name = self.model_path.name
        self.batch_size = batch_size
        self.max_length = max_length
        self.model = SentenceTransformer(str(self.model_path), device=device,
                                         local_files_only=True)
        # bge-small 最大 512；M3 支持 8192，但片段只有几百字，512 足够
        self.model.max_seq_length = min(max_length, self.model.max_seq_length)
        # sentence-transformers 6.x 改了方法名，兼容两种
        get_dim = getattr(self.model, "get_embedding_dimension", None) or self.model.get_sentence_embedding_dimension
        self.dim = int(get_dim())
        logger.info("bge_loaded path=%s dim=%s device=%s", self.model_path, self.dim, device)

    def encode_documents(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        vecs = self.model.encode(texts, batch_size=self.batch_size,
                                 normalize_embeddings=True, show_progress_bar=False,
                                 convert_to_numpy=True)
        return np.asarray(vecs, dtype=np.float32)

    def encode_query(self, text: str) -> np.ndarray:
        vec = self.model.encode([text], normalize_embeddings=True,
                                show_progress_bar=False, convert_to_numpy=True)[0]
        return np.asarray(vec, dtype=np.float32)


# 兼容旧名
BgeM3Embedding = BgeEmbedding
