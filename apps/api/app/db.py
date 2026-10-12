"""数据库连接管理：engine + sessionmaker + yield 依赖。

engine 与 SessionLocal 在模块导入时各建一次，进程内唯一。
每个 HTTP 请求通过 ``get_session()`` 拿到一个独立的 AsyncSession。
"""

from collections.abc import AsyncGenerator

from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings


def _enable_sqlite_foreign_keys(engine: Engine) -> None:
    """给每条新 SQLite 连接打开外键约束。

    SQLite 默认 ``foreign_keys = 0``——外键声明被**接受但完全不执行**。
    不开这个 pragma，模型里的 ``ondelete="CASCADE"`` 全部形同虚设：
    删用户会留下一堆孤儿 sources / document_chunks，而且测试也不会报错。

    Postgres 无此问题（外键始终生效），但同一条 pragma 对它是 no-op，
    所以统一挂在 SQLAlchemy 的 connect 事件上，不按方言分支。
    """

    @event.listens_for(engine, "connect")
    def _set_pragma(dbapi_conn: object, _record: object) -> None:
        cursor = dbapi_conn.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


# ── 模块级单例 ──────────────────────────────────────────────
# 模块导入时执行一次。生产部署多 worker 时每个 worker 各持一份。
_settings = get_settings()

engine = create_async_engine(
    _settings.database_url,
    echo=_settings.debug,  # debug=True 时把所有 SQL 打到 stdout
    future=True,           # 启用 SQLAlchemy 2.0 风格 API
)
_enable_sqlite_foreign_keys(engine.sync_engine)

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
