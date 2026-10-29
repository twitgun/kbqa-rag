"""运行时读取配置：带短 TTL 缓存，避免每次问答都查库。"""

from __future__ import annotations

import time

from sqlalchemy import select

from kbqa.infra.db import models as m
from kbqa.infra.db.session import SessionLocal

_TTL_SECONDS = 2.0
_cache: dict[str, object] = {}
_cached_at: float = 0.0


def load_config(force: bool = False) -> dict:
    """返回 {key: value} 的配置快照。数据库不可用时返回空字典（调用方用默认值）。"""
    global _cached_at
    now = time.time()
    if not force and _cache and (now - _cached_at) < _TTL_SECONDS:
        return dict(_cache)

    try:
        with SessionLocal() as db:
            rows = db.execute(select(m.AppConfig.config_key, m.AppConfig.config_value)).all()
        snapshot = {k: v for k, v in rows}
    except Exception:  # noqa: BLE001 — 配置库挂了不能阻断问答
        return dict(_cache)

    _cache.clear()
    _cache.update(snapshot)
    _cached_at = now
    return dict(_cache)


def get(key: str, default=None):
    return load_config().get(key, default)


def invalidate() -> None:
    """配置更新后调用，让下一次请求立刻读到新值。"""
    global _cached_at
    _cached_at = 0.0
