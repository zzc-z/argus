"""应用配置：唯一允许直接读取环境变量的地方。

所有其他模块必须通过 ``get_settings()`` 拿配置，不要直接 import 进程 env。
"""

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """运行时配置。

    字段顺序就是 .env.example 的顺序——保持一致便于人对照。
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,  # 允许 GITHUB_OAUTH_CLIENT_ID 和 github_oauth_client_id 都能识别
        extra="ignore",
    )

    # ── 运行时 ────────────────────────────────────────────────
    app_env: str = Field(default="dev", description="dev | test | prod")
    debug: bool = Field(default=False)
    api_host: str = Field(default="127.0.0.1")
    api_port: int = Field(default=8000)
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # ── 数据库 ────────────────────────────────────────────────
    # 默认 sqlite 是为了 W1 Day 2 上半不依赖 Docker。
    # 真 Postgres 切换：DATABASE_URL=postgresql+asyncpg://user:pwd@host:5432/db
    database_url: str = Field(
        default="sqlite+aiosqlite:///./argus.db",
        description="SQLAlchemy async URL（必须带 +asyncpg 或 +aiosqlite）",
    )

    # ── Redis ─────────────────────────────────────────────────
    # W1 Day 2 上半用 fakeredis 内存版；Docker 装好后改 redis://localhost:6379/0
    redis_url: str = Field(default="memory://")

    # ── OAuth (GitHub) ────────────────────────────────────────
    # SecretStr：打印时只显示 '**********'，避免日志/traceback 泄露。
    github_oauth_client_id: str | None = Field(default=None)
    github_oauth_client_secret: SecretStr | None = Field(default=None)
    github_oauth_callback_url: str = Field(
        default="http://localhost:8000/auth/github/callback",
    )

    # ── JWT / Session ──────────────────────────────────────────
    # argus 自己的登录票据。与 OAuth secret 必须独立——两者泄露后果不同，
    # 共用一把钥匙等于把两把锁做成一把。
    # 生成：python3 -c "import secrets; print(secrets.token_urlsafe(48))"
    jwt_secret_key: SecretStr | None = Field(default=None)
    jwt_algorithm: str = Field(default="HS256")
    jwt_expire_seconds: int = Field(default=7 * 24 * 60 * 60)  # 7 天
    # dev 走 http://localhost，Secure cookie 不会被浏览器带上，必须 false。
    # 生产部署改true——显式配置而非按环境自动切换，避免线上漏改。
    cookie_secure: bool = Field(default=False)
    # 登录成功后把浏览器送回的前端地址
    frontend_base_url: str = Field(default="http://localhost:3000")

    # ── LLM ─────────────────────────────────────────────────────
    anthropic_api_key: SecretStr | None = Field(default=None)
    openai_api_key: SecretStr | None = Field(default=None)

    # Tavily（联网搜索工具）。与 LLM key 独立——它只买「搜索」这一项能力，
    # 泄露后果也比 LLM key 轻。没填时 tavily_search 工具返回错误字符串给模型，
    # agent 循环照常跑完，只是搜不到东西。
    tavily_api_key: SecretStr | None = Field(default=None)

    # 中转站 base_url：留空走 Anthropic 官方（https://api.anthropic.com）。
    # 用第三方中转站时填对应地址，例如 https://llmapi.pro。
    # 注意：中转站返回的 model 实际身份不一定是字段名标称的版本——
    # ANTHROPIC_*_MODEL 字段值必须用中转站能认的 alias，否则请求会 404。
    anthropic_base_url: str | None = Field(default=None)

    # 任务级默认 model（complex = 复杂任务 / default = 简单任务）。
    # sprint-plan.md：Supervisor / Researcher / Writer 走 complex；
    # Analyst / Critic / Summarizer 走 default。
    anthropic_complex_model: str = Field(default="claude-sonnet-5")
    anthropic_default_model: str = Field(default="claude-haiku-4-5")

    # 按 agent 路由的可选覆盖（留空则退到 complex_model / default_model）。
    # Day 3 单 agent 阶段可只填 anthropic_complex_model，其他 6 个留空。
    anthropic_supervisor_model: str | None = Field(default=None)
    anthropic_researcher_model: str | None = Field(default=None)
    anthropic_writer_model: str | None = Field(default=None)
    anthropic_analyst_model: str | None = Field(default=None)
    anthropic_critic_model: str | None = Field(default=None)
    anthropic_summarizer_model: str | None = Field(default=None)

    # ── Embedding（RAG 检索用）────────────────────────────────
    # 嵌入模型与聊天模型是两回事：它把文字变成 1536 个数字，不生成内容。
    # OpenAI 官方只收境外信用卡，所以默认走阿里云百炼的 OpenAI 兼容端点
    # （支付宝可付，新用户送 100 万 token，90 天有效）。
    # 想换回官方把 base_url 留空、key 换成 sk- 开头的即可，代码不用动。
    embedding_api_key: SecretStr | None = Field(default=None)
    embedding_base_url: str | None = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        description="OpenAI 兼容端点。留空则用官方 https://api.openai.com/v1",
    )
    embedding_model: str = Field(
        default="text-embedding-v4",
        description="百炼的 text-embedding-v4 可选维度 1536；"
        "OpenAI 官方对应模型名是 text-embedding-3-small",
    )
    embedding_dimensions: int = Field(
        default=1536,
        description="必须与 vectorstore.EMBEDDING_DIM 一致——维度写在建表 DDL 里，"
        "改了要重建索引表",
    )

    # 原始文件存哪。存文件是因为摄取失败后用户要能重跑（可能只是没配 key），
    # 不存就只能让用户重新上传。W3 换 S3/MinIO 时只改 services/storage.py。
    source_upload_dir: str = Field(
        default="./uploads",
        description="上传文件目录，相对路径以 process cwd 为基准",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """返回进程内单例 Settings。

    用 lru_cache 避免每次调用都重读 .env。测试里 ``get_settings.cache_clear()`` 可重置。
    """
    return Settings()
