"""向量存储接口 + 内存实现（生产用 Chroma，见 ADR-005）。"""

from __future__ import annotations

import pickle
from pathlib import Path

import numpy as np


class MemoryVectorStore:
    """进程内向量表，可持久化到 pickle。仅供开发联调与单测。"""

    def __init__(self, persist_path: Path | None = None) -> None:
        self.persist_path = persist_path
        self._vecs: dict[str, np.ndarray] = {}
        self._meta: dict[str, dict] = {}

    def upsert(self, ids: list[str], vectors: np.ndarray,
               metadatas: list[dict], documents: list[str]) -> None:
        for i, uid in enumerate(ids):
            self._vecs[uid] = np.asarray(vectors[i], dtype=np.float32)
            self._meta[uid] = dict(metadatas[i])

    def delete_by_doc(self, doc_id: int) -> int:
        doomed = [uid for uid, meta in self._meta.items() if meta.get("doc_id") == doc_id]
        for uid in doomed:
            self._vecs.pop(uid, None)
            self._meta.pop(uid, None)
        return len(doomed)

    def query(self, vector: np.ndarray, top_k: int,
              where: dict | None = None) -> list[tuple[str, float, dict]]:
        if not self._vecs:
            return []
        q = np.asarray(vector, dtype=np.float32)
        qn = np.linalg.norm(q)
        q = q / qn if qn > 0 else q
        scored: list[tuple[str, float, dict]] = []
        for uid, vec in self._vecs.items():
            meta = self._meta[uid]
            if where and any(meta.get(k) != v for k, v in where.items()):
                continue
            vn = np.linalg.norm(vec)
            sim = float(np.dot(q, vec) / (vn if vn > 0 else 1.0))
            scored.append((uid, sim, meta))
        scored.sort(key=lambda x: (-x[1], x[0]))
        return scored[:top_k]

    def count(self) -> int:
        return len(self._vecs)

    def ping(self) -> bool:
        return True

    def reset(self) -> None:
        self._vecs.clear()
        self._meta.clear()

    def persist(self) -> None:
        if self.persist_path is None:
            return
        self.persist_path.parent.mkdir(parents=True, exist_ok=True)
        with self.persist_path.open("wb") as fh:
            pickle.dump({"vecs": self._vecs, "meta": self._meta}, fh)

    def load(self) -> bool:
        if self.persist_path is None or not self.persist_path.exists():
            return False
        try:
            with self.persist_path.open("rb") as fh:
                data = pickle.load(fh)
        except Exception:  # noqa: BLE001
            return False
        self._vecs = data.get("vecs", {})
        self._meta = data.get("meta", {})
        return True
