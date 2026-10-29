#!/usr/bin/env python
"""检索层性能压测：分段耗时与分位数（NFR-01/02 的检索部分）。

只测检索（不调 LLM），因此结果不受网络与模型服务波动影响。

用法：
  python scripts/bench_retrieval.py
  python scripts/bench_retrieval.py --repeat 3 --json-out data/bench.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

QUERIES = [
    "怎么配置 CORS", "后台任务怎么用", "Depends 依赖注入怎么用",
    "怎么给路由加统一前缀", "请求体怎么用 Pydantic 模型校验",
    "OAuth2 密码流怎么实现", "怎么部署到 Docker 容器", "测试用例怎么写",
    "文件上传怎么处理", "WebSocket 怎么用", "中间件怎么写",
    "路径参数怎么校验", "响应模型怎么定义", "异常处理器怎么加",
    "环境变量怎么配置", "怎么自定义 Swagger 文档",
]


def pct(values: list[int], p: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, int(round((len(ordered) - 1) * p))))
    return ordered[k]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeat", type=int, default=2)
    ap.add_argument("--json-out", default="")
    args = ap.parse_args()

    from kbqa.api.deps import get_retriever

    r = get_retriever()
    print(f"embedder={getattr(r.embedder, 'name', '')} dim={r.embedder.dim} "
          f"reranker={'on' if r.reranker else 'off'}")

    # 预热：避免首次调用把模型加载/线程池初始化算进去
    asyncio.run(r.retrieve("预热查询", enable_rerank=True))

    totals: list[int] = []
    stages: dict[str, list[int]] = {"vector_ms": [], "bm25_ms": [], "fusion_ms": [], "rerank_ms": []}
    t_all = time.perf_counter()

    for _ in range(args.repeat):
        for q in QUERIES:
            t0 = time.perf_counter()
            res = asyncio.run(r.retrieve(q, enable_rerank=True))
            totals.append(int((time.perf_counter() - t0) * 1000))
            for k in stages:
                stages[k].append(res.timing.get(k, 0))

    wall = time.perf_counter() - t_all
    n = len(QUERIES) * args.repeat

    print(f"\n共 {n} 次检索，总耗时 {wall:.1f}s，平均 {sum(totals)/n:.0f}ms")
    print(f"总延迟   P50={pct(totals,0.50)}ms  P95={pct(totals,0.95)}ms  max={max(totals)}ms")
    for k, v in stages.items():
        print(f"  {k:10s} P50={pct(v,0.50):5d}ms  P95={pct(v,0.95):5d}ms  mean={statistics.mean(v):.0f}ms")

    if args.json_out:
        Path(args.json_out).write_text(json.dumps({
            "embedder": getattr(r.embedder, "name", ""), "dim": r.embedder.dim,
            "reranker": bool(r.reranker), "n": n,
            "total": {"p50": pct(totals, 0.50), "p95": pct(totals, 0.95), "max": max(totals)},
            "stages": {k: {"p50": pct(v, 0.50), "p95": pct(v, 0.95)} for k, v in stages.items()},
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON -> {args.json_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
