"""评测指标计算（M-01 ~ M-12），口径见 00_项目治理/05_指标定义与验收基线。

纯计算，不依赖数据库与模型：输入是逐题结果字典，输出是指标字典。
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from typing import Any, Iterable


def _r3(x: float | None) -> float | None:
    return None if x is None else round(float(x), 3)


def recall_at_k(gold: list[str], retrieved: list[str], k: int = 5) -> float | None:
    """gold 为空（无答案题）返回 None，不参与平均。"""
    if not gold:
        return None
    top = set(retrieved[:k])
    return len(set(gold) & top) / len(set(gold))


def mrr_at_k(gold: list[str], retrieved: list[str], k: int = 10) -> float | None:
    if not gold:
        return None
    for rank, uid in enumerate(retrieved[:k], start=1):
        if uid in set(gold):
            return 1.0 / rank
    return None


def percentile(values: list[int], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    pos = (len(ordered) - 1) * p
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    frac = pos - lo
    return ordered[lo] * (1 - frac) + ordered[hi] * frac


def compute_mode_metrics(items: list[dict[str, Any]], questions: dict[int, dict]) -> dict:
    """单个 mode 的指标。items 需含 question_id / is_fallback / judge / recall5 / mrr10 / latency_ms。"""
    answerable = [i for i in items if questions[i["question_id"]]["qtype"] == "answerable"]
    unanswerable = [i for i in items if questions[i["question_id"]]["qtype"] == "unanswerable"]

    verdicts = Counter((i.get("judge") or {}).get("verdict") for i in answerable)
    n_ans = len(answerable) or 1

    halluc = sum(1 for i in items if (i.get("judge") or {}).get("hallucination") is True)
    faithful = [(i.get("judge") or {}).get("faithfulness") for i in items if not i.get("is_fallback")]
    faithful = [f for f in faithful if isinstance(f, (int, float))]

    abst = sum(1 for i in unanswerable if i.get("is_fallback"))
    false_abst = sum(1 for i in answerable if i.get("is_fallback"))

    recalls = [i["recall5"] for i in answerable if i.get("recall5") is not None]
    mrrs = [i["mrr10"] for i in answerable if i.get("mrr10") is not None]
    lat = [i["latency_ms"] for i in items if i.get("latency_ms") is not None]

    return {
        "total": len(items),
        "accuracy": _r3(verdicts["正确"] / n_ans),
        "partial": _r3(verdicts["部分正确"] / n_ans),
        "error": _r3(verdicts["错误"] / n_ans),
        "hallucination_rate": _r3(halluc / len(items)) if items else 0.0,
        "faithfulness": _r3(statistics.mean(faithful)) if faithful else None,
        "abstention_accuracy": _r3(abst / len(unanswerable)) if unanswerable else None,
        "false_abstention": _r3(false_abst / len(answerable)) if answerable else None,
        "recall5": _r3(statistics.mean(recalls)) if recalls else None,
        "mrr10": _r3(statistics.mean(mrrs)) if mrrs else None,
        "p50_ms": int(percentile(lat, 0.50)) if lat else None,
        "p95_ms": int(percentile(lat, 0.95)) if lat else None,
        "answerable": len(answerable),
        "unanswerable": len(unanswerable),
    }


def compute_run_metrics(items: Iterable[dict[str, Any]],
                        questions: dict[int, dict]) -> dict:
    """按 mode 分组汇总，返回 {by_mode: {...}, generated_at}。"""
    grouped: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        grouped[item["mode"]].append(item)

    by_mode = {mode: compute_mode_metrics(rows, questions)
               for mode, rows in sorted(grouped.items())}
    return {"by_mode": by_mode}


def cohen_kappa(a: list[str], b: list[str]) -> float:
    """自动判定与人工判定的一致性（Kappa）。"""
    if len(a) != len(b) or not a:
        return 0.0
    labels = sorted(set(a) | set(b))
    n = len(a)
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    pe = sum((a.count(l) / n) * (b.count(l) / n) for l in labels)
    return 1.0 if pe >= 1 else round((po - pe) / (1 - pe), 3)
