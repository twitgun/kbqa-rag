"""W1 骨架冒烟测试：不依赖数据库与模型。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from kbqa.main import create_app


def test_health_envelope() -> None:
    with TestClient(create_app()) as client:
        r = client.get("/api/v1/system/health")

    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"code", "message", "data", "trace_id", "timestamp"}
    assert body["code"] == 0
    assert len(body["trace_id"]) == 16
    assert body["data"]["status"] in {"ok", "degraded", "down"}


def test_health_has_seven_checks() -> None:
    with TestClient(create_app()) as client:
        checks = client.get("/api/v1/system/health").json()["data"]["checks"]

    names = [c["name"] for c in checks]
    assert names == ["mysql", "vector_store", "bm25", "embedding", "reranker", "deepseek", "disk"]
    for c in checks:
        assert c["status"] in {"ok", "degraded", "down", "skipped"}


def test_trace_id_is_echoed() -> None:
    with TestClient(create_app()) as client:
        r = client.get("/api/v1/system/health", headers={"X-Trace-Id": "abcdef0123456789"})

    assert r.headers["X-Trace-Id"] == "abcdef0123456789"
    assert r.json()["trace_id"] == "abcdef0123456789"


def test_unknown_path_returns_404() -> None:
    with TestClient(create_app()) as client:
        r = client.get("/api/v1/not-exist")
    assert r.status_code == 404
