"""数据库连接管理：engine + sessionmaker + yield 依赖。

engine 与 SessionLocal 在模块导入时各建一次，进程内唯一。
每个 HTTP 请求通过 ``get_session()`` 拿到一个独立的 AsyncSession。
"""

from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

# ── 模块级单例 ──────────────────────────────────────────────
# 模块导入时执行一次。生产部署多 worker 时每个 worker 各持一份。
_settings = get_settings()

engine = create_async_engine(
    _settings.database_url,
    echo=_settings.debug,  # debug=True 时把所有 SQL 打到 stdout
    future=True,           # 启用 SQLAlchemy 2.0 风格 API
)

# expire_on_commit=False：commit 后 ORM 对象属性不过期，
# 避免 endpoint 返回响应时偷偷再查一次 DB。
SessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,  # 显式控制 flush 时机，行为更可预测
)


# ── FastAPI 依赖 ─────────────────────────────────────────────
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖：每个请求提供一个 AsyncSession，请求结束自动关闭。

    用法：
        @app.get("/users/{uid}")
        async def get_user(uid: int, session: AsyncSession = Depends(get_session)):
            ...
    """
    async with SessionLocal() as session:
        yield session


# ── 健康检查 ─────────────────────────────────────────────────
async def check_db_health() -> bool:
    """/readyz 用：执行 SELECT 1 验证 DB 连接。失败抛异常。"""
    async with SessionLocal() as session:
        await session.execute(text("SELECT 1"))
    return True


# ── 测试钩子 ─────────────────────────────────────────────────
async def dispose_engine() -> None:
    """测试 teardown 用：关闭连接池。

    生产代码不要调这个——engine 是进程级单例，生命周期跟进程一致。
    """
    await engine.dispose()
