"""凭据解析：DB（用户自己配的）优先，env（部署默认）兜底。

## 这个模块是凭据的**唯一**入口

外部 AI 能力的 key / base_url / 模型名，原先散落在十来个地方直接读
``get_settings()``。本模块把它们收口成一句话的语义：

    **用户配了就用用户的，没配就用部署环境的。**

这样「测试人员在页面上配自己的中转站」这件事才有确定的落点——
不会出现「某个调用点读 DB、某个调用点读 env，两边不一致」的情况。

**三层**（2026-11-24 加共享默认行）：

    用户行  >  共享默认行  >  环境变量

共享默认行是**全库一行**，运维用
``scripts/set_default_credentials.py`` 写入——所有没自己配的用户共用它。

## 为什么不改 config.py

``get_settings()`` 是**进程级单例**，读的是进程环境。它不可能知道
「当前这次请求是谁」。要按 user_id 区分，就得在调用点带上 user_id——
那正是本模块做的事。

## 为什么不缓存解析结果

解析要查 DB（**一次 SELECT** 取回用户行与共享默认行两行），而调用点
在请求热路径上（每次研究一次、每份资料一次）。但缓存会引入两难：

- 缓存 key 是什么？``user_id`` 不够——用户改了配置后缓存还在。
- 什么时候失效？

**结论：不缓存。** 一次 SELECT 在 SQLite 上是微秒级，而研究本身要跑
30-60 秒、模型调用要几十秒。多这一次查询换「改了配置立刻生效」，
这个取舍明显划算。

真正的缓存是 **client 本身**（连接池）——那层见 ``llm.py`` 的
``get_anthropic_client``，它按 (key, base_url) 分桶。
"""

from __future__ import annotations

import ipaddress
import logging
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlsplit

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.models.credentials import ProviderCredentials
from app.services.secret_store import SecretCryptoError, SecretDecryptError, decrypt_secret

logger = logging.getLogger(__name__)

ConfigSource = Literal["user", "default", "env", "none"]
"""一个配置值的来源。

- ``user``    —— 用户在设置页自己配的（DB 的用户行）
- ``default`` —— 共享默认行（DB 的 default 行，全库一行）
- ``env``     —— 部署环境变量里的（全局兜底）
- ``none``    —— 三层都没有
"""

# 会被 ``model_for`` 查角色覆盖的角色。
#
# **writer 不在其中**：writer 走主循环硬编码的 ``complex_model``
# （``anthropic_writer_model`` 这个配置项全仓无人读取——别被名字骗了）。
# 把 writer 加进来会让「角色覆盖」看起来能改 writer，实际改不了。
_MODEL_ROLES = ("supervisor", "researcher", "analyst", "summarizer")


