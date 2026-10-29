#!/usr/bin/env python
"""分块 + 断点续传下载单个大文件（适合慢速镜像）。

huggingface_hub 在 hf-mirror 上对大文件偶发卡死；直接用 HTTP Range 更稳。
中断后重跑本脚本会从已下载字节处继续。

用法：
  python scripts/dl_model_chunked.py
  python scripts/dl_model_chunked.py --out runtime/models/bge-m3/pytorch_model.bin
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="https://hf-mirror.com/BAAI/bge-m3/resolve/main/pytorch_model.bin")
    ap.add_argument("--out", default=str(ROOT / "runtime" / "models" / "bge-m3" / "pytorch_model.bin"))
    ap.add_argument("--chunk-mb", type=int, default=8)
    ap.add_argument("--max-retries", type=int, default=50)
    args = ap.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    chunk = args.chunk_mb * 1024 * 1024

    with httpx.Client(timeout=120, follow_redirects=True,
                      headers={"User-Agent": "kbqa-downloader/1.0"}) as client:
        head = client.head(args.url)
        total = int(head.headers.get("content-length", 0))
        if total == 0:
            print("[FAIL] 无法获取文件大小")
            return 1
        print(f"目标 {total/1024**2:.0f} MB -> {out}", flush=True)

        retries = 0
        t0 = time.time()
        while True:
            have = out.stat().st_size if out.exists() else 0
            if have >= total:
                print(f"[OK] 完成 {have/1024**2:.0f} MB，用时 {(time.time()-t0)/60:.1f} 分钟", flush=True)
                return 0
            end = min(have + chunk - 1, total - 1)
            try:
                with client.stream("GET", args.url, headers={"Range": f"bytes={have}-{end}"}) as r:
                    if r.status_code not in (200, 206):
                        raise RuntimeError(f"HTTP {r.status_code}")
                    with out.open("ab") as fh:
                        for data in r.iter_bytes():
                            fh.write(data)
                retries = 0
                speed = (out.stat().st_size / 1024**2) / max(1e-6, time.time() - t0)
                print(f"  {out.stat().st_size/1024**2:7.1f}/{total/1024**2:.0f} MB  "
                      f"{speed:.2f} MB/s", flush=True)
            except Exception as exc:  # noqa: BLE001
                retries += 1
                print(f"  中断（{retries}/{args.max_retries}）：{type(exc).__name__}: {str(exc)[:100]}",
                      flush=True)
                if retries > args.max_retries:
                    print("[FAIL] 重试次数用尽，已下载部分保留，可重跑续传")
                    return 1
                time.sleep(min(30, 3 * retries))


if __name__ == "__main__":
    sys.exit(main())
