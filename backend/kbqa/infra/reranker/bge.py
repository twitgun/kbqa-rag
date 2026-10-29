"""Cross-Encoder 重排（BGE-reranker-v2-m3，见 ADR-007）。

与双塔的区别：把 (query, passage) 拼在一起过一遍模型，判断"这段材料能否回答问题"，
输出的 logits 经 sigmoid 归一到 [0,1]，这正是阈值判定的量纲。
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

logger = logging.getLogger("kbqa.reranker")


class BgeReranker:
    def __init__(self, model_path: Path, device: str = "cpu", batch_size: int = 8,
                 max_length: int = 512) -> None:
        from sentence_transformers import CrossEncoder

        self.name = Path(model_path).name
        self.batch_size = batch_size
        self.model = CrossEncoder(str(model_path), device=device,
                                  max_length=max_length, local_files_only=True)
        logger.info("reranker_loaded path=%s", model_path)

    def rerank(self, query: str, passages: list[str],
               top_k: int = 5) -> list[tuple[int, float]]:
        """返回 [(原索引, 分数)]，按分数降序。

        注意：sentence-transformers 的 CrossEncoder 对 num_labels=1 的模型
        自带 Sigmoid 激活（activation_fn），predict 返回的**已经是 [0,1] 概率**。
        早期版本又套了一层 sigmoid，把分数压到 0.5~0.73，严重损害可分性
        （实测 AUC 从应有的高位掉到 0.86 附近）。
        """
        if not passages:
            return []
        pairs = [[query, p] for p in passages]
        raw = self.model.predict(pairs, batch_size=self.batch_size,
                                 show_progress_bar=False)
        scores = np.asarray(raw, dtype=np.float32).reshape(-1)
        order = np.argsort(-scores)[:top_k]
        return [(int(i), float(scores[i])) for i in order]
