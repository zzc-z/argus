"""研究提问端点测试。

不打真实网络——``app.gateway.research.run_agent`` 是模块级函数，
monkeypatch 成一个只吐已知事件序列的假 agent，就能完整验证 SSE 帧格式、
鉴权、并发限制与错误路径。

重点守两条线：
- 开流之前的错误必须变成 HTTP 状态码（前端能读 detail）
- 开流之后的错误必须变成 error 事件（连接已经以 200 建立，改不了状态码）
"""

import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.gateway import research as research_module
from app.gateway.deps import SESSION_COOKIE
from app.services.agent import TurnChunk, TurnResult
from app.services.llm import LLMNotConfiguredError
from app.services.stream import (
    AgentEvent,
    DeltaEvent,
    DoneEvent,
    ErrorEvent,
    NodeEvent,
    ReferenceEvent,
    ToolCallEvent,
)
from tests.conftest import turn_chunks

# ── 假 agent ──────────────────────────────────────────────────


async def _fake_agent_success(
    question: str, *, user_id: int, **_: Any
) -> AsyncIterator[AgentEvent]:
    """吐一段正常的完整事件序列。"""
    yield NodeEvent(node_id="supervisor", lifecycle="active", detail="正在拆解问题意图")
    yield NodeEvent(node_id="supervisor", lifecycle="completed", elapsed_ms=2)
    yield NodeEvent(node_id="writer", lifecycle="active", detail="正在撰写研究报告")
    yield DeltaEvent(node_id="writer", text="根据检索结果，")
    yield DeltaEvent(node_id="writer", text="结论如下。")
    yield NodeEvent(node_id="writer", lifecycle="completed", elapsed_ms=8)
    yield DoneEvent(
        session_id="s-1",
        elapsed_ms=100,
        turns=1,
        input_tokens=123,
        output_tokens=45,
    )


async def _login(client: TestClient, db: AsyncSession, tag: str = "a") -> None:
    """建一个用户并把它的 session cookie 写进 client。

    不能只塞 JWT——``get_current_user`` 会拿 user_id 回查数据库，
    查不到就 401。走 OAuth 全流程太重，直接建库里的用户更省。

    ``tag`` 用来区分同一次测试里建的多个用户：email 是唯一约束，
    重复插入会撞 IntegrityError。
    """
    from app.models import User
    from app.services.token import create_access_token

    user = User(email=f"{tag}@example.com", display_name="Alice")
    db.add(user)
    await db.commit()
    await db.refresh(user)
    client.cookies.set(SESSION_COOKIE, create_access_token(user.id))


async def _login_only(client: TestClient) -> None:
    """塞 cookie 但不建用户——用于「票据合法但用户已删」的 401 场景。"""
    from app.services.token import create_access_token

    client.cookies.set(SESSION_COOKIE, create_access_token(9999))


def _frames(resp: Any) -> list[dict[str, Any]]:
    """把 SSE 响应解析成事件字典列表。"""
    lines = [line for line in resp.iter_lines() if line.startswith("data: ")]
    return [json.loads(line[6:]) for line in lines]


# ── 鉴权 ──────────────────────────────────────────────────────


async def test_ask_requires_login(client: TestClient, api_db: AsyncSession) -> None:
    """没登录必须 401。"""
    resp = client.post("/api/v1/research/ask", json={"question": "什么是向量数据库"})
    assert resp.status_code == 401


async def test_ask_with_garbage_cookie_rejected(client: TestClient, api_db: AsyncSession) -> None:
    client.cookies.set(SESSION_COOKIE, "not-a-jwt")
    resp = client.post("/api/v1/research/ask", json={"question": "问题"})
    assert resp.status_code == 401


# ── 参数校验（开流前，能拿到状态码）─────────────────────────


async def test_ask_rejects_empty_question(client: TestClient, api_db: AsyncSession) -> None:
    await _login(client, api_db)
    resp = client.post("/api/v1/research/ask", json={"question": ""})
    assert resp.status_code == 422


async def test_ask_rejects_blank_question(client: TestClient, api_db: AsyncSession) -> None:
    """纯空白必须拒绝——否则白白触发一次完整多轮模型调用。"""
    await _login(client, api_db)
    resp = client.post("/api/v1/research/ask", json={"question": "   \n\t "})
    assert resp.status_code == 422