@dataclass(frozen=True, slots=True)
class ResolvedCredentials:
    """某个用户最终生效的一组凭据。

    **每个字段都已经完成「DB 优先、env 兜底」的解析**——调用方拿到它
    就可以直接用，不需要再判断来源。
    """

    anthropic_api_key: str | None
    anthropic_base_url: str | None
    anthropic_complex_model: str
    anthropic_default_model: str
    tavily_api_key: str | None
    embedding_api_key: str | None
    embedding_base_url: str | None
    embedding_dimensions: int
    embedding_model: str
    """嵌入模型名——**只来自部署层，用户不能改**。

    ## 为什么用户不能改

    向量索引（``chunk_embeddings`` vec0 虚表）是**全库共享**的，维度
    写死在建表 DDL 里（1536）。改了模型就会出现**两套向量坐标系混在
    同一张表里**：新切片是模型 A 的向量，老切片是模型 B 的，而查询
    向量只有一个——余弦距离在混合坐标系里算出来没有意义。

    症状是**静默的**：检索质量下降，不报错。而重建索引的入口这个项目
    还没有（见 ``vectorstore.py``），用户改了就回不去了。

    嵌入的 **key 与端点**可以按用户配（那是「连到哪」）；
    **模型名**是「用什么坐标系」，必须全局一致。
    """

    # 按角色解析好的模型名。键是角色名（见 ``_MODEL_ROLES`` 与
    # ``"critic"``），值是最终生效的模型名。
    #
    # **预先解析好而不是让调用方现查**：角色覆盖来自 env，而 env 是
    # 进程级的——每个调用点现查就会各自判断一遍优先级，迟早有两处
    # 写得不一致。
    role_models: dict[str, str] = field(default_factory=dict)

    # 备胎模型链（逗号分隔的 alias 列表，按顺序尝试）。
    fallback_models: tuple[str, ...] = ()

    # ── 各值的来源（供「配置状态」接口展示）─────────────────
    anthropic_key_source: ConfigSource = "none"
    anthropic_base_url_source: ConfigSource = "none"
    tavily_key_source: ConfigSource = "none"
    embedding_key_source: ConfigSource = "none"
    embedding_base_url_source: ConfigSource = "none"

    # ── **用户自己配的** key（回显用）─────────────────────────
    #
    # ## 为什么单独存这一份
    #
    # 回显给页面的必须是**用户自己配的** key，不是「最终生效的值」。
    # 最终生效的值可能来自共享默认行或部署环境——那是**运维的密钥**，
    # 回显它等于把运维密钥发给每一个登录用户（argus 没有管理员角色，
    # 注册即得）。
    #
    # 所以这里单独存「用户层那一行的值」。用户没配 → None → 页面显示
    # 空框，但**功能上照样开箱即用**（解析时仍会落到共享默认）。
    #
    # ⚠️ 这三个字段**只给当前用户看**——它们是「你的 key」，不是
    # 「生效的 key」。
    user_anthropic_api_key: str | None = None
    user_tavily_api_key: str | None = None
    user_embedding_api_key: str | None = None
    user_anthropic_base_url: str | None = None
    user_embedding_base_url: str | None = None
    """**用户自己配的** base_url。

    为什么 base_url 也要单独存：base_url **不是密钥**，所以回显生效值
    本身没有泄漏问题。但前端要用「用户自己填过的那个 url」去做 key 与
    url 的配对回填——若用生效值（可能是共享默认层/部署层的中转站），
    用户的官方 key 就被绑到那个中转站上，密钥外泄。
    """

    def model_for(self, role: str) -> str:
        """取某个角色的模型。

        优先级与改动前的 ``llm.model_for`` 完全一致：

        1. **按角色覆盖**（``ANTHROPIC_{ROLE}_MODEL``）
        2. **critic** → complex_model（判定是复杂任务）
           **其余角色** → default_model

        区别只有一个：这里查的是**预先解析好的** ``role_models``，
        不再现场读 env。
        """
        return self.role_models.get(role, self.anthropic_default_model)

    @property
    def critic_model(self) -> str:
        """Critic（引用忠实度判定）实际用的模型。

        **单一真源**——critic 的型号只存在 ``role_models["critic"]``
        一处。以前它同时是个字段和 dict 里的一项，两处可能不一致：
        改了一处忘了改另一处，页面上显示的与实际调用的就分家了。
        """
        return self.role_models.get("critic", self.anthropic_complex_model)


def _clean(value: str | None) -> str | None:
    """去空白；空串当作 None。

    空串与 None 必须归一——``SecretStr("")`` 是「配了但没填」，
    页面回显时它会显示成「已配置」但实际调不通。
    """
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _normalize_base_url(value: str | None) -> str | None:
    """去掉尾部斜杠。

    ``base_url`` 后面要拼 ``/v1/messages``。尾部多一个斜杠会变成
    ``.../v1//messages``，中转站返回 404——而那种 404 的报错里完全
    看不出是斜杠的问题，排查一次要花半小时。
    """
    cleaned = _clean(value)
    if cleaned is None:
        return None
    return cleaned.rstrip("/")


def _source(
    user_value: str | None,
    default_value: str | None,
    env_value: str | None,
) -> ConfigSource:
    """这个值最终来自哪一层。

    三层依次查：用户行 → 共享默认行 → 环境变量。
    """
    if user_value:
        return "user"
    if default_value:
        return "default"
    if env_value:
        return "env"
    return "none"


