"""pytest 全局fixture。

核心约定：**测试绝不碰开发数据库**。
所有需要库的测试用 ``db_session`` fixture，它跑在独立的内存 SQLite 上，
每个测试结束后整个库丢弃。这样pytest 可以反复跑、可以并发跑，
不会污染 argus.db，也不会因为 dev 库里的残留数据而随机失败。
"""

from collections.abc import AsyncGenerator, AsyncIterator, Iterator
from urllib.parse import parse_qs, urlparse

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db import get_session
from app.gateway.auth import OAUTH_STATE_COOKIE
from app.main import app
from app.models import Base

pytest_plugins: list[str] = []


@pytest.fixture(autouse=True)
def _reset_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """确保测试不依赖真实 env vars。"""
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("LOG_LEVEL", "warning")


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """内存 SQLite + 完整 schema，测试结束即销毁。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session

    await engine.dispose()


@pytest.fixture
async def api_db(db_session: AsyncSession) -> AsyncGenerator[AsyncSession, None]:
    """把路由里的 get_session 依赖换成测试库，避免写 dev 库。"""
    assert db_session is not None  # 让 mypy 认出这是个 async fixture

    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = _override
    yield db_session
    app.dependency_overrides.clear()


@pytest.fixture
def client(api_db: AsyncSession) -> Iterator[TestClient]:
    """走测试库的 TestClient。带上 api_db 参数纯粹是为了触发它。"""
    with TestClient(app) as c:
        yield c


@pytest.fixture
def github_state(client: TestClient) -> str:
    """跑一次 login 端点，拿到合法 state 并留在 client 的 cookie 里。

    登录流程中间态（state + PKCE verifier）存在签名 cookie 中，
    所以「发起登录」和「校验 state」必须在同一个 TestClient 上。
    """
    resp = client.get("/api/v1/auth/github/login", follow_redirects=False)
    return parse_qs(urlparse(resp.headers["location"]).query)["state"][0]
