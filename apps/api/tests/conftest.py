"""pytest 全局fixture。

核心约定：**测试绝不碰开发数据库**。
所有需要库的测试用 ``db_session`` fixture，它跑在独立的内存 SQLite 上，
每个测试结束后整个库丢弃。这样pytest 可以反复跑、可以并发跑，
不会污染 argus.db，也不会因为 dev 库里的残留数据而随机失败。
"""

from collections.abc import AsyncGenerator, AsyncIterator, Iterator
from pathlib import Path
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
from app.db import _enable_sqlite_foreign_keys, get_session, get_sessionmaker
from app.gateway.auth import OAUTH_STATE_COOKIE
from app.main import app
from app.models import Base
from app.services.agent import TurnChunk, TurnResult
from app.services.credentials import ResolvedCredentials, resolve_env_credentials
from app.services.llm import LLMNotConfiguredError, clear_client_cache
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


async def collect_turn(
    client: Any,
    messages: Any,
    tools: Any,
    credentials: Any = None,
) -> TurnResult:
    """跑完 ``_run_turn`` 这个生成器，返回它的 ``TurnResult``。

    测试大多只关心整轮结果（usage / stop_reason / content），不关心
    中间发了哪些片段——这个辅助把生成器跑到底、取出收尾的那块。

    ``credentials`` 缺省时用 env 解析出的那一份——测试里通常不关心
    用户的凭据配置，只关心「这一轮能不能跑完」。
    """
    from app.services.agent import _run_turn

    if credentials is None:
        credentials = resolve_env_credentials()

    result: TurnResult | None = None
    async for chunk in _run_turn(client, messages, tools, credentials):
        if chunk.kind == "result":
            result = chunk.result
    assert result is not None, "_run_turn 没有产出 result 片段"
    return result


def _tavily_unavailable(_credentials: object = None) -> object:
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

    ``get_settings``（config.py）是 ``lru_cache(maxsize=1)`` 单例。
    第一次调用就把值缓存了，之后 ``monkeypatch.setenv`` 对它**完全无效**。

    只清 ``get_settings`` 不够——client 缓存（``llm._anthropic_client_cached``
    / ``llm._tavily_client_cached``）同样会缓存住带 key 的客户端，
    ``available_tools`` 拿到的仍是「已配置」。症状是
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
    # 两个都要清——只清 get_settings 的话 client 缓存仍握着带 key
    # 的客户端（症状：单跑通过、全量跑失败）。
    get_settings.cache_clear()
    clear_client_cache()
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


@pytest.fixture(autouse=True)
def _encryption_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """给测试环境一把**固定的**凭据加密主密钥，且**不碰真实的 key 文件**。

    生产的解析顺序是「环境变量 → key 文件 → 自动生成」（见
    ``app/services/secret_store.py``）。测试里要用第一档——固定值，
    每次跑都一样。

    ## 为什么不走「自动生成」那条路

    自动生成会往 ``apps/api/.credentials.key`` 写文件——那是**开发环境
    真实的主密钥**。测试跑一次就把开发环境的主密钥换掉了，开发库里
    已存的密文从此全部解不开。

    所以这里用环境变量把 key 固定住，**永远走不到生成那一档**。

    ## 为什么要固定值而不是每次随机

    有些用例要断言「解密后等于原文」，随机密钥也能过；但**跨用例复用
    同一把**才能让「这个库文件在另一个进程里也解得开」这条性质被
    验证到。

    ## 为什么用 setenv 而不是改 settings 对象

    ``_reset_env`` 会调 ``get_settings.cache_clear()``——下一次
    ``get_settings()`` 会**重建** Settings 对象，我改在旧对象上的属性
    就没了。所以这里必须在 ``_reset_env`` **之后**设环境变量并再清一次
    缓存，让新对象读到它。

    这与 conftest 顶部「pydantic-settings 的配置来自文件，环境变量对
    它无效」那条**不矛盾**：那条讲的是 `monkeypatch.delenv` 删不掉
    文件里已有的值；这里是**新增**一个文件里没有的值，环境变量照样
    生效（pydantic-settings 的优先级是环境变量 > .env 文件）。
    """
    # 这是一把**测试专用**的密钥，不是真密钥——不要拿去加密真凭据。
    monkeypatch.setenv(
        "CREDENTIALS_ENCRYPTION_KEY",
        "7zOcF7qhaYYcDAlSgZllSFihuhG2WTbbMv1eFbIvDZE=",
    )
    get_settings.cache_clear()

    # 兜底：万一哪条路径走到了「自动生成」，也不许写到开发目录——
    # 把 key 文件路径重定向到 tmp_path。
    monkeypatch.setattr(
        "app.services.secret_store._key_file_path",
        lambda: tmp_path / ".credentials.key",
    )
    yield


