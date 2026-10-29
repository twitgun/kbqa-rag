"""系统健康检查与统计（API-28 / API-29）。"""

from __future__ import annotations

import shutil
import time

from fastapi import APIRouter

from kbqa.api.response import ok
from kbqa.infra.db import session as db
from kbqa.settings import settings

router = APIRouter(prefix="/system", tags=["system"])

_START = time.time()


def _check_mysql() -> dict:
    t0 = time.perf_counter()
    alive, detail = db.ping()
    return {"name": "mysql", "status": "ok" if alive else "down",
            "latency_ms": int((time.perf_counter() - t0) * 1000), "detail": detail}


def _check_path(name: str, path, kind: str) -> dict:
    exists = path.exists()
    detail = str(path)
    return {"name": name, "status": "ok" if exists else "degraded",
            "latency_ms": 0, "detail": detail if exists else f"缺失：{detail}"}


def _check_deepseek() -> dict:
    configured = bool(settings.deepseek_api_key)
    return {"name": "deepseek", "status": "ok" if configured else "degraded",
            "latency_ms": 0,
            "detail": "已配置 API Key（未做连通性探测）" if configured else "未配置 DEEPSEEK_API_KEY"}


def _check_reranker() -> dict:
    """重排是「可关闭」能力：主动关闭记为 skipped，不计入降级。"""
    model_dir = settings.model_dir / settings.reranker_model
    if not settings.rerank_enabled:
        return {"name": "reranker", "status": "skipped", "latency_ms": 0,
                "detail": "已关闭（CPU 上延迟超预算，GPU 环境可开启）"}
    if not model_dir.exists():
        return {"name": "reranker", "status": "degraded", "latency_ms": 0,
                "detail": f"模型目录缺失：{model_dir}"}
    return {"name": "reranker", "status": "ok", "latency_ms": 0, "detail": "已加载"}


def _check_disk(min_gb: float = 1.0) -> dict:
    try:
        free_gb = shutil.disk_usage(settings.data_dir if settings.data_dir.exists() else ".")
        gb = free_gb.free / 1024**3
        return {"name": "disk", "status": "ok" if gb >= min_gb else "down",
                "latency_ms": 0, "detail": f"{gb:.1f}GB free"}
    except Exception as exc:  # noqa: BLE001
        return {"name": "disk", "status": "down", "latency_ms": 0, "detail": str(exc)}


@router.get("/health")
def health() -> dict:
    checks = [
        _check_mysql(),
        _check_path("vector_store", settings.data_dir / "vectors.pkl", "file"),
        _check_path("bm25", settings.bm25_file, "file"),
        _check_path("embedding", settings.model_dir / "bge-m3", "dir"),
        _check_reranker(),
        _check_deepseek(),
        _check_disk(),
    ]
    if any(c["status"] == "down" for c in checks):
        status = "down"
    elif any(c["status"] == "degraded" for c in checks):
        status = "degraded"
    else:
        status = "ok"

    return ok({
        "status": status,
        "checks": checks,
        "version": settings.app_version,
        "uptime_seconds": int(time.time() - _START),
    })


@router.get("/stats")
def stats() -> dict:
    """W1 阶段只返回结构；数据接入在 W2/W3 完成。"""
    return ok({
        "documents": {"total": 0, "ready": 0, "failed": 0},
        "chunks": 0,
        "sessions": 0,
        "qa": {"total": 0, "today": 0, "fallback_rate": 0.0},
        "latency": {"p50": None, "p95": None, "p99": None},
        "fallback_distribution": [],
        "trend": [],
        "top_failed_questions": [],
    })