def _key_source(
    effective: str | None,
    user_key: str | None,
    default_key: str | None,
    *,
    default_unusable: bool,
) -> ConfigSource:
    """生效的 key 实际来自哪一层。

    按生效值反查，而不是按「哪层有值」猜：成对解析和不可用层的跳过
    都可能让「有值的层」不是「生效的层」。
    """
    if effective is None:
        return "none"
    if effective == user_key:
        return "user"
    if not default_unusable and effective == default_key:
        return "default"
    return "env"


def _decrypt_or_none(ciphertext: str | None, label: str) -> tuple[str | None, bool]:
    """解密一个密文。返回 ``(值, 是否可解)``。

    ## 为什么不能把「解不开」当成「没配」

    「没配」= 往下一层回落（用共享默认 / 部署的 key）。
    「解不开」= **这一层有值，但读不出来**——回落等于**静默改用别人的
    key 去调用**，用户以为在用自己的账号额度，实际烧的是部署方的钱，
    而且界面上看不出发生过任何事。

    所以这两者必须分开：解不开时**不回落**，该层视为「不可用」。

    ## 为什么不直接抛

    主密钥轮换后整个设置页 500，用户连重新配都做不到——而那正是他需要
    做的事。降级（不回落 + 记警告 + 让页面显示异常）能让他继续操作。

    降级必须**记日志**：不记的话「密钥轮换了」这件事没有任何痕迹，
    症状只是「用户的 key 莫名其妙失效了」。
    """
    if not ciphertext:
        return None, True
    try:
        return decrypt_secret(ciphertext), True
    except SecretDecryptError as exc:
        logger.warning(
            "%s 解不开，该层按「不可用」处理——**不会**回落到下一层"
            "（多半是 CREDENTIALS_ENCRYPTION_KEY 换了）：%s",
            label,
            exc,
        )
        return None, False
    except SecretCryptoError as exc:
        # **主密钥本身坏了**（格式不对 / 不是合法 Fernet key）。
        #
        # 捕获基类——只捕获 SecretDecryptError 会让这一类直接 500，
        # 用户连重新配都做不到。
        #
        # 这里**可以**降级：DB 层的密文全都解不开，但 env 层是**明文**
        # （不受主密钥影响），仍然可用。所以降级成「DB 层不可用」，
        # env 层照常回落。
        logger.error(
            "%s 解不开——凭据加密主密钥本身有问题（不是这一行的问题）：%s",
            label,
            exc,
        )
        return None, False


# ── base_url 的 SSRF 校验 ──────────────────────────────────────
#
# **base_url 是用户填的，而请求是从服务端发出的**——它就是一条 SSRF 通道。
# 用户填 ``http://169.254.169.254/...``，服务端就会带着 API key 去打
# 云 metadata 端点；填内网地址就能打内网服务。
#
# 判据与 ``app/services/fetcher.py`` 一致（那是项目已有的 SSRF 政策）：
# 协议白名单 + 主机必须是公网 IP。

_ALLOWED_BASE_URL_SCHEMES = frozenset({"http", "https"})


class InvalidBaseUrlError(ValueError):
    """base_url 不合法——不能作为出站地址。"""