@pytest.fixture(autouse=True)
def _stub_stage_nodes(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    """把 Supervisor / Analyst 两个节点的模型调用桩掉。

    ## 为什么必须桩

    ``agent.run_agent`` 现在会调两次**主循环之外**的模型：Supervisor
    的拆解（``stages.plan_subtasks``）与 Analyst 的核对
    （``stages.analyze_evidence``）。这两个函数走
    ``client.messages.create``——**不经过** ``_run_turn``，所以
    ``test_agent_loop`` 里的 `_stub_turns` 拦不住它们。

    不桩的后果是测试真的联网：症状是 ``done.input_tokens`` 变成 337
    （100 + 真实调用烧的），而断言还写着 100。更糟的是它让整个测试套件
    依赖中转站的可用性与额度——上游一抖动就有一片用例红。

    ## 桩的行为

    返回**空的**结果（无子任务、无矛盾）。这样：

    - 账本不受影响（桩不烧 token）——已有断言（``input_tokens == 100``）
      继续成立
    - agent 主循环的路径与真实一致（拆解失败 → 降级 → 照常检索）

    ## 要测这两个节点自己的用例

    ``tests/test_stages.py`` 测的正是这两个函数的**真实行为**，所以那里
    必须跳过本桩——否则「桩返回空结果」会让那些用例测不到真东西。

    跳过的方式是看测试模块名：``request.node.module`` 是
    ``tests.test_stages``。用模块名而不是标记，是因为标记要在每个用例
    上写 ``@pytest.mark.real_stage_nodes``，漏一个就静悄悄测了桩。
    """
    from app.services import stages

    module = getattr(request.node.module, "__name__", "")
    # **精确相等**，不是后缀匹配。
    #
    # 后缀匹配（``endswith("test_stages")``）对未来新增的
    # ``test_web_stages.py`` / ``test_new_stages.py`` 也会命中——那里
    # 的 ``run_agent`` 集成测试会**真的联网调模型**
    # （``plan_subtasks`` / ``analyze_evidence`` 走
    # ``client.messages.create``，不走 ``_run_turn``，``_stub_turns``
    # 拦不住）。症状是测试依赖中转站的可用性与额度。
    #
    # 失效方向与「用标记」方案完全对称（标记漏写一个 → 静悄悄测了桩），
    # 但精确相等不会误伤新文件。
    if module == "tests.test_stages":
        return

    async def _no_plan(*args: Any, **kwargs: Any) -> stages.Plan:
        return stages.Plan()

    async def _no_analysis(*args: Any, **kwargs: Any) -> stages.Analysis:
        # **标 degraded**——桩本身没做核对，返回一个「成功且无矛盾」的
        # Analysis 会让 DAG 上的 note 说「核对 N 条证据，未发现矛盾」。
        #
        # 桩掉整个节点调用的场景（本文件要挡的就是「别真调模型」），
        # 没有任何核对发生——如实标降级。
        return stages.Analysis(degraded=True, skipped_reason="测试桩，未做核对")

    monkeypatch.setattr("app.services.agent.plan_subtasks", _no_plan)
    monkeypatch.setattr("app.services.stages.analyze_evidence", _no_analysis)


@pytest.fixture
def credentials() -> ResolvedCredentials:
    """一份按部署默认解析出来的凭据。

    测试大多不关心「这个用户配了什么 key」——它们关心的是流程能不能
    跑完。所以给一份 env 解析出来的凭据，省得每个用例自己去造。

    要测「用户自己配的 key 生效」时，用例自己调
    ``resolve_credentials(db, user_id)`` 造一份（见
    ``tests/test_credentials.py``）。
    """
    return resolve_env_credentials()


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
    # **后台任务的 session 工厂**也要换。
    #
    # ``app.db.get_sessionmaker`` 返回 ``SessionLocal``，它绑的是
    # ``app.db.engine``——**开发库的 engine**。后台任务直接调它就是普通
    # 函数调用，``dependency_overrides`` 对它无效，于是研究在测试里会
    # 静悄悄连上 ``argus.db``：往开发库写报告，测试却全绿。
    #
    # 用 ``db_session.bind`` 而不是新建 engine：内存 SQLite 的
    # ``:memory:`` 每个连接都是**独立的库**——新建 engine 会得到一个
    # 全新空库，表都没有。``db_session.bind`` 是它的 engine，同一个
    # 连接池，能看到同一份数据。
    #
    # （注意 ``AsyncSession.get_bind()`` 返回的是**同步** Engine，
    # SQLAlchemy 2.0 的行为；``.bind`` 才是 AsyncEngine。）
    app.dependency_overrides[get_sessionmaker] = lambda: async_sessionmaker(
        db_session.bind, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )
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


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """没有真实 API key 时跳过标了 ``live`` 的用例。

    标 ``live`` 的测试要**真的调模型**——CI 里只有占位 key，调用会得到
    一个难以理解的报错（而不是清晰的 skip）。这里在收集阶段统一跳过。

    判据用**配置层**而不是读 ``.env``：``.env`` 在本机是真 key，
    而 CI 只提供占位值，两者不能靠「文件存不存在」区分。
    """
    from app.config import get_settings

    if get_settings().anthropic_api_key:
        return

    skip_live = pytest.mark.skip(reason="需要真实模型调用（未配置 ANTHROPIC_API_KEY）")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)
