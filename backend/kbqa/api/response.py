"""统一响应包体（见 02_系统设计/06 错误码与异常处理）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

from kbqa.observability.trace import current_trace_id

T = TypeVar("T")


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def ok(data: Any = None, message: str = "ok") -> dict[str, Any]:
    return {"code": 0, "message": message, "data": data,
            "trace_id": current_trace_id(), "timestamp": now_iso()}


def fail(code: str, message: str, data: Any = None) -> dict[str, Any]:
    """code 对外是整数（如 'E-1001' -> 1001）。"""
    try:
        numeric = int(code.split("-")[1])
    except (IndexError, ValueError):
        numeric = 5001
    return {"code": numeric, "message": message, "data": data,
            "trace_id": current_trace_id(), "timestamp": now_iso()}


def page(items: list[Any], total: int, page_no: int, size: int) -> dict[str, Any]:
    total_pages = (total + size - 1) // size if size else 0
    return ok({"items": items, "page": page_no, "size": size,
               "total": total, "total_pages": total_pages})


class ApiResponse(BaseModel, Generic[T]):
    code: int = 0
    message: str = "ok"
    data: T | None = None
    trace_id: str
    timestamp: str
