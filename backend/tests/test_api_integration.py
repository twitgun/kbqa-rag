"""接口级集成测试：走真实 HTTP + 真实 MySQL（不可用时自动跳过）。

这些用例覆盖单元测试碰不到的东西：路由顺序、依赖注入、事务提交、序列化。
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from kbqa.infra.db import session as db
from kbqa.main import create_app

SAMPLE_MD = """# 集成测试文档

这是一个用于验证上传链路的样例文档，内容需要超过二十个字符才能通过空文档校验。

## 配置 CORS

使用 CORSMiddleware 并设置 allow_origins 参数即可完成跨域配置。

## 后台任务

通过 BackgroundTasks 把耗时操作放到响应之后执行。
"""


def _db_ready() -> bool:
    ok, _ = db.ping()
    return ok


pytestmark = pytest.mark.skipif(not _db_ready(), reason="需要 MySQL 开发实例（3307）")


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app()) as c:
        yield c


def _wait_job(client: TestClient, job_id: int, timeout: float = 60) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/v1/jobs/{job_id}").json()["data"]
        if job["status"] in ("succeeded", "failed", "canceled"):
            return job
        time.sleep(0.3)
    raise AssertionError(f"任务 {job_id} 超时")


def test_upload_index_query_delete(client: TestClient):
    files = {"file": ("it-sample.md", SAMPLE_MD.encode("utf-8"), "text/markdown")}
    r = client.post("/api/v1/documents/upload", files=files, data={"auto_index": "true"})
    body = r.json()
    assert body["code"] == 0, body
    doc_id, job_id = body["data"]["document_id"], body["data"]["job_id"]
    assert job_id is not None

    job = _wait_job(client, job_id)
    assert job["status"] == "succeeded", job

    doc = client.get(f"/api/v1/documents/{doc_id}").json()["data"]
    assert doc["status"] == "ready"
    assert doc["chunk_count"] > 0

    chunks = client.get(f"/api/v1/documents/{doc_id}/chunks").json()["data"]
    assert chunks["total"] == doc["chunk_count"]
    uid = chunks["items"][0]["chunk_uid"]
    assert uid.startswith(f"d{doc_id}_c")

    ctx = client.get(f"/api/v1/chunks/{uid}/context").json()["data"]
    assert ctx["chunk"]["chunk_uid"] == uid

    # 同一文件再传一次：应识别为重复，不新建
    files2 = {"file": ("it-sample.md", SAMPLE_MD.encode("utf-8"), "text/markdown")}
    dup = client.post("/api/v1/documents/upload", files=files2).json()["data"]
    assert dup["is_duplicate"] is True and dup["document_id"] == doc_id

    # 检索能命中
    hit = client.post("/api/v1/retrieval/search", json={"query": "配置 CORS"}).json()
    assert hit["code"] == 0
    assert hit["data"]["candidates"], "应召回片段"

    # 删除后不可再查
    assert client.delete(f"/api/v1/documents/{doc_id}").json()["code"] == 0
    assert client.get(f"/api/v1/documents/{doc_id}").json()["code"] == 2001


def test_unsupported_format_rejected(client: TestClient):
    r = client.post("/api/v1/documents/upload",
                    files={"file": ("bad.exe", b"MZ...", "application/octet-stream")})
    assert r.json()["code"] == 1002


def test_formats_and_download(client: TestClient):
    fmts = client.get("/api/v1/documents/formats").json()
    assert fmts["code"] == 0 and len(fmts["data"]["formats"]) == 5


def test_chat_returns_envelope_even_without_llm(client: TestClient):
    r = client.post("/api/v1/chat/ask", json={"question": "怎么配置 CORS"})
    body = r.json()
    assert body["code"] == 0, body
    data = body["data"]
    assert data["answer"]
    assert data["answer_status"] in ("ok", "fallback")
    if data["is_fallback"]:
        assert data["fallback_reason"] in (
            "insufficient_evidence", "llm_unavailable", "validation_failed")
    assert data["session_id"] > 0


def test_blank_question_rejected(client: TestClient):
    r = client.post("/api/v1/chat/ask", json={"question": "   "})
    assert r.json()["code"] == 1001


def test_session_lifecycle(client: TestClient):
    sid = client.post("/api/v1/sessions", json={"title": "临时会话"}).json()["data"]["id"]
    assert client.patch(f"/api/v1/sessions/{sid}",
                        json={"title": "改名"}).json()["data"]["title"] == "改名"
    msgs = client.get(f"/api/v1/sessions/{sid}/messages").json()["data"]
    assert msgs["total"] == 0
    assert client.delete(f"/api/v1/sessions/{sid}").json()["code"] == 0
    assert client.get(f"/api/v1/sessions/{sid}/messages").json()["code"] == 1004