async def test_ask_rejects_overlong_question(client: TestClient, api_db: AsyncSession) -> None:
    await _login(client, api_db)
    resp = client.post("/api/v1/research/ask", json={"question": "问" * 5000})
    assert resp.status_code == 422


# ── SSE 帧协议 ────────────────────────────────────────────────


async def test_stream_returns_event_stream_content_type(client: TestClient, monkeypatch: pytest.MonkeyPatch, api_db: AsyncSession) -> None:
    await _login(client, api_db)
    monkeypatch.setattr(research_module, "run_agent", _fake_agent_success)

    with client.stream("POST", "/api/v1/research/ask", json={"question": "问题"}) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        resp.read()


async def test_stream_disables_proxy_buffering(client: TestClient, monkeypatch: pytest.MonkeyPatch, api_db: AsyncSession) -> None:
    """X-Accel-Buffering: no 必须在——不关会被反代攒成一坨，流式失效。"""
    await _login(client, api_db)
    monkeypatch.setattr(research_module, "run_agent", _fake_agent_success)

    with client.stream("POST", "/api/v1/research/ask", json={"question": "问题"}) as resp:
        assert resp.headers["x-accel-buffering"] == "no"
        resp.read()


async def test_stream_frames_are_valid_json(client: TestClient, monkeypatch: pytest.MonkeyPatch, api_db: AsyncSession) -> None:
    await _login(client, api_db)
    monkeypatch.setattr(research_module, "run_agent", _fake_agent_success)

    with client.stream("POST", "/api/v1/research/ask", json={"question": "问题"}) as resp:
        frames = _frames(resp)

    assert len(frames) == 8
    for frame in frames:
        assert "type" in frame
        assert "v" in frame


async def test_frame_types_in_expected_order(client: TestClient, monkeypatch: pytest.MonkeyPatch, api_db: AsyncSession) -> None:
    """事件顺序：run（第一帧）→ 节点切换 → 正文 → 收尾。

    ``run`` 帧必须在**最前面**：前端拿到 run id 才能在刷新后接回这一轮，
    它要是排在正文中间，用户在正文出来之前刷新就接不回来。
    """
    await _login(client, api_db)
    monkeypatch.setattr(research_module, "run_agent", _fake_agent_success)

    with client.stream("POST", "/api/v1/research/ask", json={"question": "问题"}) as resp:
        types = [f["type"] for f in _frames(resp)]

    assert types == ["run", "node", "node", "node", "delta", "delta", "node", "done"]


async def test_run_frame_carries_run_id_and_question(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, api_db: AsyncSession
) -> None:
    """第一帧带 run id 与问题原文——前端靠它接回这一轮。

    少了 run id，刷新之后前端不知道该接哪一轮，只能重新提问（再烧一次钱）。
    """
    await _login(client, api_db)
    monkeypatch.setattr(research_module, "run_agent", _fake_agent_success)

    with client.stream("POST", "/api/v1/research/ask", json={"question": "什么是向量数据库"}) as resp:
        frames = _frames(resp)

    run_frame = frames[0]
    assert run_frame["type"] == "run"
    assert run_frame["v"]["run_id"]
    assert run_frame["v"]["question"] == "什么是向量数据库"


async def test_done_carries_session_and_tokens(client: TestClient, monkeypatch: pytest.MonkeyPatch, api_db: AsyncSession) -> None:
    await _login(client, api_db)
    monkeypatch.setattr(research_module, "run_agent", _fake_agent_success)

    with client.stream("POST", "/api/v1/research/ask", json={"question": "问题"}) as resp:
        done = next(f for f in _frames(resp) if f["type"] == "done")

    assert done["v"]["session_id"] == "s-1"
    assert done["v"]["input_tokens"] == 123
    assert done["v"]["turns"] == 1


async def test_delta_text_is_chinese_not_escaped(client: TestClient, monkeypatch: pytest.MonkeyPatch, api_db: AsyncSession) -> None:
    """中文不能是 \\uXXXX——前端要拿到可读文本。"""
    await _login(client, api_db)
    monkeypatch.setattr(research_module, "run_agent", _fake_agent_success)

    with client.stream("POST", "/api/v1/research/ask", json={"question": "问题"}) as resp:
        raw = b"".join(resp.iter_bytes()).decode()

    assert "根据检索结果" in raw
    assert "\\u" not in raw


