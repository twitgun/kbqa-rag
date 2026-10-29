#!/usr/bin/env python
"""整库重建索引（换 embedding 模型、改切分参数后必用）。

向量维度变化时旧向量不可用，必须 --reset-vectors 清空后重建。

用法：
  python scripts/reindex_all.py --reset-vectors
  python scripts/reindex_all.py                # 仅重建，不清空
  python scripts/reindex_all.py --only md      # 只重建某类文档
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import select  # noqa: E402

from kbqa.core.chunking import ChunkParams  # noqa: E402
from kbqa.core.ingest.base import ParserRegistry  # noqa: E402
from kbqa.infra.db import models as m  # noqa: E402
from kbqa.infra.db.session import SessionLocal  # noqa: E402
from kbqa.settings import settings  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset-vectors", action="store_true",
                    help="清空向量库与 BM25（维度变化时必须）")
    ap.add_argument("--only", default="", help="只重建指定扩展名，如 md")
    ap.add_argument("--strategize", default="structure")
    args = ap.parse_args()

    from kbqa.api.deps import get_index_service  # 延迟导入，读取 .env

    svc = get_index_service()
    embedder = svc.embedder
    print(f"embedder: {getattr(embedder, 'name', type(embedder).__name__)} dim={embedder.dim}")

    if args.reset_vectors:
        svc.vector_store.reset()
        svc.vector_store.persist()
        for uid in list(svc.bm25._uids):  # noqa: SLF001
            pass
        svc.bm25.rebuild([])
        svc.bm25.persist()
        print("已清空向量库与 BM25")

    params = ChunkParams(strategy=args.strategize)

    with SessionLocal() as db:
        stmt = select(m.Document)
        if args.only:
            stmt = stmt.where(m.Document.file_ext == args.only)
        docs = list(db.scalars(stmt))
    print(f"待重建 {len(docs)} 篇")

    t0 = time.time()
    ok, fail = 0, 0
    for i, doc in enumerate(docs, 1):
        with SessionLocal() as db:
            d = db.get(m.Document, doc.id)
            try:
                parsed = ParserRegistry.get(d.file_ext).parse(
                    settings.uploads_dir / d.file_path)
                n = svc.index_document(db, d, parsed, params)
                db.commit()
                ok += 1
                if i % 10 == 0 or i == len(docs):
                    print(f"  [{i}/{len(docs)}] {d.title[:30]} -> {n} 片, "
                          f"累计 {time.time() - t0:.0f}s")
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                fail += 1
                print(f"  [{i}/{len(docs)}] 失败 {d.id}: {exc}")

    print(f"\n完成：成功 {ok} / 失败 {fail} / 耗时 {time.time() - t0:.1f}s")
    print(f"向量 {svc.vector_store.count()} 条 / BM25 {svc.bm25.count()} 条")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
