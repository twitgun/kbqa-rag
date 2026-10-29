"""业务异常与全局异常处理。"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from kbqa.api.json import UTF8JSONResponse
from kbqa.api.response import fail

logger = logging.getLogger("kbqa")


class ApiError(Exception):
    """带业务错误码的异常。"""

    def __init__(self, code: str, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


class ErrorCode:
    INVALID_PARAM = "E-1001"
    UNSUPPORTED_FORMAT = "E-1002"
    FILE_TOO_LARGE = "E-1003"
    SESSION_NOT_FOUND = "E-1004"
    INVALID_COMBINATION = "E-1005"
    DOC_NOT_FOUND = "E-2001"
    PARSE_FAILED = "E-2002"
    EMPTY_DOCUMENT = "E-2003"
    INDEX_FAILED = "E-2004"
    JOB_CONFLICT = "E-2005"
    DUPLICATE_DOC = "E-2006"
    INSUFFICIENT_EVIDENCE = "E-3001"
    LLM_TIMEOUT = "E-3002"
    LLM_UNAVAILABLE = "E-3003"
    VALIDATION_FAILED = "E-3004"
    INVALID_CITATION = "E-3005"
    NO_RECALL = "E-3006"
    QA_NOT_FOUND = "E-3007"
    DB_ERROR = "E-4001"
    VECTOR_ERROR = "E-4002"
    CONFIG_INVALID = "E-4003"
    QUEUE_TIMEOUT = "E-4004"
    MODEL_LOAD_FAILED = "E-4005"
    FILE_SYSTEM_ERROR = "E-4006"
    UNKNOWN = "E-5001"


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        return UTF8JSONResponse(status_code=200, content=fail(exc.code, exc.message, exc.data))

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {"loc": [], "msg": "参数错误"}
        field = ".".join(str(x) for x in first.get("loc", [])[1:]) or "body"
        return UTF8JSONResponse(
            status_code=200,
            content=fail(ErrorCode.INVALID_PARAM, f"参数错误：{field} {first.get('msg', '')}"),
        )

    @app.exception_handler(Exception)
    async def _unknown(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_exception path=%s", request.url.path)
        return UTF8JSONResponse(
            status_code=200,
            content=fail(ErrorCode.UNKNOWN, "系统开小差了，请稍后重试"),
        )
