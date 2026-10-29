"""句子切分：保留句末标点，返回 (句子, 起, 止)。"""

from __future__ import annotations

import re

_DELIM = re.compile(r"(?<=[。！？；!?;\n])")


def split_sentences_with_offsets(text: str) -> list[tuple[str, int, int]]:
    out: list[tuple[str, int, int]] = []
    cursor = 0
    for part in _DELIM.split(text):
        if not part:
            continue
        start = cursor
        cursor += len(part)
        out.append((part, start, cursor))
    return out or [(text, 0, len(text))]


def split_sentences(text: str) -> list[str]:
    return [s for s, _, _ in split_sentences_with_offsets(text)]
