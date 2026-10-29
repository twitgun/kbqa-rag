"""引用编号归一化：把「参考资料编号」对齐到「citations 序号」。

背景（实测踩坑）：
- 提示词让模型按参考资料编号写 `[3][5]`；
- 但 citations 只列实际用到的片段（可能是 2 条）；
- V-04 若直接拿标记去比 `len(citations)`，必然误判。

因此先归一化：按标记**首次出现顺序**重排 citations，并把答案里的标记
改写成连续的 `[1][2]…`，此后 V-03/V-04/V-05 才有统一口径。
"""

from __future__ import annotations

import re

from kbqa.core.validation.types import RawAnswer, ValidationIssue

# 同时支持 [1]、[1][3]、[1, 3]、[1、3]
_MARKER_GROUP = re.compile(r"\[(\d+(?:\s*[,，、]\s*\d+)*)\]")

# 模型判定"答不了"时的典型措辞（用于识别"自相矛盾的拒答"）
_REFUSAL_HINTS = ("未找到", "未提及", "没有找到", "无法回答", "无法确认",
                  "未涉及", "资料中未", "知识库中未", "不足以回答",
                  "中找到", "未在知识库", "没有相关", "无相关", "未提供")


def _markers_in_order(text: str) -> list[int]:
    seen: list[int] = []
    for group in _MARKER_GROUP.findall(text):
        for part in re.split(r"[,，、]", group):
            part = part.strip()
            if part.isdigit():
                n = int(part)
                if n not in seen:
                    seen.append(n)
    return seen


def _looks_like_refusal(text: str) -> bool:
    return any(h in text for h in _REFUSAL_HINTS)

def normalize(answer: RawAnswer, candidates: list[Candidate]) -> tuple[RawAnswer, list[ValidationIssue]]:
    """返回 (归一化后的答案, 问题列表)。无法归一化时返回带问题列表的原答案。"""
    issues: list[ValidationIssue] = []
    order = _markers_in_order(answer.answer)
    if not order:
        return answer, issues

    # 情况一：模型口头拒答（"未找到依据"）却漏设 insufficient、且没给 citations。
    # 这是格式瑕疵而非幻觉，应归一化为"证据不足"，不该判成校验失败。
    if not answer.citations and _looks_like_refusal(answer.answer):
        return RawAnswer(
            answer=_MARKER_GROUP.sub("", answer.answer).strip(),
            citations=[], insufficient=True, confidence=answer.confidence,
        ), issues

    upper = len(candidates)
    out_of_range = [n for n in order if n < 1 or n > upper]
    if out_of_range:
        return answer, [ValidationIssue(
            "V-04", f"引用了不存在的片段编号 {out_of_range}（本轮共 {upper} 个片段）")]

    # 数量不必严格相等：
    # - citations 多出（模型多列了没引用的片段）→ 截掉多余的，无害；
    # - citations 少于标记数 → 有标记找不到出处，无法核验，必须拒。
    # 早期要求严格相等，实测在高温度下误杀 6/70 道可答题（V-04 独占）。
    if len(answer.citations) < len(order):
        return answer, [ValidationIssue(
            "V-04", f"答案引用了 {len(order)} 个不同片段，但 citations 只提供 "
                    f"{len(answer.citations)} 条，缺少出处无法核验")]

    # 标记是「参考资料编号」（如 [3][5]），不能拿去索引 citations；
    # 约定 citations 按标记首次出现顺序给出，故直接配对后重写标记为 1..k。
    remap = {marker: idx + 1 for idx, marker in enumerate(order)}
    reordered = list(answer.citations)[: len(order)]

    def _rewrite(match: re.Match) -> str:
        nums = [int(p.strip()) for p in re.split(r"[,，、]", match.group(1)) if p.strip().isdigit()]
        return "".join(f"[{remap[n]}]" for n in nums if n in remap)

    return RawAnswer(
        answer=_MARKER_GROUP.sub(_rewrite, answer.answer),
        citations=reordered,
        insufficient=answer.insufficient,
        confidence=answer.confidence,
    ), issues
