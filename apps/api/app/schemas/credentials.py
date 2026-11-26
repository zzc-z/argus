"""用户凭据配置的请求/响应模型。

## 响应**会回显密钥内容**

这是本项目的明确取舍：设置页要在输入框里**预填当前生效值**，用户
才看得见自己配的是什么、默认的是什么。少了回显，用户面对三个空框，
完全不知道现状。

前提是**只有登录用户能拿到**——接口挂在 ``CurrentUser`` 依赖后面，
而 key 本来也只对登录用户生效。

⚠️ 与「浏览器历史 / devtools / 截屏」的取舍：回显的 key 会出现在
这些地方。这是「用户看得见自己的配置」换来的代价 knowingly 接受。

## 请求里怎么表达「不改这一项」

``PUT`` 是**部分更新**：字段缺省 = 不改；字段传 ``null`` = 清空
（回落到共享默认 / 部署默认）；字段传值 = 设成这个值。

**空字符串不等于「清空」**——它被当成「没填」，跳过。那是因为前端
的输入框在用户没动过时也会提交空串，把「没动」当成「清空」会让
用户不小心把配好的 key 清掉。
"""

from pydantic import BaseModel, Field

from app.services.credentials import ConfigSource


class CredentialItem(BaseModel):
    """一项凭据的状态。

    ## ``configured`` 与 ``source`` 的区别

    - ``configured`` —— **最终生效的值**存在吗。这个永远准确。
    - ``source`` —— **那一层**有没有这个值。它是**逐层独立**判断的。

    两者可能不一致：成对解析（key 与 base_url 必须来自同一层）会丢弃
    某些层的值。典型场景——用户层配了 key 没配 url、共享默认层两者都有：
    ``configured`` 是 False（生效的 url 是 None），而 ``source`` 报
    ``default``（那一层确实有 url）。

    要判断「生效的值来自哪层」，看 ``configured`` + 实际返回值，不要
    只看 ``source``。
    """

    configured: bool = Field(description="最终生效的值存在吗")
    source: ConfigSource = Field(
        description="那一层有没有这个值：user / default / env / none"
        "（逐层判断，可能与最终生效值不一致）"
    )


class CredentialsResponse(BaseModel):
    """当前用户的凭据配置状态。"""

    anthropic_api_key: CredentialItem = Field(description="Anthropic API key")
    anthropic_base_url: CredentialItem = Field(description="中转站地址")
    tavily_api_key: CredentialItem = Field(description="Tavily API key")
    embedding_api_key: CredentialItem = Field(description="嵌入服务 API key")
    embedding_base_url: CredentialItem = Field(description="嵌入服务端点")

    # ── 回显当前生效的值 ────────────────────────────────
    #
    # **页面要把这些填进输入框**——用户看得见当前生效的是什么，
    # 才知道「留空 = 不改」到底指什么。
    #
    # 密钥也回显（见下）：设置页要能预填 key，否则用户面对三个空框，
    # 完全不知道现状。

    # ⚠️ **只回显「用户自己配的」key。**
    #
    # 生效的 key 可能来自共享默认行或部署环境——那是**运维的密钥**，
    # 回显它等于发给每个登录用户（argus 没有管理员角色，注册即得）。
    #
    # 用户没配过时这里返回**等长占位串**（只露末 4 位），不是
    # 明文——页面据此能看出「这一格有值」，但拿不到运维的密钥。
    anthropic_api_key_value: str | None = Field(
        default=None, description="用户自己配的 Anthropic API key（他人配的返回占位串）"
    )
    tavily_api_key_value: str | None = Field(
        default=None, description="用户自己配的 Tavily API key（他人配的返回占位串）"
    )
    embedding_api_key_value: str | None = Field(
        default=None, description="用户自己配的嵌入服务 API key（他人配的返回占位串）"
    )

    # ── 哪些 `*_value` 是**占位串**而非真值 ──────────────────
    #
    # ## 为什么必须显式标记，而不是靠值的样子猜
    #
    # 占位串形如 ``••••••••abcd``。若前端靠「开头是不是 •」来识别，
    # 就有两个问题：
    #
    # 1. **掩码可能被当成真 key 提交**——用户碰一下输入框，``••••••••abcd``
    #    就进了 payload，后端加密存成用户的 key，之后每次调用都用这把
    #    假 key，401 且界面显示「已配置」。
    # 2. 靠字符形状做协议约定，格式一改就静默失效。
    #
    # 显式标记后前端能：显示占位但**不让它进 payload**（提交时发
    # ``null`` 表示「我没配，用共享默认」）。
    masked_key_fields: list[str] = Field(
        default_factory=list,
        description="哪些 key 的值是占位串（不是真值）。取值："
        "anthropic_api_key / tavily_api_key / embedding_api_key",
    )
    anthropic_base_url_value: str | None = Field(
        default=None,
        description="当前生效的 Anthropic 中转站地址（用户的 key 解不开时回显用户保存的地址）",
    )
    embedding_base_url_value: str | None = Field(
        default=None,
        description="当前生效的嵌入服务端点（用户的 key 解不开时回显用户保存的地址）",
    )

    # ── **用户自己配的** base_url ────────────────────────────
    #
    # base_url 不是密钥，回显生效值没有泄漏问题。但前端要用「用户自己
    # 填过的那个 url」做 key 与 url 的配对回填——若用生效值（可能是
    # 共享默认层/部署层的中转站），用户的官方 key 就被绑到那个中转站上，
    # 密钥外泄。
    user_anthropic_base_url: str | None = Field(
        default=None, description="用户自己配的 Anthropic 中转站地址"
    )
    user_embedding_base_url: str | None = Field(
        default=None, description="用户自己配的嵌入服务端点"
    )
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
