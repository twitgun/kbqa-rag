"""RRF、校验规则、兜底的单元测试（零外部依赖）。"""

from __future__ import annotations

import pytest

from kbqa.core.fallback import FallbackHandler
from kbqa.core.retrieval.rrf import rrf_fuse
from kbqa.core.retrieval.types import Candidate
from kbqa.core.validation import RawAnswer, Validator
from kbqa.core.validation.extractor import extract_json
from kbqa.core.validation.types import ParseError


def _cand(uid: str, text: str = "原文内容") -> Candidate:
    return Candidate(chunk_uid=uid, doc_id=1, text=text)


# ---------------------------------------------------------------- RRF
def test_rrf_manual_k0():
    fused = dict(rrf_fuse(["a", "b", "c"], ["c", "b", "a"], k=0))
    assert fused["b"] == pytest.approx(1.0)
    assert fused["a"] == pytest.approx(1 + 1 / 3)


def test_rrf_order_and_tiebreak():
    assert [u for u, _ in rrf_fuse(["a", "b"], ["b"], k=0)] == ["b", "a"]
    # 完全对称时按 uid 字典序，保证可复现
    assert rrf_fuse(["a"], ["b"], k=0) == rrf_fuse(["b"], ["a"], k=0)


def test_rrf_empty_side():
    fused = rrf_fuse(["a", "b"], [], k=60)
    assert [u for u, _ in fused] == ["a", "b"]


def test_rrf_both_boosted():
    fused = dict(rrf_fuse(["a", "b"], ["b", "c"], k=60))
    assert fused["b"] > fused["a"]


# ---------------------------------------------------------------- 提取
def test_extract_clean():
    raw = '{"answer":"x","citations":[],"insufficient":true,"confidence":0.1}'
    assert extract_json(raw)["answer"] == "x"


def test_extract_fenced():
    raw = '```json\n{"answer":"x","citations":[],"insufficient":false,"confidence":0.5}\n```'
    assert extract_json(raw)["confidence"] == 0.5


def test_extract_chatty():
    raw = '好的，答案是：{"answer":"用 CORSMiddleware","citations":[],"insufficient":false,"confidence":0.8} 希望有帮助'
    assert extract_json(raw)["insufficient"] is False


def test_extract_braces_in_string():
    raw = '{"answer":"代码 for i in range(3) { print(i) } 结束","citations":[],"insufficient":false,"confidence":0.7}'
    assert "{" in extract_json(raw)["answer"]


def test_extract_no_json():
    with pytest.raises(ParseError):
        extract_json("完全没有 JSON")


# ---------------------------------------------------------------- 校验
CANDIDATES = [_cand("d1_c00001", "allow_origins 不能设置为 [\"*\"]，当 allow_credentials 为 True 时。")]


def _validate(raw: str, cands=None):
    return Validator().validate(raw, cands or CANDIDATES)


def test_v01_invalid_json():
    r = _validate("not json")
    assert not r.valid and r.issues[0].rule == "V-01"


def test_v02_missing_field():
    r = _validate('{"answer":"x","citations":[]}')
    assert not r.valid and r.issues[0].rule == "V-02"


def test_v03_unknown_chunk():
    raw = '{"answer":"x [1]","citations":[{"chunk_id":"d9_c00001","quote":"原文"}],"insufficient":false,"confidence":0.8}'
    r = _validate(raw)
    assert not r.valid and any(i.rule == "V-03" for i in r.issues)


def test_v04_marker_out_of_range():
    raw = '{"answer":"x [3]","citations":[{"chunk_id":"d1_c00001","quote":"allow_origins"}],"insufficient":false,"confidence":0.8}'
    r = _validate(raw)
    assert not r.valid and any(i.rule == "V-04" for i in r.issues)


def test_v05_no_citation():
    raw = '{"answer":"这是一个包含事实的长答案，说明了配置方法。","citations":[],"insufficient":false,"confidence":0.8}'
    r = _validate(raw)
    assert not r.valid and any(i.rule == "V-05" for i in r.issues)


def test_v05_fake_quote():
    raw = '{"answer":"x [1]","citations":[{"chunk_id":"d1_c00001","quote":"这句话原文里没有"}],"insufficient":false,"confidence":0.8}'
    r = _validate(raw)
    assert not r.valid and any("非原文" in i.detail for i in r.issues)


def test_v06_insufficient_with_conclusion():
    raw = '{"answer":"根据资料，allow_origins 必须显式列出。","citations":[],"insufficient":true,"confidence":0.3}'
    r = _validate(raw)
    assert not r.valid and any(i.rule == "V-06" for i in r.issues)


def test_valid_answer_passes():
    raw = ('{"answer":"不能设为 *，必须显式列出 [1]","citations":[{"chunk_id":"d1_c00001",'
           '"quote":"allow_origins 不能设置为"}],"insufficient":false,"confidence":0.9}')
    r = _validate(raw)
    assert r.valid, r.summary
    assert r.answer is not None


# ---------------------------------------------------------------- 兜底
def test_fallback_insufficient_hides_far_candidates():
    h = FallbackHandler()
    near = [_cand("d1_c00001")]
    r = h.insufficient_evidence(near, max_score=0.05, tau=0.30)
    assert r.nearest == []          # 0.05 < tau*0.5，不应展示
    r2 = h.insufficient_evidence(near, max_score=0.20, tau=0.30)
    assert len(r2.nearest) == 1


def test_fallback_llm_keeps_question():
    r = FallbackHandler().llm_unavailable()
    assert r.keep_question and r.retryable and r.error_code == "E-3002"
    assert "模型服务暂时不可用" in r.answer


def test_fallback_validation_failed():
    from kbqa.core.validation.types import ValidationIssue
    r = FallbackHandler().validation_failed([ValidationIssue("V-03", "x")])
    assert r.error_code == "E-3004" and r.issues == ["V-03:x"]


def test_fallback_never_calls_llm_when_insufficient():
    r = FallbackHandler().insufficient_evidence([], 0.0, 0.30)
    assert r.llm_called is False
