"""解析与切分的单元测试（不依赖数据库、模型、网络）。"""

from __future__ import annotations

import pytest

from kbqa.core.chunking import ChunkParams, get_chunker
from kbqa.core.chunking.fixed import FixedWindowChunker
from kbqa.core.chunking.utils import split_sentences_with_offsets
from kbqa.core.ingest.base import ParserRegistry
from kbqa.core.ingest.types import EmptyDocumentError, ParsedDocument, Block

SAMPLE = """# 一级标题

这是第一段正文，用于测试切分行为。它应当被完整保留。[1]

## 二级标题

第二段内容，包含 `inline code` 与一个列表：

- 项一
- 项二

```python
def hello():
    print("hi")
```

### 三级标题

第三段。这里再写一些内容，让片段长度足够触发切分逻辑。
"""


def _make_doc(text: str) -> ParsedDocument:
    blocks: list[Block] = []
    parts: list[str] = []
    cursor = 0
    for i, para in enumerate(text.split("\n\n")):
        para = para.strip()
        if not para:
            continue
        if parts:
            cursor += 2
        kind = "heading" if para.startswith("#") else "paragraph"
        level = len(para) - len(para.lstrip("#")) if kind == "heading" else None
        blocks.append(Block(kind, para, cursor, cursor + len(para), level=level, para_index=i))
        parts.append(para)
        cursor += len(para)
    return ParsedDocument(blocks=blocks, plain_text="\n\n".join(parts))


def test_markdown_parser_offsets(tmp_path):
    p = tmp_path / "a.md"
    p.write_text(SAMPLE, encoding="utf-8")
    doc = ParserRegistry.get("md").parse(p)

    assert doc.blocks, "应解析出块"
    for b in doc.blocks:
        assert doc.plain_text[b.char_start:b.char_end] == b.text, b.text[:30]


def test_markdown_parser_counts(tmp_path):
    p = tmp_path / "a.md"
    p.write_text(SAMPLE, encoding="utf-8")
    doc = ParserRegistry.get("md").parse(p)

    assert doc.doc_meta["headings"] == 3
    assert doc.doc_meta["code_blocks"] == 1


def test_markdown_empty_raises(tmp_path):
    p = tmp_path / "empty.md"
    p.write_text("# 标题\n\n短", encoding="utf-8")
    with pytest.raises(EmptyDocumentError):
        ParserRegistry.get("md").parse(p)


def test_structure_chunker_offsets(tmp_path):
    p = tmp_path / "a.md"
    p.write_text(SAMPLE, encoding="utf-8")
    doc = ParserRegistry.get("md").parse(p)

    params = ChunkParams(target_size=80, max_size=160, min_size=20, overlap=20)
    chunks = get_chunker("structure").chunk(doc, params)

    assert len(chunks) > 1
    for c in chunks:
        original = doc.plain_text[c.char_start:c.char_end]
        # 要么是原文，要么是 【path】+原文
        assert c.text == original or c.text.endswith(original)
        assert c.char_len == c.char_end - c.char_start
        assert c.char_len > 0


def test_structure_chunker_section_path(tmp_path):
    p = tmp_path / "a.md"
    p.write_text(SAMPLE, encoding="utf-8")
    doc = ParserRegistry.get("md").parse(p)
    chunks = get_chunker("structure").chunk(
        doc, ChunkParams(target_size=60, max_size=120, min_size=10, overlap=10))

    assert any("一级标题" in c.section_path for c in chunks)


def test_fixed_window_overlap_and_coverage():
    doc = _make_doc("字" * 2000)
    chunks = FixedWindowChunker().chunk(
        doc, ChunkParams(strategy="fixed", target_size=800, max_size=1600,
                         min_size=0, overlap=120))

    assert chunks[0].char_start == 0
    assert chunks[-1].char_end == 2000
    assert chunks[0].text[-120:] == chunks[1].text[:120]


def test_param_validation():
    with pytest.raises(ValueError):
        ChunkParams(target_size=800, overlap=500).validate()
    with pytest.raises(ValueError):
        ChunkParams(target_size=800, max_size=500).validate()


def test_split_sentences_offsets():
    text = "第一句。第二句！第三句？"
    parts = split_sentences_with_offsets(text)
    assert len(parts) == 3
    for s, a, b in parts:
        assert text[a:b] == s
