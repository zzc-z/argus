"""HTTP 安全响应头测试。

三组断言：
- 头确实出现在每个响应上，且值逐字正确（不是「有个 key 就行」）
- SSE 流式响应没被中间件破坏（回归防线：裸 ASGI 而非 BaseHTTPMiddleware）
- CORS 预检短路响应同样带得上头（验证中间件顺序）

依据见 app/security.py 模块 docstring。
"""

import pytest
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.gateway import research as research_module
from app.security import SecurityHeadersMiddleware, build_security_headers

# 逐字期望值。改动 app/security.py 时这里会先红——这是有意的。
_EXPECTED = {
    "content-security-policy": "frame-ancestors 'none'",
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
}


def _app_with(headers: dict[str, str]) -> FastAPI:
    """造一个只挂安全头中间件的最小 app，用于单独测 HSTS 开关。"""
    probe = FastAPI()

    @probe.get("/probe")
    async def _probe() -> dict[str, bool]:
        return {"ok": True}

    probe.add_middleware(SecurityHeadersMiddleware, headers=headers)
    return probe


# ── 头存在且值正确 ────────────────────────────────────────────


def test_security_headers_present_on_json_response(client: TestClient) -> None:
    """普通 JSON 响应带上全部安全头。"""
    resp = client.get("/api/v1/healthz")

    assert resp.status_code == 200
    for name, value in _EXPECTED.items():
        assert resp.headers[name] == value, f"{name} 不等于期望值"


def test_permissions_policy_denies_sensitive_features(client: TestClient) -> None:
    """Permissions-Policy 关掉摄像头/麦克风/定位等能力。

    逐个查而不是只查存在——值写错成 ``camera=(self)`` 一样能通过存在性断言。
    """
    value = client.get("/api/v1/healthz").headers["permissions-policy"]

    for feature in ("camera", "microphone", "geolocation", "payment", "usb", "fullscreen"):
        assert f"{feature}=()" in value, f"{feature} 未被禁用"


def test_permissions_policy_keeps_clipboard(client: TestClient) -> None:
    """clipboard 不能被禁。

    apps/web 的 error-404 TraceIdBar 用 navigator.clipboard.writeText 复制
    trace id。Permissions-Policy 里 clipboard 一旦被关，那个按钮静默失效——
    没有任何报错，只是点了没反应。
    """
    value = client.get("/api/v1/healthz").headers["permissions-policy"]

    assert "clipboard" not in value


# ── HSTS 只在 prod 发 ─────────────────────────────────────────


def test_hsts_absent_in_dev(client: TestClient) -> None:
    """默认 app_env=dev，不发 HSTS。

    MDN：浏览器在 HTTP 下忽略 HSTS，本地 http 开发它毫无作用；但若有人改用
    HTTPS 跑开发，它会把整个域名钉死在 HTTPS 上。所以 dev 不发。
    """
    assert "strict-transport-security" not in client.get("/api/v1/healthz").headers


def test_hsts_present_when_enabled() -> None:
    """enable_hsts=True 时 HSTS 带上，且带 includeSubDomains。"""
    headers = build_security_headers(enable_hsts=True)

    assert headers["strict-transport-security"] == "max-age=31536000; includeSubDomains"


def test_hsts_reaches_the_wire_when_enabled() -> None:
    """不只验证构造函数——真发一次请求，确认头真的到了响应上。"""
    probe = _app_with(build_security_headers(enable_hsts=True))

    with TestClient(probe) as client:
        resp = client.get("/probe")

    assert resp.headers["strict-transport-security"] == "max-age=31536000; includeSubDomains"


# ── 不覆盖路由自设的头 ────────────────────────────────────────


def test_route_can_override_its_own_header() -> None:
    """路由显式设的头不被中间件盖掉。

    SSE 路由（app/gateway/research.py）自设了 Cache-Control: no-store, no-transform
    来压住反代缓冲。若中间件用赋值而非「仅在缺失时补」，这里就会把它改回
    no-store，流式在 nginx 后失效——且测试不会红，只会线上变慢。
    """
    probe = FastAPI()

    @probe.get("/own")
    async def _own() -> Response:
        return Response(
            content="{}",
            media_type="application/json",
            headers={"cache-control": "no-store, no-transform"},
        )

    probe.add_middleware(
        SecurityHeadersMiddleware, headers=build_security_headers(enable_hsts=False)
    )

    with TestClient(probe) as client:
        resp = client.get("/own")

    assert resp.headers["cache-control"] == "no-store, no-transform"
    # 其余头照常补上
    assert resp.headers["x-content-type-options"] == "nosniff"


# ── SSE 流式不被破坏 ──────────────────────────────────────────


async def test_sse_response_keeps_streaming_headers(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, api_db: AsyncSession
) -> None:
    """SSE 响应既有安全头，又保住自己的流式头。

    这是「用裸 ASGI 而非 BaseHTTPMiddleware」的回归防线：后者会把
    StreamingResponse 包进自己的任务，缓冲响应体。
    """
    from tests.test_research_router import _fake_agent_success, _login

    await _login(client, api_db)
    monkeypatch.setattr(research_module, "run_agent", _fake_agent_success)

    with client.stream("POST", "/api/v1/research/ask", json={"question": "问题"}) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        assert resp.headers["x-accel-buffering"] == "no"
        assert resp.headers["cache-control"] == "no-store, no-transform"
        assert resp.headers["content-security-policy"] == "frame-ancestors 'none'"
        resp.read()


# ── CORS 预检也带得上 ─────────────────────────────────────────


def test_cors_preflight_carries_security_headers() -> None:
    """CORS 预检短路响应同样带安全头。

    安全头中间件后注册 → 在最外层 → 包住 CORS。若顺序反了，预检响应
    （CORS 直接返回，不进路由）就会漏掉这些头。
    """
    probe = FastAPI()

    @probe.get("/x")
    async def _x() -> dict[str, bool]:
        return {"ok": True}

    probe.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"])
    probe.add_middleware(
        SecurityHeadersMiddleware, headers=build_security_headers(enable_hsts=False)
    )

    with TestClient(probe) as client:
        resp = client.options(
            "/x",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert resp.status_code == 200
    assert resp.headers["content-security-policy"] == "frame-ancestors 'none'"
    assert resp.headers["x-frame-options"] == "DENY"


# ── 真实 app 上 CORS + 安全头共存 ─────────────────────────────


def test_real_app_cors_still_works_alongside_security_headers(client: TestClient) -> None:
    """加了安全头不能把 CORS 弄坏——前端跨域调用全靠它。"""
    resp = client.get("/api/v1/healthz", headers={"Origin": "http://localhost:3000"})

    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert resp.headers["x-content-type-options"] == "nosniff"


def test_docs_page_still_served_with_security_headers(client: TestClient) -> None:
    """/docs 仍可访问且带安全头。

    /docs 是 FastAPI 生成的 HTML，从 cdn.jsdelivr.net 拉 Swagger UI。
    frame-ancestors 只管「能否被嵌进 iframe」，不管「能加载什么资源」，
    所以不会像 script-src 那样把文档页打不开——这条测试守住这个区别。
    """
    resp = client.get("/docs")

    assert resp.status_code == 200
    assert resp.headers["content-security-policy"] == "frame-ancestors 'none'"
