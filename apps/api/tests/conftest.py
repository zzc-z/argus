"""pytest 全局fixture。

核心约定：**测试绝不碰开发数据库**。
所有需要库的测试用 ``db_session`` fixture，它跑在独立的内存 SQLite 上，
每个测试结束后整个库丢弃。这样pytest 可以反复跑、可以并发跑，
不会污染 argus.db，也不会因为 dev 库里的残留数据而随机失败。
"""

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

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
