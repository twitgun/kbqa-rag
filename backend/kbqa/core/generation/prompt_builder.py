"""提示词组装：模板外置 + 变量注入 + token 预算裁剪（见 03_核心机制/03）。"""

from __future__ import annotations

import re
from pathlib import Path

from kbqa.core.generation.types import Turn
from kbqa.core.retrieval.types import Candidate
from kbqa.core.validation.types import ValidationIssue


def truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "……"


class PromptBuilder:
    def __init__(self, prompt_dir: Path, *, max_context_tokens: int = 6000,
                 history_turns: int = 3, version: str = "v1") -> None:
        self.dir = Path(prompt_dir)
        self.max_context_tokens = max_context_tokens
        self.history_turns = history_turns
        self.version = version

    # ---------------- 模板 ----------------
    def _load(self, name: str) -> str:
        return (self.dir / f"{name}_{self.version}.txt").read_text(encoding="utf-8")

    # ---------------- 组装 ----------------
    def render_context(self, candidates: list[Candidate]) -> str:
        lines: list[str] = []
        for i, c in enumerate(candidates, start=1):
            loc = f"第 {c.page_no} 页" if c.page_no else (c.section_path or "正文")
            lines.append(
                f"[{i}] chunk_id={c.chunk_uid} ｜ 来源：{c.doc_title or '未知文档'} ｜ 位置：{loc}\n"
                f"{c.text.strip()}"
            )
        return "\n\n".join(lines)

    def build(self, *, query: str, candidates: list[Candidate],
              history: list[Turn] | None = None, summary: str | None = None,
              plain: bool = False) -> list[dict]:
        """plain=True 用于 L1 基线：不提供参考资料，用普通助手提示词。

        若 L1 沿用带"仅依据参考资料"约束的提示词，它会因拿不到资料而一律拒答，
        对照组退化成 0 正确率，对比就失去意义（实测踩过）。
        """
        if plain:
            messages = [{"role": "system", "content": self._load("system_l1_plain")}]
            for turn in (history or [])[-self.history_turns:]:
                messages.append({"role": "user", "content": truncate(turn.question, 400)})
                messages.append({"role": "assistant", "content": truncate(turn.answer, 400)})
            tpl = self._load("user_l1_plain")
            messages.append({"role": "user", "content": tpl.replace("{question}", query)})
            return messages

        messages: list[dict] = [
            {"role": "system", "content": self._load("system")}
        ]

        if summary:
            messages.append({"role": "user", "content": f"【对话摘要】{summary}"})
            messages.append({"role": "assistant", "content": "好的，我已了解之前的讨论。"})

        for turn in (history or [])[-self.history_turns:]:
            if turn.is_fallback:          # 兜底轮次不进上下文，避免"未找到依据"被当成事实
                continue
            messages.append({"role": "user", "content": truncate(turn.question, 400)})
            messages.append({"role": "assistant", "content": truncate(turn.answer, 400)})

        messages.append({"role": "user", "content": self._render_user(candidates, query)})
        return self._shrink(messages, candidates, query)

    def _render_user(self, candidates: list[Candidate], query: str) -> str:
        return self._load("user_template").format(
            context=self.render_context(candidates), question=query)

    def build_retry(self, *, query: str, candidates: list[Candidate],
                    issues: list[ValidationIssue], plain: bool = False) -> list[dict]:
        """重试必须保留原问题与参考资料，只在末尾追加纠错指令。

        早期版本只发纠错文本，模型会把"校验错误信息"当问题回答——
        实测出现过"未能在知识库中找到与「引用标记超出 citations 数量」相关的依据"。
        """
        messages = self.build(query=query, candidates=candidates, plain=plain)
        issues_text = "；".join(i.detail for i in issues)[:300]
        messages.append({
            "role": "user",
            "content": (f"你上一次的输出未通过校验：{issues_text}。\n"
                        f"请针对上面同一个问题重新作答，只输出 JSON，不要解释。"),
        })
        return messages

    # ---------------- 预算 ----------------
    def estimate_tokens(self, messages: list[dict]) -> int:
        text = "".join(m["content"] for m in messages)
        zh = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
        other = len(text) - zh
        return int(zh + other / 3.5) + len(messages) * 4

    def _shrink(self, messages: list[dict], candidates: list[Candidate],
                query: str) -> list[dict]:
        while self.estimate_tokens(messages) > self.max_context_tokens:
            if len(messages) > 2:                      # 先删历史，保留 system + 末条 user
                idx = next((i for i, m in enumerate(messages)
                            if i > 0 and m["role"] != "system"), 1)
                del messages[idx]
                continue
            if len(candidates) > 1:                    # 再删最低分片段
                candidates = candidates[:-1]
                messages[-1] = {"role": "user",
                                "content": self._render_user(candidates, query)}
                continue
            break
        return messages

    # ---------------- 其他模板 ----------------
    def render_rewrite(self, history: str, question: str) -> str:
        return self._load("rewrite").format(history=history, question=question)

    def render_summary(self, conversation: str) -> str:
        return self._load("summary").format(conversation=conversation)

    def render_judge(self, *, question: str, gold_answer: str,
                     context: str, answer: str) -> str:
        return self._load("judge").format(question=question, gold_answer=gold_answer,
                                          context=context[:3000], answer=answer[:2000])


def extract_keywords(text: str) -> list[str]:
    """粗粒度关键词：英文标识符 + 中文二元片段，用于改写跑题检测。"""
    ascii_words = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", text)
    zh = re.sub(r"[^\u4e00-\u9fff]", " ", text)
    zh_bigrams = [zh[i:i + 2] for i in range(0, max(0, len(zh) - 1))]
    return list(dict.fromkeys([w.lower() for w in ascii_words] +
                              [b for b in zh_bigrams if len(b) == 2]))[:20]
