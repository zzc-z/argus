"""按 OpenAPI 文档自动生成请求打接口，任何 5xx 或未捕获异常都算失败。

schemathesis 不进 pyproject：只在 CI 的独立步骤里用 ``uv run --with`` 装，
版本见 ``.github/workflows/ci.yml``。没装时本文件整体跳过。
"""

import asyncio
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.db import _enable_sqlite_foreign_keys, get_session
from app.gateway.deps import get_current_user
from app.main import app
from app.models import Base, User

schemathesis = pytest.importorskip("schemathesis")
hypothesis = pytest.importorskip("hypothesis")

# 超大整数越过 SQLite INTEGER 上限。修好后删掉对应行，
# 见 docs/TODO-code-quality.md B1。
KNOWN_OVERFLOW = {
    "GET /api/v1/reports",
    "GET /api/v1/reports/{report_id}",
    "DELETE /api/v1/reports/{report_id}",
    "GET /api/v1/sources/{source_id}",
    "DELETE /api/v1/sources/{source_id}",
    "GET /api/v1/sources/{source_id}/chunks",
    "PATCH /api/v1/sources/{source_id}/activate",
}

# 排除会真调模型、OAuth 或外网的接口，以及直连模块级 engine 的健康检查。
schema = schemathesis.openapi.from_asgi("/openapi.json", app).exclude(
    path_regex=r"/(research|auth|healthz|readyz)|/sources/url$"
)


@pytest.fixture(scope="module", autouse=True)
def _isolated_app(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """临时库 + 假登录。

    不用 conftest 的 ``api_db``：它是函数级内存库且绑定单个事件循环，
    schemathesis 每个请求都在新循环里跑。NullPool 保证连接不跨循环复用。
    """
    tmp = tmp_path_factory.mktemp("fuzz")
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp / 'fuzz.db'}", poolclass=NullPool)
    _enable_sqlite_foreign_keys(engine.sync_engine)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _prepare() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with factory() as session:
            session.add(User(id=1, email="fuzz@example.com", display_name="fuzz"))
            await session.commit()

    async def _session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    async def _user() -> User:
        return User(id=1, email="fuzz@example.com", display_name="fuzz")

    asyncio.run(_prepare())
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("SOURCE_UPLOAD_DIR", str(tmp / "uploads"))
        # 后台摄取直接调 get_vector_engine()，不停掉会连到开发库
        patch.setattr("app.gateway.sources._schedule_ingest", lambda *_args: None)
        app.dependency_overrides[get_session] = _session
        app.dependency_overrides[get_current_user] = _user
        try:
            yield
        finally:
            app.dependency_overrides.clear()


@schema.parametrize()
@hypothesis.settings(
    max_examples=50,
    deadline=None,
    derandomize=True,  # CI 结果可复现，不因随机数时红时绿
    suppress_health_check=list(hypothesis.HealthCheck),
)
def test_no_server_error(case: Any) -> None:
    try:
        case.call_and_validate(checks=[schemathesis.checks.not_a_server_error])
    except OverflowError:
        if case.operation.label not in KNOWN_OVERFLOW:
            raise
