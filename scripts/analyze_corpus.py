#!/usr/bin/env python
"""语料体检：对 data/corpus 逐篇跑解析 + 切分，输出统计与不变式校验。

用途：
  - W2 验收（解析器/切分器是否正确）
  - W3 前确认片段规模，校准容量估算
  - 改切分参数后快速看影响

用法：
  python scripts/analyze_corpus.py
  python scripts/analyze_corpus.py --target-size 600 --overlap 100
  python scripts/analyze_corpus.py --strategy fixed
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from kbqa.core.chunking import ChunkParams, get_chunker  # noqa: E402
from kbqa.core.ingest.base import ParserRegistry  # noqa: E402
from kbqa.core.ingest.types import ParseError  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(ROOT / "data" / "corpus"))
    ap.add_argument("--strategy", default="structure", choices=["structure", "fixed"])
    ap.add_argument("--target-size", type=int, default=800)
    ap.add_argument("--max-size", type=int, default=1500)
    ap.add_argument("--min-size", type=int, default=120)
    ap.add_argument("--overlap", type=int, default=120)
    ap.add_argument("--json-out", default="")
    args = ap.parse_args()

    params = ChunkParams(strategy=args.strategy, target_size=args.target_size,
                         max_size=args.max_size, min_size=args.min_size,
                         overlap=args.overlap)
    params.validate()
    chunker = get_chunker(params.strategy)
    parser = ParserRegistry.get("md")

    files = sorted(Path(args.dir).glob("*.md"))
    if not files:
        print(f"没有文档：{args.dir}")
        return 1

    docs, chunks, errors = [], [], []
    violations = 0
    prefixed = 0

    for f in files:
        try:
            doc = parser.parse(f)
        except ParseError as exc:
            errors.append((f.name, str(exc)))
            continue

        cs = chunker.chunk(doc, params)
        docs.append({"file": f.name, "chars": doc.char_count,
                     "blocks": len(doc.blocks), "chunks": len(cs),
                     **doc.doc_meta})

        for c in cs:
            original = doc.plain_text[c.char_start:c.char_end]
            ok = c.text == original or c.text.endswith(original)
            ok = ok and c.char_len == c.char_end - c.char_start and c.char_len > 0
            if not ok:
                violations += 1
            if c.text != original:
                prefixed += 1
        chunks.extend(cs)

    lengths = [c.char_len for c in chunks]
    stats = {
        "files": len(docs),
        "failed": len(errors),
        "total_chars": sum(d["chars"] for d in docs),
        "chunks": len(chunks),
        "prefixed_chunks": prefixed,
        "invariant_violations": violations,
        "len_min": min(lengths) if lengths else 0,
        "len_median": int(statistics.median(lengths)) if lengths else 0,
        "len_mean": int(statistics.mean(lengths)) if lengths else 0,
        "len_max": max(lengths) if lengths else 0,
        "over_max_size": sum(1 for n in lengths if n > params.max_size),
        "sections": len({c.section_path for c in chunks}),
    }

    print("=== 语料体检 ===")
    for k, v in stats.items():
        print(f"{k:>20}: {v}")
    if errors:
        print("\n解析失败：")
        for name, why in errors[:10]:
            print(f"  - {name}: {why}")

    print("\n前 8 篇：")
    for d in docs[:8]:
        print(f"  {d['file'][:44]:46s} {d['chars']:>6} 字  {d['chunks']:>3} 片  "
              f"h={d.get('headings', 0)} code={d.get('code_blocks', 0)}")

    if args.json_out:
        Path(args.json_out).write_text(json.dumps({"stats": stats, "docs": docs},
                                                  ensure_ascii=False, indent=2),
                                       encoding="utf-8")
        print(f"\nJSON -> {args.json_out}")

    return 0 if violations == 0 and not errors else 1


if __name__ == "__main__":
    sys.exit(main())
