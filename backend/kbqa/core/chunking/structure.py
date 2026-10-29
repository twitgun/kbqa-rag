"""结构感知切分：按标题层级聚块，超长二次切分并保留重叠与前缀。

不变式（见 03_核心机制/01 §1）：
  - char_start/char_end 指向原文区间
  - text 可能带 "【section_path】" 前缀，故 len(text) >= char_len
  - char_len == char_end - char_start（入库时用这个，不是 len(text)）
"""

from __future__ import annotations

from kbqa.core.chunking.base import Chunk, Chunker, ChunkParams, ChunkingError
from kbqa.core.chunking.utils import split_sentences_with_offsets

OVERSIZE_KINDS = {"table", "code"}


class StructureChunker(Chunker):
    def chunk(self, doc, params: ChunkParams) -> list[Chunk]:
        params.validate()
        chunks: list[Chunk] = []
        stack: list[tuple[int, str]] = []
        buf: list = []

        def path_now() -> str:
            return " > ".join(t for _, t in stack) or "正文"

        def emit(text: str, start: int, end: int, path: str, kind: str = "structure",
                 page_no: int | None = None) -> None:
            chunks.append(Chunk(text=text, char_start=start, char_end=end,
                                chunk_index=len(chunks), section_path=path,
                                page_no=page_no, strategy=params.strategy))

        def split_long(text: str, base: int, path: str) -> None:
            pieces = split_sentences_with_offsets(text)
            slice_start = 0
            slice_end = 0
            for _, s_start, s_end in pieces:
                if slice_end > slice_start and (slice_end - slice_start) + (s_end - s_start) > params.target_size:
                    seg = text[slice_start:slice_end]
                    emit(f"【{path}】{seg}", base + slice_start, base + slice_end, path)
                    back = min(params.overlap, len(seg))
                    slice_start = slice_end - back
                slice_end = s_end
            if slice_end > slice_start:
                seg = text[slice_start:slice_end]
                emit(f"【{path}】{seg}", base + slice_start, base + slice_end, path)

        def flush() -> None:
            nonlocal buf
            if not buf:
                return
            path = path_now()
            text = "\n\n".join(b.text for b in buf)
            start, end = buf[0].char_start, buf[-1].char_end

            if len(text) <= params.max_size:
                # 仅当两段在原文中物理相邻（中间只隔一个 "\n\n"）才允许合并；
                # 否则会把中间的标题一起"吃掉"，造成 text 与 char 区间对不上。
                adjacent = bool(chunks) and (start - chunks[-1].char_end) == 2
                if len(text) < params.min_size and adjacent:
                    prev = chunks[-1]
                    prev.text = f"{prev.text}\n\n{text}"
                    prev.char_end = end
                else:
                    emit(text, start, end, path)
            else:
                split_long(text, start, path)
            buf = []

        for block in doc.blocks:
            if block.kind == "heading":
                flush()
                while stack and stack[-1][0] >= (block.level or 7):
                    stack.pop()
                stack.append((block.level or 1, block.text.strip().lstrip("#").strip()))
                continue

            if (block.kind in OVERSIZE_KINDS and params.preserve_table
                    and len(block.text) > params.max_size):
                # 超长代码块/表格：仍按原文切片，避免出现局部 5000+ 字的巨型片段。
                # 不加围栏，保证 text 与 char 区间严格对应。
                flush()
                step = max(1, params.max_size - params.overlap)
                for offset in range(0, len(block.text), step):
                    seg = block.text[offset:offset + params.max_size]
                    if not seg:
                        break
                    emit(seg, block.char_start + offset,
                         block.char_start + offset + len(seg), path_now(),
                         page_no=block.page_no)
                    if offset + params.max_size >= len(block.text):
                        break
                continue

            buf.append(block)
            if sum(len(b.text) + 2 for b in buf) >= params.target_size:
                flush()

        flush()

        if not chunks:
            raise ChunkingError("切分后无片段")
        return chunks