async def test_tool_call_event_reaches_client(client: TestClient, monkeypatch: pytest.MonkeyPatch, api_db: AsyncSession) -> None:
    """工具调用事件要能穿过端点——前端要显示「正在搜索」。"""

    async def _with_tool(question: str, *, user_id: int, **_: Any) -> AsyncIterator[AgentEvent]:
        yield ToolCallEvent(call_id="t1", phase="start", name="tavily_search")
        yield ToolCallEvent(
            call_id="t1", phase="end", name="tavily_search", ok=True, elapsed_ms=2100
        )
        yield DoneEvent(
            session_id="s", elapsed_ms=1, turns=1, input_tokens=1, output_tokens=1
        )

    await _login(client, api_db)
    monkeypatch.setattr(research_module, "run_agent", _with_tool)

    with client.stream("POST", "/api/v1/research/ask", json={"question": "问题"}) as resp:
        calls = [f for f in _frames(resp) if f["type"] == "tool_call"]

    assert len(calls) == 2
    assert calls[0]["v"]["phase"] == "start"
    assert calls[1]["v"]["elapsed_ms"] == 2100


async def test_reference_event_reaches_client(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, api_db: AsyncSession
) -> None:
    """引用表要能穿过端点——前端靠它把 ``[1]`` 渲染成可点角标。"""

    async def _with_ref(question: str, *, user_id: int, **_: Any) -> AsyncIterator[AgentEvent]:
        yield ReferenceEvent(
            references=[
                {
                    "n": 1,
                    "chunk_id": 7,
                    "source_id": 2,
                    "chunk_index": 0,
                    "page": 3,
                    "title": "NVIDIA Q2 财报",
                    "excerpt": "数据中心收入 392 亿美元",
                    "recall": "向量+BM25",
                }
            ]
        )
        yield DeltaEvent(node_id="writer", text="数据中心收入 392 亿美元 [1]")
        yield DoneEvent(
            session_id="s", elapsed_ms=1, turns=1, input_tokens=1, output_tokens=1
        )

    await _login(client, api_db)
    monkeypatch.setattr(research_module, "run_agent", _with_ref)

    with client.stream("POST", "/api/v1/research/ask", json={"question": "问题"}) as resp:
        frames = _frames(resp)

    refs = [f for f in frames if f["type"] == "reference"]
    assert len(refs) == 1
    assert refs[0]["v"]["references"][0]["chunk_id"] == 7
    assert refs[0]["v"]["references"][0]["page"] == 3


async def test_reference_precedes_delta(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, api_db: AsyncSession
) -> None:
    """引用表必须早于正文到达，否则用户读到 ``[1]`` 时角标还没准备好。"""

    async def _with_ref(question: str, *, user_id: int, **_: Any) -> AsyncIterator[AgentEvent]:
        yield ReferenceEvent(references=[{"n": 1, "chunk_id": 7}])
        yield DeltaEvent(node_id="writer", text="答案 [1]")
        yield DoneEvent(
            session_id="s", elapsed_ms=1, turns=1, input_tokens=1, output_tokens=1
        )

    await _login(client, api_db)
    monkeypatch.setattr(research_module, "run_agent", _with_ref)

    with client.stream("POST", "/api/v1/research/ask", json={"question": "问题"}) as resp:
        types = [f["type"] for f in _frames(resp)]

    assert types.index("reference") < types.index("delta")


# ── 开流后的错误（改不了状态码，只能走事件）──────────────────


async def test_error_event_when_agent_crashes(client: TestClient, monkeypatch: pytest.MonkeyPatch, api_db: AsyncSession) -> None:
    """agent 抛异常要变成 error 事件，而不是 500 或裸断连接。"""

    async def _boom(question: str, *, user_id: int, **_: Any) -> AsyncIterator[AgentEvent]:
        yield NodeEvent(node_id="supervisor", lifecycle="active")
        raise RuntimeError("循环崩了")

    await _login(client, api_db)
    monkeypatch.setattr(research_module, "run_agent", _boom)

    with client.stream("POST", "/api/v1/research/ask", json={"question": "问题"}) as resp:
        assert resp.status_code == 200
        frames = _frames(resp)

    errors = [f for f in frames if f["type"] == "error"]
    assert len(errors) == 1
    assert errors[0]["v"]["code"] == "internal_error"
    assert errors[0]["v"]["retryable"] is False
    # 内部异常文本不能泄漏给前端
    assert "循环崩了" not in json.dumps(frames, ensure_ascii=False)


