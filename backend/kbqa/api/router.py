"""路由汇总，前缀 /api/v1。"""

from __future__ import annotations

from fastapi import APIRouter

from kbqa.api.endpoints import chat, configs, documents, evaluation, extras, feedback, jobs, logs, retrieval, system

api_router = APIRouter()
api_router.include_router(system.router)
api_router.include_router(extras.router)   # 必须先于 documents，否则 /documents/formats 会被 /{doc_id} 吃掉
api_router.include_router(documents.router)
api_router.include_router(jobs.router)
api_router.include_router(retrieval.router)
api_router.include_router(chat.chat_router)
api_router.include_router(chat.session_router)
api_router.include_router(evaluation.router)
api_router.include_router(logs.router)
api_router.include_router(configs.router)
api_router.include_router(feedback.router)
