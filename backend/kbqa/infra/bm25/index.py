"""BM25 稀疏检索：jieba 分词 + rank_bm25 内存索引（见 ADR-009）。"""

from __future__ import annotations

import pickle
from pathlib import Path
from typing import Iterable

import jieba
import numpy as np
from rank_bm25 import BM25Okapi

_DEFAULT_STOP = {
    "的", "了", "和", "是", "在", "有", "就", "不", "也", "都", "这", "那",
    "你", "我", "他", "它", "们", "与", "或", "但", "而", "把", "被", "让",
    "为", "以", "及", "等", "个", "中", "上", "下", "对", "从", "到",
}

STOPWORDS: set[str] = set(_DEFAULT_STOP)
_jieba = jieba.Tokenizer()


def init_tokenizer(dict_path: Path | None = None,
                   stopwords_path: Path | None = None) -> None:
    """启动时调用一次。jieba 的 load_userdict 非线程安全，不可在请求内调用。"""
    global STOPWORDS
    if dict_path and dict_path.exists():
        _jieba.load_userdict(str(dict_path))
    if stopwords_path and stopwords_path.exists():
        STOPWORDS = {w.strip() for w in stopwords_path.read_text(encoding="utf-8").splitlines() if w.strip()}
    else:
        STOPWORDS = set(_DEFAULT_STOP)


def tokenize(text: str) -> list[str]:
    out: list[str] = []
    for t in _jieba.lcut(text.lower()):
        t = t.strip()
        if not t or t in STOPWORDS:
            continue
        if len(t) == 1 and not t.isascii():
            continue
        out.append(t)
    return out


class Bm25Index:
    def __init__(self, persist_path: Path | None = None) -> None:
        self.persist_path = persist_path
        self._uids: list[str] = []
        self._doc_ids: list[int] = []
        self._tokens: list[list[str]] = []
        self._bm25: BM25Okapi | None = None

    # ---------------- 构建 ----------------
    def add_batch(self, uids: list[str], doc_ids: list[int], texts: list[str]) -> None:
        if not (len(uids) == len(doc_ids) == len(texts)):
            raise ValueError("uids/doc_ids/texts 长度必须一致")
        self._uids.extend(uids)
        self._doc_ids.extend(doc_ids)
        self._tokens.extend(tokenize(t) for t in texts)
        self._rebuild()

    def remove_by_doc(self, doc_id: int) -> int:
        keep = [i for i, d in enumerate(self._doc_ids) if d != doc_id]
        removed = len(self._doc_ids) - len(keep)
        if removed:
            self._uids = [self._uids[i] for i in keep]
            self._doc_ids = [self._doc_ids[i] for i in keep]
            self._tokens = [self._tokens[i] for i in keep]
            self._rebuild()
        return removed

    def rebuild(self, rows: Iterable[tuple[str, int, str]]) -> None:
        self._uids, self._doc_ids, self._tokens = [], [], []
        for uid, doc_id, text in rows:
            self._uids.append(uid)
            self._doc_ids.append(doc_id)
            self._tokens.append(tokenize(text))
        self._rebuild()

    def _rebuild(self) -> None:
        self._bm25 = BM25Okapi(self._tokens, k1=1.5, b=0.75) if self._tokens else None

    # ---------------- 查询 ----------------
    def search(self, query: str, top_k: int = 30) -> list[tuple[str, float]]:
        if self._bm25 is None or not self._uids:
            return []
        tokens = tokenize(query)
        if not tokens:
            return []
        scores = np.asarray(self._bm25.get_scores(tokens), dtype=np.float32)
        if not np.any(scores > 0):
            return []
        top_k = min(top_k, len(scores))
        idx = np.argpartition(-scores, top_k - 1)[:top_k]
        idx = idx[np.argsort(-scores[idx])]
        return [(self._uids[i], float(scores[i])) for i in idx if scores[i] > 0]

    def count(self) -> int:
        return len(self._uids)

    # ---------------- 持久化 ----------------
    def persist(self) -> None:
        if self.persist_path is None:
            return
        self.persist_path.parent.mkdir(parents=True, exist_ok=True)
        with self.persist_path.open("wb") as fh:
            pickle.dump({"uids": self._uids, "doc_ids": self._doc_ids,
                         "tokens": self._tokens}, fh)

    def load(self) -> bool:
        if self.persist_path is None or not self.persist_path.exists():
            return False
        try:
            with self.persist_path.open("rb") as fh:
                data = pickle.load(fh)
        except Exception:  # noqa: BLE001
            return False
        self._uids = data.get("uids", [])
        self._doc_ids = data.get("doc_ids", [])
        self._tokens = data.get("tokens", [])
        self._rebuild()
        return True
