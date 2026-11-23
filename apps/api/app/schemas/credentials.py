"""用户凭据配置的请求/响应模型。

## 响应**永不回显密钥内容**

只报「配了没有」与「来自哪一层」：

- ``configured`` —— 最终生效的值存在吗
- ``source``    —— ``user``（用户自己配的）/ ``env``（部署默认）/ ``none``

前端要显示的是「已配置（来自我的设置）」还是「未配置」，**不是**那把
key 本身。把密钥放进响应里等于把它写进浏览器历史、devtools 面板、
以及任何截屏。

## 请求里怎么表达「不改这一项」

``PUT`` 是**部分更新**：字段缺省 = 不改；字段传 ``null`` = 清空
（回落到部署默认）；字段传值 = 设成这个值。

**空字符串不等于「清空」**——它被当成「没填」，跳过。那是因为前端
的输入框在用户没动过时也会提交空串，把「没动」当成「清空」会让
用户不小心把配好的 key 清掉。
"""

from pydantic import BaseModel, Field

from app.services.credentials import ConfigSource


class CredentialItem(BaseModel):
    """一项凭据的状态。**不含密钥内容。**"""

    configured: bool = Field(description="最终生效的值存在吗")
    source: ConfigSource = Field(description="值来自哪一层：user / env / none")


class CredentialsResponse(BaseModel):
    """当前用户的凭据配置状态。"""

    anthropic_api_key: CredentialItem = Field(description="Anthropic API key")
    anthropic_base_url: CredentialItem = Field(description="中转站地址")
    tavily_api_key: CredentialItem = Field(description="Tavily API key")
    embedding_api_key: CredentialItem = Field(description="嵌入服务 API key")
    embedding_base_url: CredentialItem = Field(description="嵌入服务端点")

    # ── 非密钥字段：直接回显当前生效的值 ──────────────────
    #
    # **base_url 与模型名不是秘密**，回显它们是为了让页面能预填输入框——
    # 用户看到「当前中转站是 X」，而不是一个空框加一句「部署默认」。
    #
    # 密钥**不回显**（见 CredentialItem）——那是唯一需要藏起来的。

    anthropic_base_url_value: str | None = Field(
        default=None, description="当前生效的 Anthropic 中转站地址"
    )
    embedding_base_url_value: str | None = Field(default=None, description="当前生效的嵌入服务端点")
    anthropic_complex_model: str = Field(description="复杂任务的模型名")
    anthropic_default_model: str = Field(description="简单任务的模型名")
    anthropic_critic_model: str = Field(description="Critic（引用判定）的模型名")
    embedding_model: str = Field(description="嵌入模型名（部署级，用户不可改）")

    critic_equals_writer: bool = Field(
        description="Critic 与 Writer 是否同一个模型（自偏好偏差风险）"
    )


class CredentialsUpdate(BaseModel):
    """要保存的凭据。**字段缺省 = 不改。**

    ``None`` = 清空（回落到部署默认）。空字符串 = 忽略（当作没填）。
    """

    model_config = {"extra": "forbid"}
    """**拒绝未知字段。**

    pydantic 默认是 ``extra="ignore"``——多传的字段被静悄悄丢掉。
    对写入接口来说那是错的：用户把 ``tavily_api_key`` 拼成
    ``tavily_key``，接口返回 200，用户以为配好了，实际什么都没存。
    报错（422）让用户看见自己拼错了。
    """

    anthropic_api_key: str | None = Field(default=None, description="Anthropic API key")
    anthropic_base_url: str | None = Field(default=None, description="中转站地址")
    tavily_api_key: str | None = Field(default=None, description="Tavily API key")
    embedding_api_key: str | None = Field(default=None, description="嵌入服务 API key")
    embedding_base_url: str | None = Field(default=None, description="嵌入服务端点")

    anthropic_complex_model: str | None = Field(default=None, description="复杂任务的模型名")
    anthropic_default_model: str | None = Field(default=None, description="简单任务的模型名")
    anthropic_critic_model: str | None = Field(default=None, description="Critic 的模型名")


__all__ = [
    "CredentialItem",
    "CredentialsResponse",
    "CredentialsUpdate",
]
