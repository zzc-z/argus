"""ORM 模型结构测试。

锁住 schema 契约——字段名 / 类型 / 可空性 / 主键一旦被改坏，
这里立刻失败，避免 migration 已经上线才发现问题。
"""

import pytest
from sqlalchemy import String
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Account, Base, Provider, User


def test_metadata_registers_all_tables() -> None:
    """Base.metadata 收录全部四张表。

    Alembic autogenerate 靠遍历这份注册表比对实际结构，少 import 一个模块
    就等于该表不进迁移——所以这里断言的是全集，不只是新增的那两张。
    """
    assert sorted(Base.metadata.tables) == [
        "accounts",
        "document_chunks",
        "sources",
        "users",
    ]


def test_user_columns_and_nullability() -> None:
    """users 表字段与可空性符合设计。"""
    columns = {c.name: c.nullable for c in User.__table__.columns}

    assert columns["id"] is False  # NOT NULL
    assert columns["email"] is True  # OAuth 用户可能不给邮箱
    assert columns["display_name"] is True
    assert columns["avatar_url"] is True
    assert columns["created_at"] is False
    assert columns["updated_at"] is False


def test_account_composite_primary_key() -> None:
    """accounts 用 (provider, provider_account_id) 复合主键。"""
    pk_columns = [c.name for c in Account.__table__.primary_key.columns]

    assert pk_columns == ["provider", "provider_account_id"]


def test_account_cascades_on_user_delete() -> None:
    """users 删除时 accounts 级联删除，不留孤儿行。"""
    fk = next(iter(Account.__table__.foreign_keys))

    assert fk.ondelete == "CASCADE"


def test_provider_enum_values() -> None:
    """Provider 枚举值小写，与 DB 里存的值一致。"""
    assert [p.value for p in Provider] == ["github", "google"]


def test_string_length_limits() -> None:
    """字段长度符合外部系统的硬限制（GitHub 用户名 39 / RFC 5321 邮箱 320）。"""
    user_lengths = {
        c.name: c.type.length for c in User.__table__.columns if isinstance(c.type, String)
    }
    assert user_lengths == {"email": 320, "display_name": 100, "avatar_url": 512}

    account_lengths = {
        c.name: c.type.length for c in Account.__table__.columns if isinstance(c.type, String)
    }
    assert account_lengths == {
        "provider": 32,
        "provider_account_id": 255,
        "access_token": 512,
        "refresh_token": 512,
    }


async def test_user_defaults_filled_on_insert(db_session: AsyncSession) -> None:
    """server_default 生效：created_at / updated_at 由 DB 自动填。"""
    user = User(email="a@example.com", display_name="alice")
    db_session.add(user)
    await db_session.commit()

    assert user.id is not None
    assert user.created_at is not None
    assert user.updated_at is not None


async def test_account_can_reference_user(db_session: AsyncSession) -> None:
    """accounts.user_id 能关联到 users.id。"""
    user = User(email="b@example.com")
    account = Account(provider=Provider.GITHUB.value, provider_account_id="12345")
    user.accounts.append(account)

    db_session.add(user)
    await db_session.commit()

    assert account.user_id == user.id
