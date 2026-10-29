"""固定窗口切分（对照基线）。"""

from __future__ import annotations

from kbqa.core.chunking.base import Chunk, Chunker, ChunkParams


class FixedWindowChunker(Chunker):
    def chunk(self, doc, params: ChunkParams) -> list[Chunk]:
        params.validate()
        text = doc.plain_text
        size, overlap = params.target_size, params.overlap
        step = max(1, size - overlap)
        out: list[Chunk] = []
        i = 0
        while i < len(text):
            seg = text[i:i + size]
            out.append(Chunk(text=seg, char_start=i, char_end=i + len(seg),
                             chunk_index=len(out), section_path="正文",
                             strategy="fixed"))
            if i + size >= len(text):
                break
            i += step
        return out