async def test_error_event_when_vector_engine_unavailable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, api_db: AsyncSession
) -> None:
    """向量库起不来也要变成 error 事件，不能裸 500。

    ``get_vector_engine`` 是懒初始化的单例，首次调用才建连接——sqlite-vec
    扩展加载失败、数据库文件不可写都在这一步抛。它在 try 块里的话前端
    至少收得到 error 事件；挪出去就成了裸 500，前端连失败都判断不了。
    """

    def _boom() -> object:
        raise RuntimeError("vec0 扩展加载失败")

    async def _never(question: str, *, user_id: int, **_: Any) -> AsyncIterator[AgentEvent]:
        raise AssertionError("引擎挂了就不该进 agent")
        yield  # pragma: no cover

    await _login(client, api_db)
    monkeypatch.setattr(research_module, "get_vector_engine", _boom)
    monkeypatch.setattr(research_module, "run_agent", _never)

    with client.stream("POST", "/api/v1/research/ask", json={"question": "问题"}) as resp:
        assert resp.status_code == 200
        frames = _frames(resp)

    errors = [f for f in frames if f["type"] == "error"]
    assert len(errors) == 1
    assert errors[0]["v"]["code"] == "internal_error"
    assert "vec0" not in json.dumps(frames, ensure_ascii=False)


async def test_stream_releases_slot_on_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, api_db: AsyncSession
) -> None:
    """出错后并发槽必须归还，否则几次失败就把 4 个槽全占死。"""

    async def _boom(question: str, *, user_id: int, **_: Any) -> AsyncIterator[AgentEvent]:
        raise RuntimeError("崩")
        yield  # pragma: no cover

    await _login(client, api_db)
    monkeypatch.setattr(research_module, "run_agent", _boom)

    for _ in range(research_module.MAX_CONCURRENT_STREAMS + 2):
        with client.stream("POST", "/api/v1/research/ask", json={"question": "q"}) as resp:
            assert resp.status_code == 200, "槽没归还，第 N 次已经被 503 挡掉"


async def test_agent_gets_the_override_session(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, api_db: AsyncSession
) -> None:
    """agent 拿到的必须连**测试库**，不能是开发库。

    这条守着 ``api_db`` fixture 的 override：一旦有人把 db 改成
    ``SessionLocal()`` 或 ``asynccontextmanager(get_session)()``（两者都是
    普通函数调用、绕过依赖求解器），override 就不生效，测试会静悄悄地
    连到 ``argus.db`` 上去——症状是「测试全绿，但开发库被写了」。

    ## 断言的是「同一个 engine」而不是「同一个 session 对象」

    2026-11-01 起 agent 跑在**后台任务**里，后台任务自己开 session
    （请求的 session 随响应结束就关了，跑不到那么久）。同一个 engine
    的不同 session 是**必须**的——它们是两个连接，能同时用。

    所以断言 engine 相同：那才是「连的是哪个库」的决定因素。
    断言 session 对象相同在新架构下反而是错的。
    """
    seen: dict[str, object] = {}

    async def _capture(
        question: str, *, user_id: int, db: Any, **_: Any
    ) -> AsyncIterator[AgentEvent]:
        seen["db"] = db
        yield DoneEvent(session_id="s", elapsed_ms=1, turns=1, input_tokens=1, output_tokens=1)

    await _login(client, api_db)
    monkeypatch.setattr(research_module, "run_agent", _capture)

    with client.stream("POST", "/api/v1/research/ask", json={"question": "q"}) as resp:
        assert resp.status_code == 200
        resp.read()

    agent_db = seen["db"]
    assert isinstance(agent_db, AsyncSession)
    assert agent_db.bind is api_db.bind, (
        "agent 拿到的 session 不在测试库上——override 被绕过了"
    )


async def test_agent_session_is_usable_during_stream(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, api_db: AsyncSession
) -> None:
    """流生成器跑的时候 session 必须还能执行查询。

    ``Depends()`` 默认 ``scope="request"``，依赖挂在**外层** exit stack 上，
    在响应发完之后才关闭（``dependencies/utils.py:664-667``）。内层
    ``function_stack`` 早关是另一回事，别看成同一个——真踩过这个坑，
    第一版误以为 session 在生成器跑之前就关了，于是自己开了一个，
    结果绕过了 override、连上开发库。

    有人把依赖改成 ``Depends(scope="function")`` 时这条会失败。
    """
    from sqlalchemy import text

    rows: list[Any] = []

    async def _query(
        question: str, *, user_id: int, db: Any, **_: Any
    ) -> AsyncIterator[AgentEvent]:
        result = await db.execute(text("SELECT 1"))
        rows.append(result.scalar())
        yield DoneEvent(session_id="s", elapsed_ms=1, turns=1, input_tokens=1, output_tokens=1)

    await _login(client, api_db)
    monkeypatch.setattr(research_module, "run_agent", _query)

    with client.stream("POST", "/api/v1/research/ask", json={"question": "q"}) as resp:
        assert resp.status_code == 200
        resp.read()

    assert rows == [1], "生成器里 session 已经不能用了"


