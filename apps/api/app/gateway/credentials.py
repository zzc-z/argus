"""用户凭据配置的读写路由。

## 为什么这个接口存在

外部 AI 能力（Anthropic / Tavily / Embedding）的 key 与 base_url 原先
只有进程环境变量这一个来源——同一台部署上的**所有账号共用一把 key**。
测试人员没法各自配自己的中转站，也没法在不重新部署的情况下换线路。

这个接口让每个账号能在设置页配自己的凭据（见
``app/models/credentials.py``）。

## 两条铁律

1. **响应只回显「用户自己配的」密钥。** 别人的（共享默认行、部署环境
   里的）只给等长占位串（只露末 4 位）——那是**运维的密钥**，
   明文回显等于发给每一个登录用户（argus 没有管理员角色，注册即得）。
   另附 ``masked_key_fields`` 明示哪些值是占位串——前端据此不把它们
   当真值提交。
2. **只改自己的。** 每个请求按 cookie 里的 session 取 user_id，
   凭据按 user_id 存——没有「传 user_id 改别人的」这种入口。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.gateway.deps import CurrentUser
from app.models.credentials import SCOPE_USER, ProviderCredentials
from app.schemas.credentials import (
    CredentialItem,
    CredentialsResponse,
    CredentialsUpdate,
)
from app.services.credentials import (
    InvalidBaseUrlError,
    resolve_credentials,
    validate_base_url,
)
from app.services.secret_store import encrypt_secret

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])

DbSession = Annotated[AsyncSession, Depends(get_session)]

# 用户可配的字段白名单。**请求模型里的字段名与模型列名一一对应**，
# 所以这里只是一份「允许写哪些列」的名单。
#
# 用白名单而不是遍历请求字段：多配一个字段进来就悄悄写进库是不可
# 接受的——白名单让「没在名单里的字段」根本没有写入路径。
_WRITABLE_FIELDS = (
    "anthropic_api_key",
    "anthropic_base_url",
    "tavily_api_key",
    "embedding_api_key",
    "embedding_base_url",
    "anthropic_complex_model",
    "anthropic_default_model",
    "anthropic_critic_model",
)

# base_url 字段——它们存进库前要去掉尾部斜杠。
#
# ``base_url`` 后面要拼 ``/v1/messages``。尾部多一个斜杠会变成
# ``.../v1//messages``，中转站返回 404——而那种 404 的报错里完全
# 看不出是斜杠的问题，排查一次要花半小时。
_BASE_URL_FIELDS = frozenset({"anthropic_base_url", "embedding_base_url"})

# 存进库时要**加密**的字段——它们是 API key。
#
# 其余字段（base_url、模型名）明文存：地址与模型名不是秘密，页面要
# 直接回显它们，加密只会让「读出来给页面」这件事多一道解密。
_SECRET_FIELDS = frozenset(
    {"anthropic_api_key", "tavily_api_key", "embedding_api_key"}
)


def _echo(own: str | None, effective: str | None) -> str | None:
    """回显一个 key：**自己的明文，别人的占位串**。

    - ``own`` —— 用户自己配的那把（用户层的解密结果）
    - ``effective`` —— 最终生效的那把（可能是共享默认 / 部署环境的）

    两者一致 → 用户配的就是生效的 → 回显明文。
    不一致或 ``own`` 为空 → 生效的那把不是用户的 → **只给占位串**。

    ## 为什么占位串而不是空

    空 = 「没配」，占位串 = 「有，但不是你的」。页面据此能区分
    「我还没配」与「有人在用共享默认」——前者要填，后者不用填。
    """
    if own and effective and own == effective:
        return own
    return _mask(effective)


def _mask(secret: str | None) -> str | None:
    """把「不是用户自己的」密钥变成一个**不可还原的占位串**。

    ## 为什么需要它

    生效的 key 可能来自共享默认行或部署环境——那是**运维的密钥**。
    回显它等于把运维密钥发给每一个登录用户（argus 没有管理员角色，
    注册即得）。

    但完全不回显也不行：页面要能看出「这一格有值」。

    ## 占位串长什么样

    与原 key **等长**的 ``•``，只露**末 4 位**；不超过 4 位时全部打码。
    末 4 位足够让人认出「这是我那把 key」（key 的前缀本来就都一样）。

    等长是产品要求（页面上 key 的长度不能变），代价是暴露了长度。
    """
    if not secret:
        return None
    tail = secret[-4:] if len(secret) > 4 else ""
    return "•" * (len(secret) - len(tail)) + tail


@router.get(
    "/credentials",
    response_model=CredentialsResponse,
    summary="当前用户的凭据配置状态",
)
async def read_credentials(user: CurrentUser, db: DbSession) -> CredentialsResponse:
    """返回这个用户的凭据状态。

    **含用户自己配的密钥明文**；别人配的（共享默认行 / 部署环境）只给
    占位串——见模块 docstring 的「两条铁律」。


    报的是**最终生效**的值——用户配了就看用户的，没配就看部署默认。
    这样前端不需要自己判断「该显示我的还是显示默认的」。
    """
    resolved = await resolve_credentials(db, user.id)
    return CredentialsResponse(
        anthropic_api_key=CredentialItem(
            configured=bool(resolved.anthropic_api_key),
            source=resolved.anthropic_key_source,
        ),
        anthropic_base_url=CredentialItem(
            configured=bool(resolved.anthropic_base_url),
            source=resolved.anthropic_base_url_source,
        ),
        tavily_api_key=CredentialItem(
            configured=bool(resolved.tavily_api_key),
            source=resolved.tavily_key_source,
        ),
        embedding_api_key=CredentialItem(
            configured=bool(resolved.embedding_api_key),
            source=resolved.embedding_key_source,
        ),
        embedding_base_url=CredentialItem(
            configured=bool(resolved.embedding_base_url),
            source=resolved.embedding_base_url_source,
        ),
        # **用户自己配的 key → 明文；别人配的 → 占位串。**
        #
        # 生效值可能来自共享默认行或部署环境——那是**运维的密钥**，
        # 明文回显等于发给每个登录用户（argus 没有管理员角色）。
        # 见 ``_mask`` 的注释。
        anthropic_api_key_value=_echo(resolved.user_anthropic_api_key, resolved.anthropic_api_key),
        tavily_api_key_value=_echo(resolved.user_tavily_api_key, resolved.tavily_api_key),
        embedding_api_key_value=_echo(
            resolved.user_embedding_api_key, resolved.embedding_api_key
        ),
        # 哪些值是**占位串**——前端据此不把它们当真值提交。
        masked_key_fields=[
            name
            for name, own, effective in (
                ("anthropic_api_key", resolved.user_anthropic_api_key, resolved.anthropic_api_key),
                ("tavily_api_key", resolved.user_tavily_api_key, resolved.tavily_api_key),
                (
                    "embedding_api_key",
                    resolved.user_embedding_api_key,
                    resolved.embedding_api_key,
                ),
            )
            if own is None and effective is not None
        ],
        # 用户层的 key 解不开时生效地址是 None，仍要回显用户保存过的地址，
        # 否则看起来像没保存上。
        anthropic_base_url_value=resolved.anthropic_base_url or resolved.user_anthropic_base_url,
        embedding_base_url_value=resolved.embedding_base_url or resolved.user_embedding_base_url,
        # **用户自己配的** base_url——前端做 key/url 配对回填时只用它。
        user_anthropic_base_url=resolved.user_anthropic_base_url,
        user_embedding_base_url=resolved.user_embedding_base_url,
        anthropic_complex_model=resolved.anthropic_complex_model,
        anthropic_default_model=resolved.anthropic_default_model,
        anthropic_critic_model=resolved.critic_model,
        embedding_model=resolved.embedding_model,
        critic_equals_writer=resolved.critic_model == resolved.anthropic_complex_model,
    )


@router.put(
    "/credentials",
    response_model=CredentialsResponse,
    summary="保存当前用户的凭据配置",
)
async def update_credentials(
    payload: CredentialsUpdate,
    user: CurrentUser,
    db: DbSession,
) -> CredentialsResponse:
    """保存凭据配置。**部分更新**——三种状态要分清：

    | 请求里的值 | 含义 |
    |---|---|
    | 字段缺省 | 不改 |
    | ``""`` | 忽略（用户没动这个输入框） |
    | ``null`` | 清空（回落到部署默认） |
    | 有值 | 设成这个值 |

    **空串为什么是「忽略」而不是「清空」**：前端的输入框在用户没动过时
    也会提交空串——把它当成「清空」会让用户不小心把配好的 key 抹掉。
    真要清空，前端发 ``null``（用户点「清除」按钮）。

    **怎么区分「缺省」与「null」**：pydantic 的 ``model_fields_set``
    记录了请求里**实际出现过**的字段名。缺省时该字段不在里面；
    显式传 null 时它在里面而值是 None。
    """
    # 先算出要写什么——**没东西可写就不建行**。
    #
    # 建一行全空的凭据会让「这人的配置从哪来」的判断变复杂：到底是
    # 没配，还是配了但都被清空了。
    updates = _collect_updates(payload)
    if not updates:
        return await read_credentials(user, db)

    row = await ProviderCredentials.find_by_user(db, user.id)
    if row is None:
        row = ProviderCredentials(user_id=user.id, scope=SCOPE_USER)
        db.add(row)

    for field, value in updates.items():
        # **key 字段存密文**，base_url 与模型名明文存（它们不是秘密）。
        if field in _SECRET_FIELDS:
            value = encrypt_secret(value)
        setattr(row, field, value)

    await db.commit()
    await db.refresh(row)

    # 保存后**重新解析**再返回——用户要立刻看到「已生效」的状态，
    # 而不是「我提交了什么」。
    return await read_credentials(user, db)


def _collect_updates(payload: CredentialsUpdate) -> dict[str, str | None]:
    """把请求里的字段收成「要写的列 → 值」。

    返回空字典表示**没有东西要写**。

    值是 ``None`` 时表示「清空这一列」——它与「不改」不同，所以
    这里用 ``model_fields_set`` 区分：字段压根没出现在请求里就不管，
    出现了但值是 None 才是清空。
    """
    updates: dict[str, str | None] = {}
    provided = payload.model_fields_set
    for field in _WRITABLE_FIELDS:
        if field not in provided:
            # 缺省 = 不改。
            continue
        value = getattr(payload, field)
        if value is None:
            # 显式 null = 清空（回落到部署默认）。
            updates[field] = None
            continue
        cleaned = value.strip()
        if not cleaned:
            # 空串 = 没填 = 忽略。
            continue
        if field in _BASE_URL_FIELDS:
            # **base_url 是出站地址**——用户填的内网地址就是一条 SSRF
            # 通道（云 metadata 端点、内网服务都在射程内）。
            # 校验在这里做，写库之前。
            try:
                cleaned = validate_base_url(cleaned)
            except InvalidBaseUrlError as exc:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    f"{field} 不合法：{exc}",
                ) from exc
            assert cleaned is not None  # 非空串过不了 validate 的 None 分支
        updates[field] = cleaned
    return updates


__all__ = ["router"]
