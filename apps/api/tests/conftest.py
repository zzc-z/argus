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
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.db import _enable_sqlite_foreign_keys, get_session
from app.gateway.auth import OAUTH_STATE_COOKIE
from app.main import app
from app.models import Base
from app.services.vectorstore import create_vector_engine

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
    # 与 app.db 同理：SQLite 默认不执行外键，不开 pragma 的话
    # CASCADE 相关的测试会「通过」而实际什么都没删。
    _enable_sqlite_foreign_keys(engine.sync_engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def shared_db(tmp_path) -> AsyncGenerator[tuple[AsyncSession, AsyncEngine], None]:
    """业务表与向量索引在**同一个** SQLite 文件里。

    混合检索的 ``source_ids`` 过滤是在向量库的 ``document_chunks`` 上做子查询，
    两边不同库的话子查询永远查不到行——症状是「索引明明有数据却一条都检索不到」。
    所以这两个 fixture 必须共用一个库，不能各自造。
    """
    db_path = tmp_path / "shared.db"
    # 用 create_vector_engine 而不是 create_async_engine：它加载了 sqlite-vec 扩展，
    # 而 vec0 虚表建在同一文件里。普通 engine 建 document_chunks 没问题，
    # 但一旦碰到 ensure_vector_table 就报 "no such module: vec0"。
    engine = create_vector_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session, engine

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
