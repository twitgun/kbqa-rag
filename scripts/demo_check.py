#!/usr/bin/env python
"""端到端自检：一条命令走完全流程并给出通过/失败。

检查项对应验收清单 F 段：
  1. 服务起来、依赖健康
  2. 上传一份文档并索引成功
  3. 可答题：命中、给答案、带引用
  4. 不可答（远域）：被拦，未调用模型，延迟低
  5. 近域陷阱：有兜底或拒答，不硬答
  6. 检索测试接口：分数与阈值可见

用法：
  python scripts/demo_check.py
  python scripts/demo_check.py --base http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = """# 演示用文档

这是一份用于演示的样例文档，内容超过二十个字符以便通过校验。

## 配置 CORS

在 FastAPI 中使用 CORSMiddleware 配置跨域，allow_origins 指定允许的源。

## 后台任务

用 BackgroundTasks 在返回响应之后执行耗时操作。
"""

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    mark = "通过" if ok else "失败"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""), flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    args = ap.parse_args()
    base = args.base.rstrip("/")
    api = f"{base}/api/v1"

    with httpx.Client(timeout=120) as c:
        # 1 健康
        try:
            h = c.get(f"{api}/system/health").json()["data"]
            check("服务可访问", True, f"status={h.get('status')}")
        except Exception as exc:  # noqa: BLE001
            check("服务可访问", False, str(exc)[:80])
            return 1

        # 2 上传并等索引
        files = {"file": ("demo-sample.md", SAMPLE.encode("utf-8"), "text/markdown")}
        up = c.post(f"{api}/documents/upload", files=files,
                    data={"auto_index": "true"}).json()
        ok = up.get("code") == 0
        check("上传文档", ok, f"doc_id={up.get('data', {}).get('document_id')}")
        doc_id = up.get("data", {}).get("document_id")
        job_id = up.get("data", {}).get("job_id")

        indexed = False
        if job_id:
            for _ in range(60):
                job = c.get(f"{api}/jobs/{job_id}").json()["data"]
                if job["status"] in ("succeeded", "failed", "canceled"):
                    indexed = job["status"] == "succeeded"
                    check("索引完成", indexed, f"status={job['status']}")
                    break
                time.sleep(0.5)

        # 3 可答
        r = c.post(f"{api}/chat/ask", json={"question": "怎么配置 CORS？"}).json()["data"]
        answered = r["answer_status"] == "ok" and r["citations"]
        check("可答题给出带引用的答案", bool(answered),
              f"status={r['answer_status']} 引用={len(r['citations'])} {r['latency_ms']}ms")

        # 4 远域
        r2 = c.post(f"{api}/chat/ask", json={"question": "红烧肉怎么做？"}).json()["data"]
        blocked = r2["is_fallback"] and r2["fallback_reason"] == "insufficient_evidence"
        fast = r2["latency_ms"] < 1500
        check("远域问题被阈值拦住", blocked and fast,
              f"{r2['fallback_reason']} {r2['latency_ms']}ms max={r2['retrieval']['max_score']}")

        # 5 近域陷阱
        r3 = c.post(f"{api}/chat/ask", json={"question": "FastAPI 支持 HTTP/3 吗？"}).json()["data"]
        safe = r3["is_fallback"] or "未" in (r3["answer"] or "")[:40]
        check("近域陷阱未硬答", bool(safe),
              f"status={r3['answer_status']} {r3['fallback_reason'] or ''}")

        # 6 检索测试
        s = c.post(f"{api}/retrieval/search", json={"query": "后台任务", "top_k": 5}).json()["data"]
        check("检索测试可展示分数", bool(s["candidates"]),
              f"max={s['debug']['max_score']} tau={s['debug']['tau']}")

        # 清理
        if doc_id:
            c.delete(f"{api}/documents/{doc_id}")

    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n预演结果：{passed}/{len(results)} 通过")
    if passed < len(results):
        print("有失败项，请先修复。")
        return 1
    print("全部通过，可以用于现场演示。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
