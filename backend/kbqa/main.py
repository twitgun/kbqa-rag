"""应用入口。

W1 骨架：健康检查 + 统一响应 + 全局异常 + trace。
后续里程碑逐步挂载 documents / chat / eval 等路由。
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from kbqa.api.exception_handlers import register_exception_handlers
from kbqa.api.json import UTF8JSONResponse
from kbqa.api.response import fail
from kbqa.api.router import api_router
from kbqa.observability.trace import current_trace_id, new_trace_id, trace_context
from kbqa.settings import settings

logger = logging.getLogger("kbqa")
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    from kbqa.infra.db import session as db

    alive, detail = db.ping()
    logger.info("startup db_ok=%s detail=%s", alive, detail)
    if not alive:
        logger.warning("数据库不可用，服务仍启动，健康检查将显示 down（NFR-10）")
    yield
    logger.info("shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title="知源 · 知识库问答系统",
        version=settings.app_version,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
        default_response_class=UTF8JSONResponse,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://127.0.0.1:8000"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def trace_middleware(request: Request, call_next):
        trace_id = request.headers.get("X-Trace-Id") or new_trace_id()
        request.state.trace_id = trace_id
        started = time.perf_counter()
        with trace_context(trace_id):
            response = await call_next(request)
        elapsed_ms = (time.perf_counter() - started) * 1000
        response.headers["X-Trace-Id"] = trace_id
        logger.info("access %s %s %s %.0fms trace=%s",
                    request.method, request.url.path, response.status_code,
                    elapsed_ms, trace_id)
        return response

    register_exception_handlers(app)
    app.include_router(api_router, prefix="/api/v1")

    if STATIC_DIR.exists() and any(STATIC_DIR.iterdir()):
        app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
    else:
        @app.get("/")
        def index() -> JSONResponse:
            return JSONResponse(content=fail(
                "E-5001", "前端尚未构建（运行 pnpm build 后生成 kbqa/static）"))

    return app


app = create_app()
