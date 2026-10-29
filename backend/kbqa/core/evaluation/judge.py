"""答案判定（LLM-as-judge）：给出 verdict / hallucination / faithfulness。

判定口径见 `prompts/judge_v1.txt`：
- hallucination = 答案含【参考资料】与【标准答案】都不存在的事实；
- 明确拒答不算幻觉（否则把"诚实地不知道"和"编造"混为一谈）。
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger("kbqa.judge")

_JSON = re.compile(r"\{.*\}", re.S)
VALID_VERDICTS = {"正确", "部分正确", "错误"}
# 盲评：抹掉引用标记与"根据资料"这类元信息，避免评审员凭"有没有引用"先入为主
_MARKERS = re.compile(r"\[\d+(?:\s*[,，、]\s*\d+)*\]")
_META_PREFIX = re.compile(r"^(根据|依据|按照)(参考)?(资料|文档|上下文|片段)[，,：:]?\s*")


def blind(text: str) -> str:
    """去掉答案里的引用标记与"依据资料"式开头，供盲评使用。"""
    out = _MARKERS.sub("", text or "")
    out = _META_PREFIX.sub("", out.strip())
    return re.sub(r"\s{2,}", " ", out).strip()


class Judge:
    def __init__(self, llm, prompt_dir: Path) -> None:
        self.llm = llm
        self.template = (Path(prompt_dir) / "judge_v1.txt").read_text(encoding="utf-8")

    async def judge(self, *, question: str, answer: str, gold_answer: str | None,
                    contexts: list[str], is_fallback: bool = False,
                    blind_mode: bool = True, qtype: str = "answerable") -> dict:
        # 系统拒答：直接按"未作答"处理，不调用模型（省钱且避免把拒答判成幻觉）
        if is_fallback or not (answer or "").strip():
            return {"verdict": "错误", "hallucination": False, "faithfulness": 0.0,
                    "reason": "系统拒答或空答案", "judged_by": "rule"}

        # 模板里含字面量 JSON 花括号，不能用 str.format，改用占位符替换
        prompt = (self.template
                  .replace("{gold_answer}", gold_answer or "（无标准答案，本题本不应作答）")
                  .replace("{question}", question)
                  .replace("{context}", "\n\n".join(
                      f"[{i}] {t[:800]}" for i, t in enumerate(contexts, 1)) or "（无参考资料）")
                  .replace("{answer}", (blind(answer) if blind_mode else (answer or ""))[:1500]))
        for attempt in range(2):
            try:
                raw = await self.llm.complete(
                    [{"role": "user", "content": prompt}],
                    temperature=0.0, max_tokens=200, timeout=40, json_mode=False)
                data = self._parse(raw.text)
                if data is None:
                    continue
                verdict = self._normalize(data, contexts)
                # 不可答题只要给出了实质答案，就是"越界作答"——不管内容看着对不对。
                # 早期版本漏了这条，导致该指标恒为 0，把系统的实际越界行为掩盖了。
                if qtype == "unanswerable" and not self._is_refusal(answer):
                    verdict.update({"verdict": "错误", "hallucination": True,
                                    "faithfulness": 0.0,
                                    "reason": "对不可答题给出实质答案（越界作答）",
                                    "judged_by": "rule"})
                return verdict
            except Exception as exc:  # noqa: BLE001
                logger.warning("judge_failed attempt=%s: %s", attempt, exc)
        return {"verdict": "错误", "hallucination": False, "faithfulness": 0.0,
                "reason": "判定失败（模型不可用）", "judged_by": "rule"}

    @staticmethod
    def _parse(text: str) -> dict | None:
        text = re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.M).strip()
        m = _JSON.search(text)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _is_refusal(answer: str) -> bool:
        hints = ("未找到", "未提及", "没有找到", "无法回答", "无法确认", "未涉及",
                 "资料中未", "知识库中未", "不足以回答", "中没有提到", "未提供", "不确定")
        text = answer or ""
        return any(h in text[:200] for h in hints)

    @staticmethod
    def _normalize(data: dict, contexts: list[str]) -> dict:
        verdict = str(data.get("verdict", "")).strip()
        if verdict not in VALID_VERDICTS:
            verdict = "错误" if "错" in verdict else "部分正确"
        try:
            faith = float(data.get("faithfulness", 0.0))
        except (TypeError, ValueError):
            faith = 0.0
        # 没有参考资料时，"被支撑比例"无意义，置 None 不参与平均
        if not contexts:
            faith = None
        return {
            "verdict": verdict,
            "hallucination": bool(data.get("hallucination", False)),
            "faithfulness": None if faith is None else max(0.0, min(1.0, faith)),
            "reason": str(data.get("reason", ""))[:200],
            "judged_by": "llm",
        }
