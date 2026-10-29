"""向量化接口与一个**仅用于本地联调**的确定性实现。

生产应使用 BGE-M3（见 ADR-006）。当模型文件缺失时，系统回退到 HashEmbedding，
让"上传→切分→索引→检索"的链路可以先跑通，但**检索质量不可用于评测**。
"""

from __future__ import annotations

import hashlib
from typing import Protocol

import numpy as np


class EmbeddingProvider(Protocol):
    dim: int

    def encode_documents(self, texts: list[str]) -> np.ndarray: ...

    def encode_query(self, text: str) -> np.ndarray: ...


class HashEmbedding:
    """把文本哈希到固定维度并归一化。确定性、零依赖，仅用于开发联调。"""

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim
        self.name = "hash-dev"

    def _encode_one(self, text: str) -> np.ndarray:
        vec = np.zeros(self.dim, dtype=np.float32)
        for token in text.lower().split():
            h = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16)
            vec[h % self.dim] += 1.0
        # 中文没有空格，按字符二元组补一遍，避免整段挤到一个桶
        for i in range(len(text) - 1):
            h = int(hashlib.md5(text[i:i + 2].encode("utf-8")).hexdigest(), 16)
            vec[h % self.dim] += 0.5
        norm = np.linalg.norm(vec)
        return vec / norm if norm > 0 else vec

    def encode_documents(self, texts: list[str]) -> np.ndarray:
        return np.stack([self._encode_one(t) for t in texts]) if texts else np.zeros((0, self.dim), dtype=np.float32)

    def encode_query(self, text: str) -> np.ndarray:
        return self._encode_one(text)