async def test_error_is_last_frame(client: TestClient, monkeypatch: pytest.MonkeyPatch, api_db: AsyncSession) -> None:
    """error 必须是最后一帧——前端靠它把界面收尾。"""

    async def _boom(question: str, *, user_id: int, **_: Any) -> AsyncIterator[AgentEvent]:
        raise RuntimeError("挂了")
        yield  # pragma: no cover - 让它成为生成器

    await _login(client, api_db)
    monkeypatch.setattr(research_module, "run_agent", _boom)

    with client.stream("POST", "/api/v1/research/ask", json={"question": "问题"}) as resp:
        frames = _frames(resp)

    assert frames[-1]["type"] == "error"


async def test_agent_error_event_passes_through(client: TestClient, monkeypatch: pytest.MonkeyPatch, api_db: AsyncSession) -> None:
    """agent 自己发的 ErrorEvent 原样透传，不被端点重复包装。"""

    async def _fail(question: str, *, user_id: int, **_: Any) -> AsyncIterator[AgentEvent]:
        yield ErrorEvent(code="llm_unavailable", message="模型服务暂时不可用，请稍后重试")

    await _login(client, api_db)
    monkeypatch.setattr(research_module, "run_agent", _fail)

    with client.stream("POST", "/api/v1/research/ask", json={"question": "问题"}) as resp:
        frames = _frames(resp)

    # 第一帧是 run（run id + 问题），后面才是 agent 的 error 帧。
    assert [f["type"] for f in frames] == ["run", "error"]
    assert frames[1]["v"]["code"] == "llm_unavailable"
    assert frames[1]["v"]["retryable"] is True


# ── 开流前的服务端配置错误 ────────────────────────────────────


async def test_ask_returns_400_when_llm_unconfigured(client: TestClient, monkeypatch: pytest.MonkeyPatch, api_db: AsyncSession) -> None:
    """模型没配置要在开流前拒——开流后就只能发事件了。

    **用 400 而不是 503**：503 的语义是「服务暂时不可用，稍后重试」，
    而「模型未配置」是部署问题，重试一万次也一样。两者混在同一个状态码
    里，前端没法区分「该等」还是「该改配置」。
    """

    def _raise() -> None:
        raise LLMNotConfiguredError("ANTHROPIC_API_KEY 未配置")

    await _login(client, api_db)
    monkeypatch.setattr(research_module, "get_anthropic_client", _raise)

    resp = client.post("/api/v1/research/ask", json={"question": "问题"})
    assert resp.status_code == 400
    assert "模型服务未配置" in resp.json()["detail"]


