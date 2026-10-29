"""trace_id：贯穿一次请求的日志与响应。"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

_trace_id: ContextVar[str] = ContextVar("trace_id", default="")


def new_trace_id() -> str:
    return uuid.uuid4().hex[:16]


def current_trace_id() -> str:
    return _trace_id.get() or new_trace_id()


@contextmanager
def trace_context(trace_id: str) -> Iterator[None]:
    token = _trace_id.set(trace_id)
    try:
        yield
    finally:
        _trace_id.reset(token)
