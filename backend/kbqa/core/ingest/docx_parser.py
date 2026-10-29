"""Word 解析：按 body 顺序遍历段落与表格，标题按样式名识别。"""

from __future__ import annotations

import re
from pathlib import Path

from docx import Document as load_docx
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from kbqa.core.ingest.cleaner import clean_text
from kbqa.core.ingest.types import Block, EmptyDocumentError, ParsedDocument, ParseError

_HEADING = re.compile(r"^(?:Heading|标题)\s*(\d)$", re.I)


def _heading_level(style_name: str | None) -> int | None:
    if not style_name:
        return None
    m = _HEADING.match(style_name.strip())
    return int(m.group(1)) if m else None


def _table_to_md(table: Table) -> str:
    rows: list[list[str]] = []
    for row in table.rows:
        cells = [c.text.strip().replace("|", "\\|").replace("\n", " ") for c in row.cells]
        rows.append(cells)
    rows = [r for r in rows if any(r)]
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    head, body = rows[0], rows[1:]
    lines = ["| " + " | ".join(head) + " |", "| " + " | ".join(["---"] * width) + " |"]
    lines += ["| " + " | ".join(r) + " |" for r in body]
    return "\n".join(lines)


class DocxParser:
    extensions = ("docx",)

    def parse(self, path: Path) -> ParsedDocument:
        try:
            doc = load_docx(str(path))
        except Exception as exc:  # noqa: BLE001
            raise ParseError(f"docx 打开失败：{exc}") from exc

        blocks: list[Block] = []
        parts: list[str] = []
        cursor = 0
        idx = 0

        for child in doc.element.body.iterchildren():
            if child.tag == qn("w:p"):
                para = Paragraph(child, doc)
                text = clean_text(para.text)
                if not text:
                    continue
                level = _heading_level(para.style.name if para.style else None)
                kind = "heading" if level else "paragraph"
            elif child.tag == qn("w:tbl"):
                text = _table_to_md(Table(child, doc))
                if not text:
                    continue
                level, kind = None, "table"
            else:
                continue

            if parts:
                cursor += 2
            blocks.append(Block(kind, text, cursor, cursor + len(text),  # type: ignore[arg-type]
                                level=level, para_index=idx))
            parts.append(text)
            cursor += len(text)
            idx += 1

        plain = "\n\n".join(parts)
        if len(plain.strip()) < 20:
            raise EmptyDocumentError(f"文档内容为空：{path.name}")
        return ParsedDocument(blocks=blocks, plain_text=plain,
                              doc_meta={"headings": sum(1 for b in blocks if b.kind == "heading"),
                                        "tables": sum(1 for b in blocks if b.kind == "table")})
