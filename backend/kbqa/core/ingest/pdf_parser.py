"""PDF 解析：pdfplumber 逐页取文本，记录 page_map 供引用定位。"""

from __future__ import annotations

import re
from pathlib import Path

import pdfplumber

from kbqa.core.ingest.cleaner import clean_text
from kbqa.core.ingest.types import Block, EmptyDocumentError, PageSpan, ParsedDocument, ParseError

_SENT_END = ("。", "！", "？", ".", "!", "?", "：", ":")


def _merge_broken_lines(lines: list[str]) -> list[str]:
    out: list[str] = []
    for line in lines:
        if out and not out[-1].endswith(_SENT_END) and not line.startswith((" ", "\t", "-", "*", "|", "#")):
            out[-1] += line
        else:
            out.append(line)
    return out


class PdfParser:
    extensions = ("pdf",)

    def parse(self, path: Path) -> ParsedDocument:
        blocks: list[Block] = []
        page_map: list[PageSpan] = []
        parts: list[str] = []
        cursor = 0
        idx = 0

        try:
            with pdfplumber.open(str(path)) as pdf:
                for page_no, page in enumerate(pdf.pages, 1):
                    text = page.extract_text() or ""
                    lines = _merge_broken_lines([ln for ln in text.split("\n") if ln.strip()])
                    page_start = cursor
                    for para in re.split(r"\n\s*\n", "\n".join(lines)):
                        seg = clean_text(para)
                        if not seg:
                            continue
                        if parts:
                            cursor += 2
                        blocks.append(Block("paragraph", seg, cursor, cursor + len(seg),
                                            page_no=page_no, para_index=idx))
                        parts.append(seg)
                        cursor += len(seg)
                        idx += 1
                    page_map.append(PageSpan(page_no, page_start, cursor))
        except Exception as exc:  # noqa: BLE001
            raise ParseError(f"PDF 解析失败：{exc}") from exc

        plain = "\n\n".join(parts)
        if len(plain.strip()) < 20:
            raise EmptyDocumentError(f"未能提取到文本（可能是扫描件）：{path.name}")
        return ParsedDocument(blocks=blocks, plain_text=plain, page_map=page_map,
                              doc_meta={"headings": 0, "pages": len(page_map)})
