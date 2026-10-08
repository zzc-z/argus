"""Alembic 运行时脚本。

与模板的两点差异：
1. ``target_metadata`` 指向 app.models.Base.metadata——否则 autogenerate 看不到任何表
2. 数据库 URL 从 app.config.get_settings() 读，而不是写死在 alembic.ini里，
   保证迁移用的库和应用连的是同一个
"""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from app.config import get_settings
from app.models import Base

# Alembic Config 对象，提供 alembic.ini 里的配置访问
config = context.config

# 让alembic.ini 的 [loggers] 段生效
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# autogenerate 的比对基准——所有模型的注册表
target_metadata = Base.metadata


def get_url() -> str:
    """从应用配置拿库连接串，覆盖 alembic.ini 的静态值。"""
    return get_settings().database_url


def run_migrations_offline() -> None:
    """离线模式：不连库，只把 SQL 打到stdout。

    用法：alembic upgrade head --sql
    """
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,      # 类型变了也要生成 ALTER
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """同步上下文中执行迁移（由 run_async_migrations 调用）。"""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """建async engine，连库，跑迁移。"""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  #迁移结束就关，不复用
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
