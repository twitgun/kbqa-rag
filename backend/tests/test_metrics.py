"""评测指标计算：口径必须与 00/05 指标定义一致。"""

from __future__ import annotations

import pytest

from kbqa.core.evaluation import (
    cohen_kappa,
    compute_mode_metrics,
    compute_run_metrics,
    mrr_at_k,
    percentile,
    recall_at_k,
)

QUESTIONS = {
    1: {"qtype": "answerable"},
    2: {"qtype": "answerable"},
    3: {"qtype": "unanswerable"},
    4: {"qtype": "unanswerable"},
}


def _item(qid, mode, *, fallback=False, verdict=None, halluc=False, faith=None,
          recall=None, mrr=None, ms=1000):
    return {"question_id": qid, "mode": mode, "is_fallback": fallback,
            "judge": {"verdict": verdict, "hallucination": halluc, "faithfulness": faith}
            if verdict or halluc or faith is not None else None,
            "recall5": recall, "mrr10": mrr, "latency_ms": ms}


def test_recall_and_mrr():
    assert recall_at_k(["a", "b"], ["a", "x"]) == 0.5
    assert recall_at_k(["a"], ["a"]) == 1.0
    assert recall_at_k([], ["a"]) is None
    assert mrr_at_k(["b"], ["a", "b"]) == 0.5
    assert mrr_at_k(["z"], ["a"]) is None


def test_percentile_nearest_rank():
    values = list(range(1, 101))
    assert percentile(values, 0.5) == pytest.approx(50.5)
    assert percentile(values, 0.95) == pytest.approx(95.05)
    assert percentile([], 0.5) == 0.0


def test_accuracy_and_partial():
    items = [
        _item(1, "L4", verdict="正确", faith=1.0, recall=1.0, mrr=1.0),
        _item(2, "L4", verdict="部分正确", faith=0.5, recall=0.5, mrr=0.5),
        _item(3, "L4", fallback=True),
        _item(4, "L4", fallback=True),
    ]
    m = compute_mode_metrics(items, QUESTIONS)

    assert m["accuracy"] == 0.5
    assert m["partial"] == 0.5
    assert m["error"] == 0.0
    assert m["abstention_accuracy"] == 1.0     # 两道无答案题都拒答
    assert m["false_abstention"] == 0.0
    assert m["recall5"] == 0.75
    assert m["faithfulness"] == 0.75


def test_false_abstention_counted():
    items = [
        _item(1, "L4", fallback=True),          # 有答案题被拒 → 误拒
        _item(2, "L4", verdict="正确", faith=1.0),
        _item(3, "L4", verdict="错误", halluc=True, faith=0.0),  # 无答案题却作答
        _item(4, "L4", fallback=True),
    ]
    m = compute_mode_metrics(items, QUESTIONS)

    assert m["false_abstention"] == 0.5
    assert m["abstention_accuracy"] == 0.5
    assert m["hallucination_rate"] == 0.25     # 分母是全部题


def test_run_metrics_groups_by_mode():
    items = [
        _item(1, "L1", verdict="正确", faith=1.0),
        _item(2, "L1", verdict="错误"),
        _item(1, "L4", verdict="正确", faith=1.0),
        _item(2, "L4", fallback=True),
    ]
    r = compute_run_metrics(items, QUESTIONS)
    assert set(r["by_mode"]) == {"L1", "L4"}
    assert r["by_mode"]["L1"]["accuracy"] == 0.5
    assert r["by_mode"]["L4"]["false_abstention"] == 0.5


def test_kappa():
    assert cohen_kappa(["正确", "错误"], ["正确", "错误"]) == 1.0
    assert cohen_kappa(["正确", "正确"], ["错误", "错误"]) == 0.0
    assert cohen_kappa([], []) == 0.0
