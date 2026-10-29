#!/usr/bin/env python
"""下载向量模型（带重试与断点续传）。

hf-mirror 对 Xet 存储不代理（会 401），必须关掉 XET 走普通 HTTP。
大文件下载慢是常态：本脚本失败后自动重试，已下载的分片会续传。

用法：
  python scripts/fetch_model.py --repo BAAI/bge-m3
  python scripts/fetch_model.py --repo BAAI/bge-m3 --retries 50
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="BAAI/bge-m3")
    ap.add_argument("--local-dir", default="")
    ap.add_argument("--retries", type=int, default=30)
    ap.add_argument("--workers", type=int, default=1)
    args = ap.parse_args()

    # 关键环境变量：镜像 + 禁用 Xet
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    os.environ["HF_HUB_DISABLE_XET"] = "1"
    os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "0"

    from huggingface_hub import snapshot_download

    local_dir = Path(args.local_dir) if args.local_dir else (
        ROOT / "runtime" / "models" / args.repo.split("/")[-1])

    allow = ["*.json", "*.txt", "*.safetensors", "*.model", "sentencepiece*", "spm*"]
    ignore = ["onnx/*", "*.onnx", "*.bin", "imgs/*", "*.pdf", "*.md"]

    for attempt in range(1, args.retries + 1):
        try:
            t0 = time.time()
            path = snapshot_download(
                repo_id=args.repo, local_dir=str(local_dir),
                allow_patterns=allow, ignore_patterns=ignore,
                max_workers=args.workers,
            )
            total_mb = sum(f.stat().st_size for f in Path(path).rglob("*") if f.is_file()) / 1024**2
            print(f"[OK] {args.repo} -> {path}  ({total_mb:.0f} MB, {time.time()-t0:.0f}s)")
            return 0
        except Exception as exc:  # noqa: BLE001
            done = sum(f.stat().st_size for f in local_dir.rglob("*") if f.is_file()) / 1024**2
            print(f"[{attempt}/{args.retries}] 失败：{type(exc).__name__}: {str(exc)[:160]} "
                  f"（已下载 {done:.0f} MB，5s 后续传）", flush=True)
            time.sleep(5)
    print("[FAIL] 重试次数用尽")
    return 1


if __name__ == "__main__":
    sys.exit(main())