def validate_base_url(value: str | None) -> str | None:
    """校验并归一一个 base_url。**不合法就抛**。

    ## 为什么在这里校验

    base_url 是**用户填的**，而请求由**服务端发出**——填一个内网地址
    就是一条 SSRF 通道（云 metadata 端点、内网服务都在射程内）。

    判据与 ``app/services/fetcher.py`` 的 SSRF 政策一致：

    - 协议只能是 http/https（挡掉 ``file://`` 这类能读本地资源的）
    - 主机名要么是公网 IP，要么解析到公网 IP

    ## 为什么不做 DNS 解析检查

    ``fetcher.py`` 会解析 DNS（因为它要抓取，得知道最终连哪个 IP）。
    这里是**写入时**的一次性校验，且 base_url 通常是 IP 或固定域名——
    解析 DNS 会让「保存配置」变成一个慢操作，还多一个「解析结果会变」
    的 TOCTOU 窗口（校验时是公网，实际请求时可能已被改指内网）。

    所以这里只挡**字面上**就是内网地址的输入：IP 字面量、localhost、
    ``.local`` / ``.internal`` 这类内网专用后缀。域名的情况由部署者
    自己把关（他能配 base_url 就说明他有那台机器的访问权）。
    """
    cleaned = _normalize_base_url(value)
    if cleaned is None:
        return None

    parts = urlsplit(cleaned)
    if parts.scheme.lower() not in _ALLOWED_BASE_URL_SCHEMES:
        raise InvalidBaseUrlError("只支持 http/https 地址")

    host = parts.hostname
    if not host:
        raise InvalidBaseUrlError("地址缺少主机名")

    lowered = host.lower()
    # 字面上就是内网/本机的。
    if lowered in {"localhost", "localhost.localdomain"} or lowered.endswith(
        (".localhost", ".local", ".internal", ".home.arpa")
    ):
        raise InvalidBaseUrlError("地址不能指向本机或内网")

    # IP 字面量：判是不是公网。非 IP 字面量（域名）不在这里判——
    # 见 docstring 的「为什么不做 DNS 解析检查」。
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return cleaned

    if not ip.is_global or ip.is_multicast:
        raise InvalidBaseUrlError("地址不能指向本机或内网")

    return cleaned


def _pair(
    user_key: str | None,
    user_base_url: str | None,
    default_key: str | None,
    default_base_url: str | None,
    env_key: str | None,
    env_base_url: str | None,
    *,
    user_unusable: bool = False,
    default_unusable: bool = False,
) -> tuple[str | None, str | None]:
    """把「key + base_url」当**一对**解析，返回 (key, base_url)。

    ## 为什么必须成对

    key 与 base_url 描述的是**同一次调用**的两端：key 是给谁用的，
    base_url 是「谁」。

    混层的后果是**密钥外泄**，且不报错：

    - 部署配了中转站，用户只填了官方 key → 他的官方 key 被发到中转站
    - 用户只填了 base_url，部署的 key → 部署的 key 被发到用户指定的
      地址

    ## 规则：**自上而下找一层，那一层的 key 与 url 一起取——不跨层拼。**

    - 用户层配了任何一个 → 两个都从用户层取。
      - 用户配了 key 没配 url → (用户的 key, None)。那把 key 走官方
        端点，而不是发给部署者的中转站。
      - 用户配了 url 没配 key → (None, 用户的 url)。没有 key 就调不通，
        但**绝不会**把默认行的 key 发到用户的地址。
    - 用户层什么都没配 → 看默认层，规则同上。
    - 默认层也没配 → 用 env 的。

    ## 为什么 url 绝不能从下层继承（哪怕默认行是「自己人」）

    曾试过放宽成「用户配了 key 就继承默认行的 url」——理由是默认行
    是部署者配的整套配置，url 跟着走应该没问题。

    **但那样就把 env 的中转站也带进来了**：默认行没配 url、env 配了
    ``ANTHROPIC_BASE_URL=https://relay.example`` 时，用户的官方 key
    会被发到那个中转站。这正是本函数要防的第一种泄漏。

    区分不了「默认行的 url」与「env 的 url」——它们都是「下层的 url」，
    而下层的 url 可能指向**别人的服务器**（中转站）。

    所以规则保持严格成对。**「换 key 后调不通」的问题在别处解决**：
    前端改 key 时把配对的 url 一起提交（见
    ``apps/web/.../CredentialsPanel/index.tsx`` 的 ``PAIRED_URL_FIELD``），
    用户层于是存的是「自己的 key + 那个中转站的 url」——成对，且是
    用户自己确认过的组合。
    """
    # **不可用的层被跳过——但只跳过那一层。**
    #
    # 「解不开」（主密钥轮换）不是「没配」：**用户层**不可用时不能
    # 往下回落（那等于静默改用别人的 key 去调用，用户以为在用自己的
    # 额度，实际烧的是别人的钱）。
    #
    # 但**默认层**不可用时要**继续看 env**：env 层是明文（不受主密钥
    # 影响），它可能完全可用。把整个能力打成 None 会让「共享默认行
    # 坏了」变成「部署的 key 也不能用」——那是更大的损失。
    #
    # ⚠️ 两层的不可用是**各自独立**的：默认行里 anthropic 的密文坏了
    # 不该影响 tavily（同一行，但不同能力）。
    if user_unusable:
        # 用户层不可用 → 整个不回落（用户的配置坏了就是坏了）。
        return None, None
    if user_key or user_base_url:
        return user_key, user_base_url
    # 默认层不可用 → 跳过它，继续看 env。
    if not default_unusable and (default_key or default_base_url):
        return default_key, default_base_url
    return env_key, env_base_url


