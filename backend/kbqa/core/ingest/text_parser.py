"""纯文本解析：按空行分段。"""

from __future__ import annotations

import re
from pathlib import Path

from kbqa.core.ingest.cleaner import clean_text
from kbqa.core.ingest.types import Block, EmptyDocumentError, ParsedDocument


class TextParser:
    extensions = ("txt",)

    def parse(self, path: Path) -> ParsedDocument:
        raw = path.read_bytes()
        for enc in ("utf-8", "utf-8-sig", "gbk"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = raw.decode("utf-8", errors="replace")

        blocks: list[Block] = []
        parts: list[str] = []
        cursor = 0
        for i, chunk in enumerate(re.split(r"\n\s*\n", text.replace("\r\n", "\n"))):
            seg = clean_text(chunk)
            if not seg:
                continue
            if parts:
                cursor += 2
            blocks.append(Block("paragraph", seg, cursor, cursor + len(seg), para_index=i))
            parts.append(seg)
            cursor += len(seg)

        plain = "\n\n".join(parts)
        if len(plain.strip()) < 20:
            raise EmptyDocumentError(f"文档内容为空：{path.name}")
        return ParsedDocument(blocks=blocks, plain_text=plain, doc_meta={"headings": 0})
