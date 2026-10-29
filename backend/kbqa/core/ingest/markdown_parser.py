"""Markdown 解析：用 markdown-it 的 token.map 取行区间，保留原文与精确偏移。"""

from __future__ import annotations

from pathlib import Path

from markdown_it import MarkdownIt

from kbqa.core.ingest.cleaner import clean_text
from kbqa.core.ingest.types import Block, EmptyDocumentError, ParsedDocument, ParseError

# token.type -> Block.kind
_KIND = {
    "heading_open": "heading",
    "fence": "code",
    "code_block": "code",
    "table_open": "table",
    "blockquote_open": "quote",
    "bullet_list_open": "list",
    "ordered_list_open": "list",
    "paragraph_open": "paragraph",
    "html_block": "paragraph",
}


class MarkdownParser:
    extensions = ("md", "markdown")

    def __init__(self) -> None:
        self._md = MarkdownIt("commonmark").enable("table").enable("strikethrough")

    def parse(self, path: Path) -> ParsedDocument:
        raw = path.read_text(encoding="utf-8", errors="replace")
        raw = raw.replace("\r\n", "\n")
        lines = raw.split("\n")

        try:
            tokens = self._md.parse(raw)
        except Exception as exc:  # noqa: BLE001
            raise ParseError(f"Markdown 解析失败：{exc}") from exc

        blocks: list[Block] = []
        parts: list[str] = []
        cursor = 0
        para_index = 0

        for tok in tokens:
            if tok.level != 0 or tok.map is None:
                continue
            start_line, end_line = tok.map
            text = clean_text("\n".join(lines[start_line:end_line]))
            if not text:
                continue

            kind = _KIND.get(tok.type)
            if kind is None:
                continue

            level = None
            if kind == "heading":
                try:
                    level = int(tok.tag[1])
                except (IndexError, ValueError):
                    level = 1

            meta: dict = {}
            if kind == "code" and tok.info:
                meta["lang"] = tok.info.strip().split()[0]

            if parts:
                cursor += 2  # 块间 "\n\n"
            block = Block(kind=kind, text=text, char_start=cursor,
                          char_end=cursor + len(text), level=level,
                          para_index=para_index, meta=meta)
            blocks.append(block)
            parts.append(text)
            cursor += len(text)
            para_index += 1

        plain = "\n\n".join(parts)
        if len(plain.strip()) < 20:
            raise EmptyDocumentError(f"文档内容为空或过短：{path.name}")

        return ParsedDocument(
            blocks=blocks,
            plain_text=plain,
            doc_meta={
                "headings": sum(1 for b in blocks if b.kind == "heading"),
                "tables": sum(1 for b in blocks if b.kind == "table"),
                "code_blocks": sum(1 for b in blocks if b.kind == "code"),
            },
        )