def _parse_fallback_models(raw: str) -> tuple[str, ...]:
    """把逗号分隔的备胎模型串解析成元组。

    空串 → 空元组（无备胎）。每项去空白，丢掉空项。
    """
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _role_models(settings: Settings, default_model: str, critic_model: str) -> dict[str, str]:
    """解析每个角色的模型名。

    角色覆盖只来自 env（**用户可配的角色只有 complex / default / critic**
    ——那三个是「任务级默认」；supervisor / analyst 这类角色覆盖是
    部署级的调参项，页面上不暴露）。

    critic 的回落链是 ``user_critic → env_critic → complex_model``，
    与改动前 ``model_for("critic")`` 的行为一致。
    """
    resolved: dict[str, str] = {"critic": critic_model}
    for role in _MODEL_ROLES:
        override = getattr(settings, f"anthropic_{role}_model", None)
        if isinstance(override, str) and override.strip():
            resolved[role] = override.strip()
        else:
            resolved[role] = default_model
    return resolved


async def resolve_credentials(
    db: AsyncSession,
    user_id: int,
) -> ResolvedCredentials:
    """解析某个用户最终生效的凭据。

    ``db`` 是请求级的 session —— **一次查询**取回两行（用户行 +
    共享默认行），**不缓存**（见模块 docstring 的理由）。

    一次查询而不是两次：解析在请求热路径上（``agent.py`` 每次研究一次、
    ``ingest.py`` 每份资料一次），分成两次 SELECT 就是每次调用多一次
    数据库往返。
    """
    user_row, default_row = await ProviderCredentials.find_user_and_default(db, user_id)
    # 值不在这里清洗——``_build`` 统一做（见那里的说明）。
    return _build(
        user_anthropic_key=user_row.anthropic_api_key if user_row else None,
        user_anthropic_base_url=user_row.anthropic_base_url if user_row else None,
        user_complex_model=user_row.anthropic_complex_model if user_row else None,
        user_default_model=user_row.anthropic_default_model if user_row else None,
        user_critic_model=user_row.anthropic_critic_model if user_row else None,
        user_tavily_key=user_row.tavily_api_key if user_row else None,
        user_embedding_key=user_row.embedding_api_key if user_row else None,
        user_embedding_base_url=user_row.embedding_base_url if user_row else None,
        default_anthropic_key=default_row.anthropic_api_key if default_row else None,
        default_anthropic_base_url=default_row.anthropic_base_url if default_row else None,
        default_complex_model=default_row.anthropic_complex_model if default_row else None,
        default_default_model=default_row.anthropic_default_model if default_row else None,
        default_critic_model=default_row.anthropic_critic_model if default_row else None,
        default_tavily_key=default_row.tavily_api_key if default_row else None,
        default_embedding_key=default_row.embedding_api_key if default_row else None,
        default_embedding_base_url=default_row.embedding_base_url if default_row else None,
    )


