"""配置接口（API-26、API-27）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from kbqa.api.deps import get_db
from kbqa.api.exception_handlers import ApiError, ErrorCode
from kbqa.api.response import ok
from kbqa.config.runtime import invalidate
from kbqa.config.service import ConfigError, ConfigService

router = APIRouter(prefix="/configs", tags=["configs"])


@router.get("")
def list_configs(group: str | None = None, db: Session = Depends(get_db)) -> dict:
    groups = ConfigService(db).grouped()
    if group:
        groups = [g for g in groups if g["group"] == group]
    return ok({"groups": groups})


@router.put("")
def update_configs(body: dict, db: Session = Depends(get_db)) -> dict:
    updates = body.get("updates")
    if not isinstance(updates, dict) or not updates:
        raise ApiError(ErrorCode.INVALID_PARAM, "updates 必须是非空对象")

    svc = ConfigService(db)
    try:
        result = svc.update(updates, source="ui")
    except ConfigError as exc:
        raise ApiError(ErrorCode.CONFIG_INVALID, f"配置项 {exc.key} 不合法：{exc.reason}") from exc
    db.commit()
    invalidate()   # 让下一次请求立刻读到新值
    return ok(result)


@router.get("/audits")
def list_audits(key: str | None = None, db: Session = Depends(get_db)) -> dict:
    from sqlalchemy import select

    from kbqa.infra.db import models as m

    stmt = select(m.ConfigAudit).order_by(m.ConfigAudit.id.desc()).limit(100)
    if key:
        stmt = stmt.where(m.ConfigAudit.config_key == key)
    rows = list(db.scalars(stmt))
    items = [{"id": r.id, "key": r.config_key, "old": r.old_value, "new": r.new_value,
              "source": r.source,
              "at": r.created_at.isoformat() if r.created_at else None} for r in rows]
    return ok({"items": items, "total": len(items)})
