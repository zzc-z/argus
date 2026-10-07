"""健康检查端点测试。"""

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app


def test_healthz_returns_ok() -> None:
    """/api/v1/healthz 不依赖任何外部服务，恒返回 200。"""
    with TestClient(app) as client:
        response = client.get("/api/v1/healthz")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "argus-api"
    assert body["detail"] is None


def test_readyz_returns_ok_when_db_available() -> None:
    """DB 连得上时 /api/v1/readyz 返回 200。"""
    with TestClient(app) as client:
        response = client.get("/api/v1/readyz")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_readyz_returns_503_when_db_unavailable() -> None:
    """DB 连不上时 /api/v1/readyz 返回 503，且 body 里 status 为 unavailable。

    patch app.main.check_db_health 而不是真改 .env——测试不依赖外部环境。
    """
    with (
        patch("app.gateway.health.check_db_health", side_effect=ConnectionError("db down")),
        TestClient(app) as client,
    ):
        response = client.get("/api/v1/readyz")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["detail"] == "ConnectionError"


def test_docs_available() -> None:
    """OpenAPI 文档页可访问。"""
    with TestClient(app) as client:
        response = client.get("/docs")

    assert response.status_code == 200


def test_openapi_schema_declares_api_v1_prefix() -> None:
    """OpenAPI schema 中的路径都挂在 /api/v1 前缀下。"""
    with TestClient(app) as client:
        schema = client.get("/openapi.json").json()

    paths = set(schema["paths"])
    assert "/api/v1/healthz" in paths
    assert "/api/v1/readyz" in paths
