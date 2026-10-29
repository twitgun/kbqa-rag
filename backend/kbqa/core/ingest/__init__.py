"""解析器注册。新增格式只需实现 DocumentParser 并在此注册。"""

from __future__ import annotations

from kbqa.core.ingest.base import ParserRegistry
from kbqa.core.ingest.docx_parser import DocxParser
from kbqa.core.ingest.markdown_parser import MarkdownParser
from kbqa.core.ingest.pdf_parser import PdfParser
from kbqa.core.ingest.text_parser import TextParser
from kbqa.core.ingest.xlsx_parser import XlsxParser

_registered = False


def register_default_parsers() -> None:
    global _registered
    if _registered:
        return
    for parser in (MarkdownParser(), DocxParser(), PdfParser(), TextParser(), XlsxParser()):
        ParserRegistry.register(parser)
    _registered = True


register_default_parsers()

__all__ = ["ParserRegistry", "register_default_parsers"]
