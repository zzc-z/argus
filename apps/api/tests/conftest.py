"""pytest 全局fixture。

核心约定：**测试绝不碰开发数据库**。
所有需要库的测试用 ``db_session`` fixture，它跑在独立的内存 SQLite 上，
每个测试结束后整个库丢弃。这样pytest 可以反复跑、可以并发跑，
不会污染 argus.db，也不会因为 dev 库里的残留数据而随机失败。
"""

from collections.abc import AsyncGenerator, AsyncIterator, Iterator
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings
from app.db import _enable_sqlite_foreign_keys, get_session
from app.gateway.auth import OAUTH_STATE_COOKIE
from app.main import app
from app.models import Base
from app.services.agent import TurnChunk, TurnResult
from app.services.llm import LLMNotConfiguredError, get_anthropic_client, get_tavily_client
from app.services.vectorstore import create_vector_engine, get_vector_engine

pytest_plugins: list[str] = []


def turn_chunks(result: TurnResult) -> list[TurnChunk]:
    """把一个 ``TurnResult`` 转成 ``_run_turn`` 会 yield 的片段序列。

    ``_run_turn`` 现在是异步生成器（边收上游 delta 边发），所以打桩时
    不能只返回一个 ``TurnResult``——必须 yield 出同样的片段序列，
    否则测试测的就不是真实调用形态了。

    正文先于 result：与真实顺序一致（正文增量在流中到达，result 是
    流结束时的收尾）。
    """
    chunks: list[TurnChunk] = []
    if result.text:
        chunks.append(TurnChunk(kind="text", text=result.text))
    chunks.append(TurnChunk(kind="result", result=result))
    return chunks


async def collect_turn(client: Any, messages: Any, tools: Any) -> TurnResult:
    """跑完 ``_run_turn`` 这个生成器，返回它的 ``TurnResult``。

    测试大多只关心整轮结果（usage / stop_reason / content），不关心
    中间发了哪些片段——这个辅助把生成器跑到底、取出收尾的那块。
    """
    from app.services.agent import _run_turn

    result: TurnResult | None = None
    async for chunk in _run_turn(client, messages, tools):
        if chunk.kind == "result":
            result = chunk.result
    assert result is not None, "_run_turn 没有产出 result 片段"
    return result


def _tavily_unavailable() -> object:
    """``get_tavily_client`` 的测试替身：永远报「未配置」。

    ## 覆盖范围（别当成全局保证）

    它替换的是 ``app.services.tools`` 里那份**模块级引用**。全仓只有
    ``tools.py:25`` 从 llm 导入它，所以 agent 路径（``available_tools`` 与
    ``execute_tool`` 都按模块全局查找）被覆盖到了。

    但 ``app.services.llm.get_tavily_client`` 本身**没被换**。改它不行：
    ``llm.clear_client_cache()``（llm.py:89）按名字查全局并调
    ``.cache_clear()``，换成普通函数会让 ``test_llm_client`` 的 setup 报
    AttributeError。所以 llm 层要真调 Tavily 的用例得自己管——目前
    ``test_llm_client.py`` 靠把自己的 ``get_settings`` 换成缺 key 版本来
    达到同样效果。**新加 llm 层正向用例时必须重复那一步**，否则会拿到
    真客户端并真的发请求（症状是某个用例报 Tavily 的 4xx，看着像产品 bug）。
    """
    raise LLMNotConfiguredError("TAVILY_API_KEY 未配置")


