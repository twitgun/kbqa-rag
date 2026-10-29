"""解析器协议与注册表。新增格式 = 实现 Protocol + register。"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from kbqa.core.ingest.types import ParsedDocument, UnsupportedFormatError


@runtime_checkable
class DocumentParser(Protocol):
    extensions: tuple[str, ...]

    def parse(self, path: Path) -> ParsedDocument: ...


class ParserRegistry:
    _parsers: dict[str, DocumentParser] = {}

    @classmethod
    def register(cls, parser: DocumentParser) -> None:
        for ext in parser.extensions:
            cls._parsers[ext.lower().lstrip(".")] = parser

    @classmethod
    def get(cls, ext: str) -> DocumentParser:
        key = ext.lower().lstrip(".")
        if key not in cls._parsers:
            raise UnsupportedFormatError(f"不支持的格式：.{key}")
        return cls._parsers[key]

    @classmethod
    def supported(cls) -> list[str]:
        return sorted(cls._parsers)
