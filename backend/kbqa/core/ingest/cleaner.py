"""文本清洗：统一换行、去零宽字符、压缩空白，但不碰代码缩进。"""

from __future__ import annotations

import re

_ZERO_WIDTH = re.compile(r"[\u200b-\u200f\u202a-\u202e\ufeff]")
_MULTI_BLANK = re.compile(r"\n{3,}")


def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def clean_text(text: str) -> str:
    text = normalize_newlines(text)
    text = _ZERO_WIDTH.sub("", text)
    text = _MULTI_BLANK.sub("\n\n", text)
    return text.strip()


def is_blank(text: str) -> bool:
    return not text.strip()
