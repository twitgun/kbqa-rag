"""历史摘要压缩（FR-28）：会话变长后把早期轮次压成 ≤200 字，控制 token 成本。

设计：
- 只在轮数达到 `conversation.summary_trigger_turns` 时触发；
- 摘要覆盖「除最近 history_turns 轮以外」的全部内容；
- 模型不可用时静默跳过，不影响问答主链路。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from kbqa.core.generation.types import Turn

logger = logging.getLogger("kbqa.summary")


class SummaryService:
    def __init__(self, llm, prompt_dir: Path, *, max_chars: int = 200,
                 timeout: int = 20) -> None:
        self.llm = llm
        self.template = (Path(prompt_dir) / "summary_v1.txt").read_text(encoding="utf-8")
        self.max_chars = max_chars
        self.timeout = timeout

    async def summarize(self, history: list[Turn]) -> str | None:
        if not history:
            return None
        conversation = "\n".join(
            f"用户：{t.question}\n助手：{t.answer[:300]}" for t in history)
        prompt = self.template.replace("{conversation}", conversation[:6000])
        try:
            raw = await self.llm.complete(
                [{"role": "user", "content": prompt}],
                temperature=0.0, max_tokens=self.max_chars * 2,
                timeout=self.timeout, json_mode=False)
        except Exception as exc:  # noqa: BLE001 — 摘要失败不能拖垮问答
            logger.warning("summary_failed: %s", exc)
            return None

        text = self._clean(raw.text)
        return text[: self.max_chars] if text else None

    _PREFIX = re.compile(r"^\s*(摘要|总结|概要)\s*[：:]\s*")

    @classmethod
    def _clean(cls, text: str) -> str:
        text = (text or "").strip()
        text = cls._PREFIX.sub("", text)
        return " ".join(text.split())
