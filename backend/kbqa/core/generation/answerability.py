"""生成前的可答性判定（answerability check）。

动机：阈值只能识别"完全跑题"，识别不了"话题相关但资料没有答案"。
在调用生成模型之前，先让模型看一眼资料能否回答问题，不能就直接走 F-01。

代价：一次额外调用（约 0.8–1.5s）；收益：把"硬答"挡在生成之前。
失败策略：判定异常时**放行**（宁漏勿错杀），因为后续还有引用校验与兜底。
"""

from __future__ import annotations

import logging
from pathlib import Path

from kbqa.core.retrieval.types import Candidate

logger = logging.getLogger("kbqa.answerability")


class AnswerabilityChecker:
    def __init__(self, llm, prompt_dir: Path, *, max_context: int = 2400,
                 timeout: int = 15) -> None:
        self.llm = llm
        self.template = (Path(prompt_dir) / "answerability_v1.txt").read_text(encoding="utf-8")
        self.max_context = max_context
        self.timeout = timeout

    async def can_answer(self, query: str, candidates: list[Candidate]) -> bool | None:
        """True=能答；False=不能答；None=判定失败（调用方应放行）。"""
        if not candidates:
            return False
        context = "\n\n".join(f"[{i}] {c.text[:600]}" for i, c in enumerate(candidates, 1))
        prompt = (self.template
                  .replace("{question}", query)
                  .replace("{context}", context[: self.max_context]))
        try:
            raw = await self.llm.complete(
                [{"role": "user", "content": prompt}],
                temperature=0.0, max_tokens=8, timeout=self.timeout, json_mode=False)
        except Exception as exc:  # noqa: BLE001
            logger.warning("answerability_failed: %s", exc)
            return None

        text = (raw.text or "").strip()
        if "不能" in text:
            return False
        if "能" in text:
            return True
        logger.info("answerability_unclear: %r", text[:20])
        return None
