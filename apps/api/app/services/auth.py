"""认证相关的业务编排。

当前只有 OAuth 登录的「找或建用户」。将来 session 管理、token 刷新也放这里。
"""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Account, Provider, User


@dataclass(frozen=True, slots=True)
class OAuthProfile:
    """从 OAuth provider 拿到的用户资料。

    与 provider 无关——GitHub / Google 的字段名不同，在 gateway 层
    转换成这个统一结构后再传给 service，service 不需要知道哪家 provider。
    """

    provider: Provider
    provider_account_id: str
    email: str | None = None
    display_name: str | None = None
    avatar_url: str | None = None


@dataclass(frozen=True, slots=True)
class LoginResult:
    """登录结果。

    is_new 供前端决定要不要走 onboarding；linked 表示这次登录
    把一个已有账号绑上了新的 provider（自动关联）。
    """

    user: User
    is_new: bool
    linked: bool = False


async def get_or_create_user(session: AsyncSession, profile: OAuthProfile) -> LoginResult:
    """按 OAuth 身份找用户，找不到则建；邮箱撞上已有账号时做自动关联。

    三段查找（顺序不能变，先命中先返回）：
      1. (provider, provider_account_id) 命中 → 老用户，顺带刷新资料
      2. email 命中已有 user → 账号关联，把新 provider 挂上去
      3. 都没有 → 新建 user + account

    自动关联的前提是 provider 能保证邮箱已验证。GitHub 与 Google 的
    OAuth 流程都会验证主邮箱，所以这里安全。若将来接入允许未验证邮箱的
    provider，必须在调用方关掉第2 步，否则会出现账号劫持。
    """
    account = await Account.find_by_identity(
        session,
        profile.provider,
        profile.provider_account_id,
    )
    if account is not None:
        _refresh_profile(account.user, profile)
        await session.commit()
        return LoginResult(user=account.user, is_new=False)

    if profile.email:
        existing = await User.find_by_email(session, profile.email)
        if existing is not None:
            existing.accounts.append(
                Account(
                    provider=profile.provider,
                    provider_account_id=profile.provider_account_id,
                )
            )
            _refresh_profile(existing, profile)
            await session.commit()
            return LoginResult(user=existing, is_new=False, linked=True)

    user = User(email=profile.email, display_name=profile.display_name, avatar_url=profile.avatar_url)
    user.accounts.append(
        Account(
            provider=profile.provider,
            provider_account_id=profile.provider_account_id,
        )
    )
    session.add(user)
    await session.commit()
    return LoginResult(user=user, is_new=True)


def _refresh_profile(user: User, profile: OAuthProfile) -> None:
    """用provider 返回的最新资料覆盖本地字段。

    只覆盖非空值——用户可能在 GitHub 清掉了头像或设为私有，
    那时不该把本地已有的值抹成 NULL。
    """
    if profile.display_name:
        user.display_name = profile.display_name
    if profile.avatar_url:
        user.avatar_url = profile.avatar_url
    if profile.email:
        user.email = profile.email