def resolve_env_credentials() -> ResolvedCredentials:
    """只按环境变量解析——**没有 DB 可用时**用。

    什么时候没有 DB：``run_agent`` 的 ``db`` 参数可以是 None
    （测试里大量场景不接数据库）。那时只能用部署默认配置。

    **共享默认行也读不到**（它也在 DB 里）——所以这条路没有默认层。
    """
    return _build(
        user_anthropic_key=None,
        user_anthropic_base_url=None,
        user_complex_model=None,
        user_default_model=None,
        user_critic_model=None,
        user_tavily_key=None,
        user_embedding_key=None,
        user_embedding_base_url=None,
    )


def _build(
    *,
    user_anthropic_key: str | None,
    user_anthropic_base_url: str | None,
    user_complex_model: str | None,
    user_default_model: str | None,
    user_critic_model: str | None,
    user_tavily_key: str | None,
    user_embedding_key: str | None,
    user_embedding_base_url: str | None,
    default_anthropic_key: str | None = None,
    default_anthropic_base_url: str | None = None,
    default_complex_model: str | None = None,
    default_default_model: str | None = None,
    default_critic_model: str | None = None,
    default_tavily_key: str | None = None,
    default_embedding_key: str | None = None,
    default_embedding_base_url: str | None = None,
) -> ResolvedCredentials:
    """把「用户层」「共享默认层」「环境层」合成最终生效的一组。

    抽出来是因为 ``resolve_credentials``（有 DB）与
    ``resolve_env_credentials``（无 DB）走的是**同一套优先级规则**——
    写两遍必然漂移。

    ## 优先级

    **用户行 > 共享默认行 > 环境变量。**

    ## 用户层的值在这里**再清一次**

    调用方（``resolve_credentials``）已经清过了，但**归一必须在这一层**——
    这里是所有路径的汇合处。漏在这里的后果：用户那格填了空格，
    ``"   "`` 是真值，于是 ``user or env`` 选中它，最终拿一把**全是空格
    的 key** 去调模型——那不是「没配」，是「配了一把废 key」，
    错误信息会指向别处。

    ## key 的解密也在这一层

    DB 里存的是**密文**（``enc:v1:`` 前缀）。解密必须发生在这里——
    这是所有路径的汇合处。密文不解密就参与 ``or`` 回落，
    选中的是密文而不是明文。
    """
    settings = get_settings()

    # ── 归一：去空白，空串当 None ────────────────────────────
    user_anthropic_key = _clean(user_anthropic_key)
    user_anthropic_base_url = _normalize_base_url(user_anthropic_base_url)
    user_complex_model = _clean(user_complex_model)
    user_default_model = _clean(user_default_model)
    user_critic_model = _clean(user_critic_model)
    user_tavily_key = _clean(user_tavily_key)
    user_embedding_key = _clean(user_embedding_key)
    user_embedding_base_url = _normalize_base_url(user_embedding_base_url)

    default_anthropic_key = _clean(default_anthropic_key)
    default_anthropic_base_url = _normalize_base_url(default_anthropic_base_url)
    default_complex_model = _clean(default_complex_model)
    default_default_model = _clean(default_default_model)
    default_critic_model = _clean(default_critic_model)
    default_tavily_key = _clean(default_tavily_key)
    default_embedding_key = _clean(default_embedding_key)
    default_embedding_base_url = _normalize_base_url(default_embedding_base_url)

    # ── 解密：DB 里的 key 是密文 ──────────────────────────────
    #
    # 解密失败（主密钥不对 / 密文被篡改）时**这一层不可用**，并记警告
    # ——不让整个接口 500。
    #
    # ## 「不可用」与「没配」是两件事
    #
    # - **没配** → 往下一层回落。这是设计。
    # - **不可用**（解不开）→ **不回落**。回落等于静默改用别人的 key
    #   去调用，用户以为在用自己的额度，实际烧的是别人的钱。
    #
    # 不可用的粒度是**按层 + 按能力**的：默认行里 anthropic 的密文坏
    # 了，不该影响 tavily（同一行，但不同能力）。
    #
    # ## 为什么降级而不是硬失败
    #
    # 最常见的触发场景是**主密钥轮换**：运维换了
    # ``CREDENTIALS_ENCRYPTION_KEY``，库里所有旧密文都解不开。若这里
    # 抛异常，整个 ``GET /settings/credentials`` 500——设置页整个挂
    # 掉，用户**连重新配都做不到**（那正是他需要做的事）。
    #
    # ⚠️ 但「不回落」有个代价：**主密钥轮换后，在恢复之前没有任何凭据
    # 可用**（连 env 层的那把也不回落）——恢复主密钥才是解法，不是
    # 「让用户重新填一次」。
    #
    # ## 为什么不静默
    #
    # 降级要**记日志**。不记的话「密钥轮换了」这件事没有任何痕迹，
    # 而症状是「用户的 key 莫名其妙失效了」——排查成本极高。
    user_anthropic_key, user_anthropic_ok = _decrypt_or_none(
        user_anthropic_key, "用户层的 Anthropic key"
    )
    user_tavily_key, user_tavily_ok = _decrypt_or_none(user_tavily_key, "用户层的 Tavily key")
    user_embedding_key, user_embedding_ok = _decrypt_or_none(
        user_embedding_key, "用户层的嵌入 key"
    )
    default_anthropic_key, default_anthropic_ok = _decrypt_or_none(
        default_anthropic_key, "默认行的 Anthropic key"
    )
    default_tavily_key, default_tavily_ok = _decrypt_or_none(
        default_tavily_key, "默认行的 Tavily key"
    )
    default_embedding_key, default_embedding_ok = _decrypt_or_none(
        default_embedding_key, "默认行的嵌入 key"
    )

    # 「解不开」的那一项不可用——**不往下回落**。见 `_pair` 里的说明。
    #
    # ⚠️ **按能力分开判断**：anthropic 的 key 解不开，**不该**让 tavily
    # 也失效（它们是独立的能力）。合成一个「用户层整体不可用」的
    # 标记会让一把坏 key 拖垮所有能力。
    user_anthropic_unusable = not user_anthropic_ok
    user_tavily_unusable = not user_tavily_ok
    user_embedding_unusable = not user_embedding_ok
    default_anthropic_unusable = not default_anthropic_ok
    default_tavily_unusable = not default_tavily_ok
    default_embedding_unusable = not default_embedding_ok

    env_anthropic_key = (
        _clean(settings.anthropic_api_key.get_secret_value())
        if settings.anthropic_api_key
        else None
    )
    env_anthropic_base_url = _normalize_base_url(settings.anthropic_base_url)
    env_tavily_key = (
        _clean(settings.tavily_api_key.get_secret_value()) if settings.tavily_api_key else None
    )
    env_embedding_key = (
        _clean(settings.embedding_api_key.get_secret_value())
        if settings.embedding_api_key
        else None
    )
    env_embedding_base_url = _normalize_base_url(settings.embedding_base_url)

    # ── key 与 base_url 必须**成对**解析 ──────────────────────
    #
    # 为什么不能各自独立回落（`user_key or env_key` + `user_url or env_url`）：
    #
    # 部署配了 `ANTHROPIC_BASE_URL=https://relay.example`（中转站的 key
    # 在 env 里）。用户 A 只在页面上填了 `anthropic_api_key`（他以为是
    # 官方 key）。独立回落会得到 **key=用户的官方 key、url=中转站**——
    # 于是他的官方 key 被发到中转站operator手里。**没有任何报错。**
    #
    # 反过来更糟：用户只填了 `base_url=https://attacker.example`，
    # 部署的 env key 会被发到那个地址。
    #
    # 所以规则是：**自上而下找一层，那一层的 key 与 url 一起取。**
    # 用户层没配 key 时 base_url 也留空（走官方端点）——那把 key 本来
    # 就是给官方端点用的。
    anthropic_key, anthropic_base_url = _pair(
        user_anthropic_key,
        user_anthropic_base_url,
        default_anthropic_key,
        default_anthropic_base_url,
        env_anthropic_key,
        env_anthropic_base_url,
        user_unusable=user_anthropic_unusable,
        default_unusable=default_anthropic_unusable,
    )
    embedding_key, embedding_base_url = _pair(
        user_embedding_key,
        user_embedding_base_url,
        default_embedding_key,
        default_embedding_base_url,
        env_embedding_key,
        env_embedding_base_url,
        user_unusable=user_embedding_unusable,
        default_unusable=default_embedding_unusable,
    )
    # Tavily 没有配对的 url，所以是**独立的回落链**——但「不可用的层
    # 被跳过」的规则同样适用（见 `_pair` 里的说明）：
    # - 用户层不可用 → **不回落**（用户的配置坏了就是坏了，不能改用
    #   别人的 key）
    # - 默认层不可用 → **跳过它**，继续看 env（env 是明文，不受主密钥
    #   影响，很可能可用）
    if user_tavily_unusable:
        tavily_key = None
    elif user_tavily_key:
        # 必须排在默认层判断之前：默认行坏了不能盖掉用户自己的 key。
        tavily_key = user_tavily_key
    elif default_tavily_unusable:
        tavily_key = env_tavily_key
    else:
        tavily_key = default_tavily_key or env_tavily_key

    complex_model = (
        user_complex_model or default_complex_model or settings.anthropic_complex_model
    )
    default_model = (
        user_default_model or default_default_model or settings.anthropic_default_model
    )
    # critic 的回落链：**用户配的 critic → 用户配的 complex → 默认行的 critic → 默认行的 complex → env 的 critic → env 的 complex**。
    #
    # 顺序要紧：用户配了 complex 却没配 critic 时，critic 必须跟着用户的
    # complex 走——不然用户「换了个模型」，critic 还在用 env 里那个旧的，
    # 而且页面上看不出来（critic 与 writer 的型号不同 = 表面正常）。
    #
    # 两种配法都要「用户优先」：用户配了 complex 时，更低层的 critic
    # 覆盖**不再适用**——那是部署者给默认那套配的，不是给用户这套配的。
    # 于是更低的 critic 只在**用户什么都没配**时才生效。
    if user_critic_model:
        critic_model = user_critic_model
    elif user_complex_model:
        critic_model = user_complex_model
    elif default_critic_model:
        critic_model = default_critic_model
    elif default_complex_model:
        critic_model = default_complex_model
    else:
        critic_model = settings.anthropic_critic_model or complex_model

    return ResolvedCredentials(
        anthropic_api_key=anthropic_key,
        anthropic_base_url=anthropic_base_url,
        anthropic_complex_model=complex_model,
        anthropic_default_model=default_model,
        tavily_api_key=tavily_key,
        embedding_api_key=embedding_key,
        embedding_base_url=embedding_base_url,
        embedding_dimensions=settings.embedding_dimensions,
        embedding_model=settings.embedding_model,
        role_models=_role_models(settings, default_model, critic_model),
        fallback_models=_parse_fallback_models(settings.anthropic_fallback_models),
        # **用户自己配的** key（回显用）。见 dataclass 里的注释——
        # 回显的是「你的 key」，不是「生效的 key」。
        user_anthropic_api_key=user_anthropic_key,
        user_tavily_api_key=user_tavily_key,
        user_embedding_api_key=user_embedding_key,
        user_anthropic_base_url=user_anthropic_base_url,
        user_embedding_base_url=user_embedding_base_url,
        # source 报的是「最终生效的值来自哪一层」——没有生效的值时报 "none"。
        anthropic_key_source=_key_source(
            anthropic_key,
            user_anthropic_key,
            default_anthropic_key,
            default_unusable=default_anthropic_unusable,
        ),
        anthropic_base_url_source=_source(
            user_anthropic_base_url, default_anthropic_base_url, env_anthropic_base_url
        ),
        tavily_key_source=_key_source(
            tavily_key,
            user_tavily_key,
            default_tavily_key,
            default_unusable=default_tavily_unusable,
        ),
        embedding_key_source=_key_source(
            embedding_key,
            user_embedding_key,
            default_embedding_key,
            default_unusable=default_embedding_unusable,
        ),
        embedding_base_url_source=_source(
            user_embedding_base_url, default_embedding_base_url, env_embedding_base_url
        ),
    )