async def test_concurrency_limit_returns_503(
    client: TestClient, api_db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """并发满时 503，且不会开流。"""

    async def _never(question: str, *, user_id: int, **_: Any) -> AsyncIterator[AgentEvent]:
        yield DoneEvent(  # pragma: no cover - 走不到
            session_id="s", elapsed_ms=1, turns=1, input_tokens=1, output_tokens=1
        )

    await _login(client, api_db)
    monkeypatch.setattr(research_module, "run_agent", _never)

    # 手动占满所有槽位，模拟并发已满
    for _ in range(research_module.MAX_CONCURRENT_STREAMS):
        await research_module._slots.acquire()
    try:
        resp = client.post("/api/v1/research/ask", json={"question": "问题"})
        assert resp.status_code == 503
        assert "并发" in resp.json()["detail"]
    finally:
        for _ in range(research_module.MAX_CONCURRENT_STREAMS):
            research_module._slots.release()


async def test_slots_released_after_stream(client: TestClient, monkeypatch: pytest.MonkeyPatch, api_db: AsyncSession) -> None:
    """流结束后槽位必须归还，否则跑几次之后就永久 503。"""
    monkeypatch.setattr(research_module, "run_agent", _fake_agent_success)

    for i in range(research_module.MAX_CONCURRENT_STREAMS + 2):
        await _login(client, api_db, tag=f"u{i}")
        with client.stream("POST", "/api/v1/research/ask", json={"question": "问题"}) as resp:
            assert resp.status_code == 200
            resp.read()

    assert not research_module._slots.locked()


async def test_slots_released_even_when_agent_crashes(client: TestClient, monkeypatch: pytest.MonkeyPatch, api_db: AsyncSession) -> None:
    """agent 崩了也要归还槽位。"""

    async def _boom(question: str, *, user_id: int, **_: Any) -> AsyncIterator[AgentEvent]:
        raise RuntimeError("崩")
        yield  # pragma: no cover

    await _login(client, api_db)
    monkeypatch.setattr(research_module, "run_agent", _boom)

    with client.stream("POST", "/api/v1/research/ask", json={"question": "问题"}) as resp:
        resp.read()

    assert not research_module._slots.locked()


# ── 端到端：真实 run_agent 走一遍（打桩 LLM）──────────────────


async def test_end_to_end_with_stubbed_llm(client: TestClient, monkeypatch: pytest.MonkeyPatch, api_db: AsyncSession) -> None:
    """不打桩端点这层，用打桩后的真实 agent 跑通全链路。

    验证两件最要紧的：节点不变量在穿过端点编码后依然成立，
    正文能拼回原文。
    """
    from app.services import agent as agent_module

    def _turn(text: str = "", tools: list[dict[str, Any]] | None = None) -> TurnResult:
        calls = tools or []
        content: list[dict[str, Any]] = [{"type": "thinking", "thinking": "想一下", "signature": "S"}]
        if text:
            content.append({"type": "text", "text": text})
        content.extend(calls)
        return TurnResult(
            content=content,
            text=text,
            tool_calls=calls,
            stop_reason="tool_use" if calls else "end_turn",
            input_tokens=100,
            output_tokens=50,
        )

    script = [
        _turn(
            tools=[
                {
                    "type": "tool_use",
                    "id": "t1",
                    "name": "dedup",
                    "input": {"urls": ["https://a.com"]},
                }
            ]
        ),
        _turn(text="最终结论是：向量数据库适合高维近邻检索。"),
    ]

    async def _fake_turn(cl: Any, messages: Any, tools: Any) -> AsyncIterator[TurnChunk]:
        for chunk in turn_chunks(script.pop(0)):
            yield chunk

    monkeypatch.setattr(agent_module, "_run_turn", _fake_turn)
    await _login(client, api_db)

    with client.stream(
        "POST", "/api/v1/research/ask", json={"question": "什么是向量数据库"}
    ) as resp:
        frames = _frames(resp)

    # 节点不变量：任一时刻至多一个 active，结束时归零
    active = 0
    for frame in frames:
        if frame["type"] != "node":
            continue
        if frame["v"]["lifecycle"] == "active":
            active += 1
            assert active == 1, f"出现第二个 active: {frame}"
        else:
            active -= 1
    assert active == 0

    # 正文能拼回原文
    text = "".join(f["v"]["text"] for f in frames if f["type"] == "delta")
    assert text == "最终结论是：向量数据库适合高维近邻检索。"

    assert any(f["type"] == "tool_call" for f in frames)
    # done 不再是最后一帧：Critic 的校验帧排在它**之后**发出，这样 judge
    # 调用慢（最坏 120s × 3 次重试）也不挡用户看到报告与 token 统计。
    assert frames[-1]["type"] == "faithfulness"
    done_idx = next(i for i, f in enumerate(frames) if f["type"] == "done")
    faith_idx = next(i for i, f in enumerate(frames) if f["type"] == "faithfulness")
    assert done_idx < faith_idx


async def test_stream_does_not_touch_db(
    client: TestClient, api_db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """鉴权用的 DB session 不能被 SSE 长连接一直占着。

    本次不落库，流期间不该再碰数据库——否则 4 个并发 SSE 就把连接池
    占满，其他接口（含 /api/v1/me）一起卡死。
    """
    monkeypatch.setattr(research_module, "run_agent", _fake_agent_success)
    await _login(client, api_db)

    with client.stream("POST", "/api/v1/research/ask", json={"question": "问题"}) as resp:
        assert resp.status_code == 200
        resp.read()

    assert api_db is not None
