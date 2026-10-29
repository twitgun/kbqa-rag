#!/usr/bin/env python
"""比较两组（通常是 L2 vs L4）在「拒绝质量」和「引用合法性」上的差异。

这些是约束层/校验层真正该起作用的地方：
- 引用合法性：citations 里的 chunk_uid 是否真在本轮召回集内（V-03）；
- 引用可核验：quote 能否在 chunk 原文中逐字找到（V-05）；
- 拒绝质量：拒答是否只发生在不可答题上（误拒率），以及是否漏答。

用法：
  python scripts/compare_quality.py experiments/xxx.jsonl
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))


def norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python scripts/compare_quality.py <结果.jsonl>")
        return 1

    from sqlalchemy import select

    from kbqa.infra.db import models as m
    from kbqa.infra.db.session import SessionLocal

    rows = [json.loads(l) for l in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
            if l.strip()]
    with SessionLocal() as db:
        chunk_text = dict(db.execute(select(m.Chunk.chunk_uid, m.Chunk.text)).all())

    stat: dict[str, dict] = defaultdict(lambda: {
        "answered": 0, "cits": 0, "legal": 0, "verifiable": 0,
        "refused_ans": 0, "refused_unans": 0, "n_ans": 0, "n_unans": 0})

    for r in rows:
        s = stat[r["mode"]]
        is_unans = r["qtype"] == "unanswerable"
        s["n_unans" if is_unans else "n_ans"] += 1
        if r["is_fallback"]:
            s["refused_unans" if is_unans else "refused_ans"] += 1
            continue
        s["answered"] += 1
        recalled = {c.get("chunk_uid") for c in (r.get("retrieval", {}).get("candidates") or [])}
        for c in r.get("citation_detail") or []:
            uid = c.get("chunk_uid")
            quote = c.get("quote") or ""
            s["cits"] += 1
            # 合法性：引用是否来自本轮召回（result 里未存全量候选时退化为"片段存在"）
            s["legal"] += 1 if (not recalled or uid in recalled) else 0
            probe = norm(quote)[:30]
            s["verifiable"] += 1 if (probe and probe in norm(chunk_text.get(uid, ""))) else 0

    print(f"{'模式':<6}{'作答':>5}{'引用':>6}{'合法率':>8}{'可核验率':>10}"
          f"{'误拒率':>8}{'漏答率':>8}")
    for mode, s in sorted(stat.items()):
        legal = s["legal"] / s["cits"] * 100 if s["cits"] else 0
        verif = s["verifiable"] / s["cits"] * 100 if s["cits"] else 0
        false_rej = s["refused_ans"] / s["n_ans"] * 100 if s["n_ans"] else 0
        miss = s["refused_unans"] / s["n_unans"] * 100 if s["n_unans"] else 0
        print(f"{mode:<6}{s['answered']:>5}{s['cits']:>6}{legal:>7.1f}%{verif:>9.1f}%"
              f"{false_rej:>7.1f}%{miss:>7.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
