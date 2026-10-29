"""配置服务：读写 app_configs，带类型/范围校验与审计（ADR-019）。"""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from kbqa.infra.db import models as m

GROUP_LABELS = {
    "chunk": "切分参数",
    "retrieval": "检索参数",
    "generation": "生成参数",
    "conversation": "会话参数",
    "eval": "评测参数",
    "runtime": "运行时",
    "upload": "上传限制",
}


class ConfigError(Exception):
    def __init__(self, key: str, reason: str) -> None:
        super().__init__(f"{key}: {reason}")
        self.key = key
        self.reason = reason


def _coerce(row: m.AppConfig, value):
    """按 value_type 校验并归一化；不合法抛 ConfigError。"""
    t = row.value_type
    key = row.config_key

    if t == "bool":
        if not isinstance(value, bool):
            raise ConfigError(key, "应为布尔值")
        return value
    if t == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigError(key, "应为整数")
    elif t == "float":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConfigError(key, "应为数值")
        value = float(value)
    elif t in ("str", "enum"):
        if not isinstance(value, str):
            raise ConfigError(key, "应为字符串")
    elif t == "json":
        if not isinstance(value, (list, dict)):
            raise ConfigError(key, "应为 JSON 数组或对象")
    else:
        raise ConfigError(key, f"未知类型 {t}")

    if t in ("int", "float"):
        if row.min_value is not None and value < float(row.min_value):
            raise ConfigError(key, f"不得小于 {row.min_value}")
        if row.max_value is not None and value > float(row.max_value):
            raise ConfigError(key, f"不得大于 {row.max_value}")
    if t == "enum" and row.enum_values and value not in row.enum_values:
        raise ConfigError(key, f"只能是 {row.enum_values} 之一")
    return value


class ConfigService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def all_rows(self) -> list[m.AppConfig]:
        return list(self.db.scalars(select(m.AppConfig).order_by(m.AppConfig.group_name,
                                                                m.AppConfig.config_key)))

    def grouped(self) -> list[dict]:
        groups: dict[str, list[dict]] = {}
        for r in self.all_rows():
            groups.setdefault(r.group_name, []).append({
                "key": r.config_key, "value": r.config_value, "default": r.default_value,
                "type": r.value_type, "description": r.description,
                "min": float(r.min_value) if r.min_value is not None else None,
                "max": float(r.max_value) if r.max_value is not None else None,
                "enum_values": r.enum_values,
                "hot_reloadable": r.hot_reloadable,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            })
        return [{"group": g, "label": GROUP_LABELS.get(g, g), "items": items}
                for g, items in groups.items()]

    def get(self, key: str, default=None):
        row = self.db.scalar(select(m.AppConfig).where(m.AppConfig.config_key == key))
        return row.config_value if row else default

    def snapshot(self) -> dict:
        return {r.config_key: r.config_value for r in self.all_rows()}

    def update(self, updates: dict, source: str = "ui") -> dict:
        """原子更新：任一项非法则全部不生效。"""
        rows = {r.config_key: r for r in self.all_rows()}
        unknown = [k for k in updates if k not in rows]
        if unknown:
            raise ConfigError(unknown[0], "未知配置项")

        prepared: dict[str, object] = {}
        for key, value in updates.items():
            prepared[key] = _coerce(rows[key], value)

        changed = []
        for key, value in prepared.items():
            row = rows[key]
            if row.config_value == value:
                continue
            self.db.add(m.ConfigAudit(config_key=key, old_value=row.config_value,
                                      new_value=value, source=source))
            old = row.config_value
            row.config_value = value
            row.updated_at = datetime.now()
            changed.append({"key": key, "old": old, "new": value, "applied": True})

        non_hot = [c["key"] for c in changed if not rows[c["key"]].hot_reloadable]
        return {
            "updated": len(changed),
            "effective": "restart_required" if non_hot else "hot",
            "restart_keys": non_hot,
            "items": changed,
        }
