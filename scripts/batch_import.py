#!/usr/bin/env python
"""把 data/corpus 下的文档逐篇上传并等待索引完成。

串行执行：GPU 只有一个，并发上传只会让任务排队、日志难读。

用法：
  python scripts/batch_import.py
  python scripts/batch_import.py --base http://127.0.0.1:8000 --delay 0.2
  python scripts/batch_import.py --dry-run          # 只列出将上传的文件
  python scripts/batch_import.py --skip-existing    # 跳过已 ready 的同名文档

前置：后端已启动、健康检查 ok、数据库已建表。
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "data" / "corpus"


def log(msg: str) -> None:
    print(msg, flush=True)


def api(client: httpx.Client, base: str, path: str) -> dict:
    r = client.get(f"{base}/api/v1{path}")
    r.raise_for_status()
    body = r.json()
    if body.get("code") != 0:
        raise RuntimeError(f"{path} -> {body.get('code')} {body.get('message')}")
    return body.get("data") or {}


def existing_titles(client: httpx.Client, base: str) -> set[str]:
    titles: set[str] = set()
    page = 1
    while True:
        data = api(client, base, f"/documents?page={page}&size=100")
        items = data.get("items") or []
        titles.update(i["title"] for i in items)
        if page >= data.get("total_pages", 1):
            break
        page += 1
    return titles


def wait_job(client: httpx.Client, base: str, job_id: int, timeout: int = 300) -> dict:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        job = api(client, base, f"/jobs/{job_id}")
        status = job.get("status")
        msg = job.get("message") or ""
        if msg != last:
            log(f"      {job.get('progress', 0):>3}% {msg}")
            last = msg
        if status in ("succeeded", "failed", "canceled"):
            return job
        time.sleep(1)
    return {"status": "timeout", "error_detail": f"等待超过 {timeout}s"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--dir", default=str(CORPUS))
    ap.add_argument("--delay", type=float, default=0.2)
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--skip-existing", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    files = sorted(Path(args.dir).glob("*.md"))
    if not files:
        log(f"没有找到文档：{args.dir}")
        return 1

    log(f"待上传 {len(files)} 篇 -> {args.base}")
    if args.dry_run:
        for i, f in enumerate(files, 1):
            log(f"  {i:02d} {f.name} ({f.stat().st_size} B)")
        return 0

    ok, dup, fail, skipped = 0, 0, 0, 0
    failures: list[tuple[str, str]] = []

    with httpx.Client(timeout=120) as client:
        try:
            health = api(client, args.base, "/system/health")
            log(f"健康检查：{health.get('status')}")
        except Exception as e:
            log(f"健康检查失败，后端可能未启动：{e}")
            return 2

        titles = existing_titles(client, args.base) if args.skip_existing else set()

        for i, f in enumerate(files, 1):
            title = f.stem.split("_", 1)[1] if "_" in f.stem else f.stem
            if args.skip_existing and title in titles:
                log(f"[{i}/{len(files)}] 跳过（已存在） {f.name}")
                skipped += 1
                continue

            log(f"[{i}/{len(files)}] 上传 {f.name}")
            try:
                with f.open("rb") as fh:
                    r = client.post(
                        f"{args.base}/api/v1/documents/upload",
                        files={"file": (f.name, fh, "text/markdown")},
                        data={"auto_index": "true"},
                    )
                body = r.json()
                if body.get("code") != 0:
                    log(f"      失败：{body.get('code')} {body.get('message')}")
                    failures.append((f.name, body.get("message", "")))
                    fail += 1
                    continue

                data = body["data"]
                if data.get("is_duplicate"):
                    log("      已存在，跳过索引")
                    dup += 1
                    continue

                job_id = data.get("job_id")
                if job_id is None:
                    ok += 1
                    continue

                job = wait_job(client, args.base, job_id, args.timeout)
                if job.get("status") == "succeeded":
                    ok += 1
                    log("      done")
                else:
                    fail += 1
                    detail = job.get("error_detail") or job.get("status")
                    log(f"      失败：{detail}")
                    failures.append((f.name, str(detail)))
            except Exception as e:
                fail += 1
                failures.append((f.name, str(e)))
                log(f"      异常：{e}")

            time.sleep(args.delay)

    log("\n===== 汇总 =====")
    log(f"成功 {ok} / 重复 {dup} / 跳过 {skipped} / 失败 {fail} / 共 {len(files)}")
    if failures:
        log("失败清单：")
        for name, why in failures:
            log(f"  - {name}: {why}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