@pytest.fixture(autouse=True)
def _reset_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """确保测试不依赖真实 env vars。

    ## 为什么隔离点选在 monkeypatch 而不是配置层

    pydantic-settings 的配置来自**文件**，不是进程环境——所以
    ``monkeypatch.delenv("TAVILY_API_KEY")`` 对它完全无效。2026-10-13
    配上真 key 后症状是 ``test_tool_use_produces_tool_call_events`` 报
    ``BadRequestError: Query is too short``：看着像产品 bug，其实是测试
    在联网（它用的查询词是 ``x``）。

    试过又放弃的三条路（都实测炸过，记下来免得重走）：

    1. ``setenv("TAVILY_API_KEY", "")`` —— pydantic-settings 对空串的语义
       不等于「未设置」，``_require`` 拿到的仍是真值，36 个用例挂掉。
    2. 把 ``Settings.env_file`` 指向 ``.env.example`` —— 那里
       ``JWT_SECRET_KEY`` 等是占位符，73 个用例当场炸。
    3. 给 ``SettingsConfigDict`` 加 ``env_file_factory`` —— 这个 key 不存在。

    剩下唯一可行的是替换 ``tools`` 模块里那份引用，见下方注释。

    要用 Tavily 的用例自己 monkeypatch 回去（``test_tools._with_tavily_key``）；
    它只换 client，真正发请求的 ``_search`` 仍需各自 mock。

    ## 为什么还要 cache_clear

    三个 ``lru_cache(maxsize=1)`` 单例：``get_settings``（config.py:124）
    与 ``get_anthropic_client`` / ``get_tavily_client``（llm.py:45,70）。
    第一次调用就把值缓存了，之后 ``monkeypatch.setenv`` 对它们**完全无效**。

    只清 ``get_settings`` 不够——``get_tavily_client`` 同样会缓存住带 key
    的客户端，``available_tools`` 拿到的仍是「已配置」。症状是
    ``test_tool_use_produces_tool_call_events`` 断言「搜索工具未配置」
    却拿到「工具内部错误」（它真的发了一次请求，被 Tavily 拒了）。
    config.py 早就写了「测试里 cache_clear() 可重置」，但没人真的调。

    ## 这条 cache_clear 覆盖不到的（已知）

    ``app/db.py:36`` 与 ``app/main.py:27`` 在**导入期**就把
    ``get_settings()`` 绑进模块全局，``cache_clear`` 对它们无效。
    写「setenv + cache_clear 就该生效」的测试会绿，但生产路径用的还是
    导入期那份。目前不涉及 Tavily 所以没炸——别拿这个 fixture 当万能药。
    """
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("LOG_LEVEL", "warning")
    # 单例缓存：第一次调用就把值锁住，之后 setenv / setattr 对它无效。
    # 三个都要清——只清 get_settings 的话 get_tavily_client 仍握着带 key
    # 的客户端（症状：单跑通过、全量跑失败）。
    get_settings.cache_clear()
    get_anthropic_client.cache_clear()
    get_tavily_client.cache_clear()
    # get_tavily_client 默认抛「未配置」。这是**唯一**能让测试不联网的
    # 钩子：pydantic-settings 的配置来自文件而不是进程环境，清掉进程里的
    # TAVILY_API_KEY 对它无效；而把 env_file 整体换掉又会让 JWT_SECRET_KEY
    # 之类测试确实需要的配置一起变占位符（实测 73 个用例当场炸）。
    #
    # 要用 Tavily 的测试自己 monkeypatch 回去（见 test_tools._with_tavily_key）。
    #
    # 只替换 **tools 模块里那份引用**，不碰 llm 模块的属性：后者被
    # ``llm.clear_client_cache()`` 按名字查找（llm.py:89），换成普通函数
    # 会让 test_llm_client 的 setup 直接报 AttributeError。tools 侧是
    # ``from ... import get_tavily_client`` 的独立引用，替换它不影响别处。
    monkeypatch.setattr(
        "app.services.tools.get_tavily_client",
        _tavily_unavailable,
    )


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """内存 SQLite + 完整 schema，测试结束即销毁。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    # 与 app.db 同理：SQLite 默认不执行外键，不开 pragma 的话
    # CASCADE 相关的测试会「通过」而实际什么都没删。
    _enable_sqlite_foreign_keys(engine.sync_engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def shared_db(tmp_path) -> AsyncGenerator[tuple[AsyncSession, AsyncEngine], None]:
    """业务表与向量索引在**同一个** SQLite 文件里。

    混合检索的 ``source_ids`` 过滤是在向量库的 ``document_chunks`` 上做子查询，
    两边不同库的话子查询永远查不到行——症状是「索引明明有数据却一条都检索不到」。
    所以这两个 fixture 必须共用一个库，不能各自造。
    """
    db_path = tmp_path / "shared.db"
    # 用 create_vector_engine 而不是 create_async_engine：它加载了 sqlite-vec 扩展，
    # 而 vec0 虚表建在同一文件里。普通 engine 建 document_chunks 没问题，
    # 但一旦碰到 ensure_vector_table 就报 "no such module: vec0"。
    engine = create_vector_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session, engine

    await engine.dispose()


@pytest.fixture
async def api_db(db_session: AsyncSession) -> AsyncGenerator[AsyncSession, None]:
    """把路由里的 get_session 依赖换成测试库，避免写 dev 库。

    **向量 engine 也要一起换。** ``get_vector_engine()`` 是模块级函数，
    直接调用的话 ``dependency_overrides`` 对它无效——于是路由里拿到的
    向量库会指向开发者的真实 ``argus.db``，测试会在那边建虚表、读数据，
    而全部测试依然绿灯。

    这是 Day 11 CR 抓过两次的同一类问题（第一次是 ``get_session``，
    第二次是这个），所以两条一起覆盖，缺一条就等于没修。
    """
    assert db_session is not None  # 让 mypy 认出这是个 async fixture

    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = _override
    # 向量库必须与业务表同库：混合检索的 source_ids 过滤是在向量库的
    # document_chunks 上做子查询，两边不同库的话子查询永远查不到行。
    app.dependency_overrides[get_vector_engine] = lambda: db_session.get_bind()
    try:
        yield db_session
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def client(api_db: AsyncSession) -> Iterator[TestClient]:
    """走测试库的 TestClient。带上 api_db 参数纯粹是为了触发它。"""
    with TestClient(app) as c:
        yield c


@pytest.fixture
def github_state(client: TestClient) -> str:
    """跑一次 login 端点，拿到合法 state 并留在 client 的 cookie 里。

    登录流程中间态（state + PKCE verifier）存在签名 cookie 中，
    所以「发起登录」和「校验 state」必须在同一个 TestClient 上。
    """
    resp = client.get("/api/v1/auth/github/login", follow_redirects=False)
    return parse_qs(urlparse(resp.headers["location"]).query)["state"][0]
