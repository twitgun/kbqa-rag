"""引用编号归一化：编号体系对齐与拒答纠正。"""

from __future__ import annotations

import pytest

from kbqa.core.retrieval.types import Candidate
from kbqa.core.validation.normalize import normalize
from kbqa.core.validation.types import CitationItem, RawAnswer


def _cands(n: int = 5) -> list[Candidate]:
    return [Candidate(chunk_uid=f"d1_c{i:05d}", doc_id=1, text=f"片段{i}内容",
                      doc_title="t", page_no=None, section_path="s",
                      char_start=0, char_end=5) for i in range(1, n + 1)]


def _answer(text: str, ids: list[str], insufficient: bool = False) -> RawAnswer:
    return RawAnswer(answer=text, citations=[CitationItem(chunk_id=i, quote="片段内容")
                                             for i in ids],
                     insufficient=insufficient, confidence=0.8)


def test_context_numbers_rewritten_to_citation_index():
    a = _answer("先用 A [3]，再用 B [5]。", ["d1_c00003", "d1_c00005"])
    out, issues = normalize(a, _cands())
    assert issues == []
    assert out.answer == "先用 A [1]，再用 B [2]。"
    assert [c.chunk_id for c in out.citations] == ["d1_c00003", "d1_c00005"]


def test_multiple_markers_in_one_bracket():
    a = _answer("两者都支持 [2, 4]。", ["d1_c00002", "d1_c00004"])
    out, issues = normalize(a, _cands())
    assert issues == []
    assert out.answer == "两者都支持 [1][2]。"
    assert len(out.citations) == 2


def test_out_of_range_marker_rejected():
    a = _answer("见 [9]。", ["d1_c00009"])
    out, issues = normalize(a, _cands(5))
    assert not out or issues
    assert issues[0].rule == "V-04"
    assert "不存在的片段编号" in issues[0].detail


def test_missing_citation_rejected():
    """标记多于 citations：有标记找不到出处，必须拒。"""
    a = _answer("见 [1][2][3]。", ["d1_c00001", "d1_c00002"])
    _, issues = normalize(a, _cands())
    assert issues and "缺少出处" in issues[0].detail


def test_extra_citation_trimmed():
    """citations 多于标记：多列了没用到的引用，截掉即可，不该拒。"""
    a = _answer("见 [2]。", ["d1_c00002", "d1_c00004"])
    out, issues = normalize(a, _cands())
    assert issues == []
    assert len(out.citations) == 1
    assert out.answer == "见 [1]。"


def test_refusal_with_marker_and_no_citations_becomes_insufficient():
    """模型口头拒答却漏设 insufficient：应纠正为证据不足，而不是判校验失败。"""
    a = _answer("未在知识库中找到相关依据 [3]。建议换一种说法。", [])
    out, issues = normalize(a, _cands())
    assert issues == []
    assert out.insufficient is True
    assert out.citations == []
    assert "[3]" not in out.answer


def test_normal_answer_untouched():
    a = _answer("答案 [1]。", ["d1_c00001"])
    out, issues = normalize(a, _cands())
    assert issues == [] and out.answer == "答案 [1]。"
