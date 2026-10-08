"""OAuth 登录编排测试：三条查找路径 + 资料刷新。

路径：老用户命中 → email 自动关联 → 完全新建。
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Account, Provider, User
from app.services.auth import LoginResult, OAuthProfile, get_or_create_user


async def _count(session: AsyncSession, model: type) -> int:
    stmt = select(func.count()).select_from(model)
    return await session.scalar(stmt) or 0


def _profile(**overrides: object) -> OAuthProfile:
    defaults: dict[str, object] = {
        "provider": Provider.GITHUB,
        "provider_account_id": "12345",
        "email": "alice@example.com",
        "display_name": "alice",
        "avatar_url": "https://avatars.githubusercontent.com/u/12345",
    }
    return OAuthProfile(**{**defaults, **overrides})  # type: ignore[arg-type]


async def test_new_user_created(db_session: AsyncSession) -> None:
    """第一次登录：建 user + account，is_new=True。"""
    result = await get_or_create_user(db_session, _profile())

    assert result.is_new is True
    assert result.linked is False
    assert result.user.id is not None
    assert result.user.email == "alice@example.com"

    assert await _count(db_session, User) == 1
    assert await _count(db_session, Account) == 1


async def test_existing_identity_returns_same_user(db_session: AsyncSession) -> None:
    """同一 provider 同一 ID 二次登录：返回同一个 user，不新建。"""
    first = await get_or_create_user(db_session, _profile())
    second = await get_or_create_user(db_session, _profile())

    assert second.is_new is False
    assert second.linked is False
    assert second.user.id == first.user.id
    assert await _count(db_session, User) == 1
    assert await _count(db_session, Account) == 1


async def test_different_provider_same_email_links_account(db_session: AsyncSession) -> None:
    """同邮箱换 provider 登录：自动关联到已有 user，不新建。"""
    first = await get_or_create_user(
        db_session,
        _profile(provider=Provider.GITHUB, provider_account_id="12345"),
    )
    second = await get_or_create_user(
        db_session,
        _profile(provider=Provider.GOOGLE, provider_account_id="99999"),
    )

    assert second.is_new is False
    assert second.linked is True
    assert second.user.id == first.user.id
    assert await _count(db_session, User) == 1
    # users 一行，accounts 两行（GitHub + Google）
    assert await _count(db_session, Account) == 2


async def test_different_email_creates_separate_user(db_session: AsyncSession) -> None:
    """邮箱不同就是不同的人，不关联。"""
    await get_or_create_user(db_session, _profile())
    second = await get_or_create_user(
        db_session,
        _profile(provider=Provider.GOOGLE, provider_account_id="99999", email="bob@example.com"),
    )

    assert second.is_new is True
    assert second.linked is False
    assert await _count(db_session, User) == 2


async def test_profile_refresh_updates_fields(db_session: AsyncSession) -> None:
    """老用户再次登录时，本地资料被 provider 的最新值覆盖。"""
    await get_or_create_user(db_session, _profile(display_name="alice-old"))
    result = await get_or_create_user(db_session, _profile(display_name="alice-new"))

    assert result.user.display_name == "alice-new"


async def test_refresh_does_not_wipe_fields_with_null(db_session: AsyncSession) -> None:
    """provider 返回空值时不覆盖本地已有资料。"""
    await get_or_create_user(db_session, _profile(display_name="alice"))
    result = await get_or_create_user(
        db_session,
        _profile(display_name=None, avatar_url=None),
    )

    assert result.user.display_name == "alice"
    assert result.user.avatar_url is not None


async def test_login_without_email_skips_linking(db_session: AsyncSession) -> None:
    """provider 没给邮箱时不做关联，也不报错。"""
    result = await get_or_create_user(
        db_session,
        _profile(email=None, provider=Provider.GOOGLE, provider_account_id="77777"),
    )

    assert result.is_new is True
    assert result.user.email is None


async def test_return_type_carries_user_instance(db_session: AsyncSession) -> None:
    """返回的 LoginResult 里 user 是真实的 ORM 对象，可直接序列化。"""
    result = await get_or_create_user(db_session, _profile())

    assert isinstance(result, LoginResult)
    assert isinstance(result.user, User)
