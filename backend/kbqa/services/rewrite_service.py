"""追问改写：把「那它呢」补全成可独立检索的问题（FR-27，见 03/06）。

约定：**改写失败返回空字符串**，而不是原问题。
编排层据此把 rewritten_question 保持为 None 并沿用原问题，
避免前端把"没改写"误显示成"已改写为原句"。
"""

from __future__ import annotations

import logging
import re

from kbqa.core.generation.prompt_builder import PromptBuilder, extract_keywords
from kbqa.core.generation.types import Turn

logger = logging.getLogger("kbqa.rewrite")

_PREFIX = re.compile(r"^(改写结果|改写后的问题|结果是|问题)[：:]\s*")


class LlmRewriter:
    """实现 core.orchestration.Rewriter 协议。"""

    def __init__(self, llm, builder: PromptBuilder, *, max_tokens: int = 120,
                 timeout: int = 8) -> None:
        self.llm = llm
        self.builder = builder
        self.max_tokens = max_tokens
        self.timeout = timeout

    async def rewrite(self, question: str, history: list[Turn]) -> str:
        if not history:
            return ""

        history_text = "\n".join(
            f"用户：{t.question}\n助手：{t.answer[:200]}" for t in history[-3:])
        prompt = self.builder.render_rewrite(history=history_text, question=question)

        try:
            raw = await self.llm.complete(
                [{"role": "user", "content": prompt}],
                temperature=0.0, max_tokens=self.max_tokens,
                timeout=self.timeout, json_mode=False)
        except Exception as exc:  # noqa: BLE001 — 模型不可用时降级
            logger.warning("rewrite_failed: %s", exc)
            return ""

        text = self._sanitize(raw.text)
        # 短追问（如「那凭据呢」）本身抽不出实词，需用历史关键词做跑题判定，
        # 否则会把「改写后引入了当轮的正确术语」误判为跑题。
        context_kws = extract_keywords(question)
        if len(question) <= 10 or not context_kws:
            context_kws = extract_keywords(" ".join(t.question for t in history[-3:]))
        if not self._reasonable(text, question, context_kws):
            logger.info("rewrite_rejected text=%r", text[:60])
            return ""
        return text

    @staticmethod
    def _sanitize(text: str) -> str:
        lines = (text or "").strip().splitlines()
        head = lines[0].strip() if lines else ""
        return _PREFIX.sub("", head).strip().strip('"“”').strip()

    @staticmethod
    def _reasonable(candidate: str, original: str, context_kws: list[str] | None = None) -> bool:
        if not candidate or len(candidate) < 2:
            return False
        if len(candidate) > max(120, len(original) * 4):
            return False

        kws = context_kws or extract_keywords(original)
        if not kws:
            return True

        # 有英文标识符（API 名、参数名）时以它为准：中文二元组里「怎么/什么」这类
        # 通用词会让任何句子都"命中"，判定形同虚设。
        ascii_kws = [k for k in kws if k.isascii() and len(k) >= 3]
        if ascii_kws:
            low = candidate.lower()
            return any(k.lower() in low for k in ascii_kws)
        return any(k in candidate for k in kws)
