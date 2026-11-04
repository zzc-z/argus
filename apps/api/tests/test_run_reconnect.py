"""重连：刷新 / 切页后接回那一轮。

## 要守住什么

2026-11-01 之前，agent 直接跑在 ``StreamingResponse`` 的生成器里——
客户端一断开（刷新、切页、关标签）**生成就停**，用户回来只看到一片
空白，已经烧掉的 token 白烧。

改成「服务端持有 run、客户端只是订阅者」之后，要守住两件事：

1. **断开不影响生成**：run 继续跑，事件继续进缓冲。
2. **重连能补齐**：新订阅者拿到「订阅之前发生过的全部事件」+「之后的
   增量」，合起来是完整序列，不重不漏。

## 为什么同步用 ``threading.Event`` 而不是 ``asyncio.Event``

``TestClient`` 把 app 跑在**另一个线程**的另一个事件循环里（portal）。
测试代码跑在 pytest-asyncio 的循环里。``asyncio.Event`` 绑定创建它
的那个循环——跨循环 ``set()`` 不会唤醒等待者，测试会**永久挂住**
（第一版就是这么挂的，120 秒超时）。

``threading.Event`` 不绑定循环，跨线程安全。agent 侧用
``await asyncio.to_thread(release.wait)`` 等它——不阻塞那个 portal
循环。

## 每条测试的「错误实现也会通过吗」对照

- ``test_generation_continues_after_client_disconnects`` —— 断开后 run
  仍然收到后续事件。旧实现（生成绑在连接上）会失败 ✓
- ``test_reconnect_replays_the_whole_run`` —— 重连拿到全部事件。
  只会「接上未来」的实现在这里失败 ✓
- ``test_reconnect_rejects_unknown_run`` —— 404。
- ``test_reconnect_requires_login`` —— 401。
- ``test_reconnect_rejects_other_users_run`` —— 别人的 run 拿不到。
  少了鉴权这条会挂 ✓
"""

import asyncio
import json
import threading
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.gateway import research as research_module
from app.gateway.deps import SESSION_COOKIE
from app.services.runs import get_run_registry
from app.services.stream import AgentEvent, DeltaEvent, DoneEvent, NodeEvent


async def _login(client: TestClient, db: AsyncSession, tag: str = "a") -> None:
    """建用户并把 session cookie 写进 client。见 test_research_router。"""
    from app.models import User
    from app.services.token import create_access_token

    user = User(email=f"{tag}@example.com", display_name="Alice")
    db.add(user)
    await db.commit()
    await db.refresh(user)
    client.cookies.set(SESSION_COOKIE, create_access_token(user.id))


def _frames(resp: Any) -> list[dict[str, Any]]:
    lines = [line for line in resp.iter_lines() if line.startswith("data: ")]
    return [json.loads(line[6:]) for line in lines]


def _deltas(frames: list[dict[str, Any]]) -> list[str]:
    return [f["v"]["text"] for f in frames if f["type"] == "delta"]


@pytest.fixture(autouse=True)
def _clean_registry() -> None:
    """每个用例前清空 run 注册表——它是进程级单例，跨用例残留会互相干扰。"""
    get_run_registry().clear()


def _only_run_id() -> str:
    """取注册表里唯一的 run id。"""
    runs = get_run_registry()._runs
    assert len(runs) == 1, f"注册表里应该只有一个 run，实际 {len(runs)} 个"
    return next(iter(runs))


# ── 断开不影响生成 ────────────────────────────────────────────


async def test_generation_continues_after_client_disconnects(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, api_db: AsyncSession
) -> None:
    """客户端断开后，run **继续**收到事件。

    这条守的就是本次改动的核心。旧实现里生成器挂在 HTTP 连接上，
    客户端一断，agent 就被取消——用户回来看到空白，已烧的 token 白烧。
    """
    release = threading.Event()
    finished = threading.Event()

    async def _slow_agent(question: str, *, user_id: int, **_: Any) -> AsyncIterator[AgentEvent]:
        yield NodeEvent(node_id="supervisor", lifecycle="active")
        yield DeltaEvent(node_id="writer", text="第一片")
        # 等测试放行才发第二片——模拟「客户端断开之后模型还在生成」。
        await asyncio.to_thread(release.wait, 5.0)
        yield DeltaEvent(node_id="writer", text="第二片")
        yield DoneEvent(session_id="s", elapsed_ms=1, turns=1, input_tokens=1, output_tokens=1)
        finished.set()

    await _login(client, api_db)
    monkeypatch.setattr(research_module, "run_agent", _slow_agent)

    # 连上就断开——不等流结束。
    with client.stream("POST", "/api/v1/research/ask", json={"question": "q"}) as resp:
        assert resp.status_code == 200

    # 客户端已经走了。现在让 agent 继续跑完。
    release.set()
    assert finished.wait(5.0), "agent 没跑完——断开把生成带走了"

    # 断开之后产生的事件仍在 run 的缓冲里。
    run = get_run_registry().get(_only_run_id())
    assert run is not None
    _queue, replay = await run.subscribe()
    deltas = [e.text for e in replay if isinstance(e, DeltaEvent)]
    assert deltas == ["第一片", "第二片"], f"断开后的事件没进缓冲：{deltas}"


# ── 重连 ──────────────────────────────────────────────────────


async def test_reconnect_replays_the_whole_run(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, api_db: AsyncSession
) -> None:
    """重连要把整轮事件补上——用户刷新回来看到的是**完整**的报告。

    只接「未来」的话，用户刷新回来会看到半截报告——正文从中间开始。
    """

    async def _agent(question: str, *, user_id: int, **_: Any) -> AsyncIterator[AgentEvent]:
        yield DeltaEvent(node_id="writer", text="第一片")
        yield DeltaEvent(node_id="writer", text="第二片")
        yield DoneEvent(session_id="s", elapsed_ms=1, turns=1, input_tokens=1, output_tokens=1)

    await _login(client, api_db)
    monkeypatch.setattr(research_module, "run_agent", _agent)

    with client.stream("POST", "/api/v1/research/ask", json={"question": "q"}) as resp:
        resp.read()

    run_id = _only_run_id()
    with client.stream("GET", f"/api/v1/research/runs/{run_id}/stream") as resp:
        assert resp.status_code == 200
        frames = _frames(resp)

    texts = _deltas(frames)
    assert texts == ["第一片", "第二片"], f"重连没有补齐整轮：{texts}"
    assert any(f["type"] == "done" for f in frames), "重连没拿到收尾帧"


async def test_run_event_is_first_frame_on_reconnect(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, api_db: AsyncSession
) -> None:
    """重连时第一帧仍是 run 帧——前端靠它确认「接对的那一轮」。"""

    async def _agent(question: str, *, user_id: int, **_: Any) -> AsyncIterator[AgentEvent]:
        yield DeltaEvent(node_id="writer", text="正文")
        yield DoneEvent(session_id="s", elapsed_ms=1, turns=1, input_tokens=1, output_tokens=1)

    await _login(client, api_db)
    monkeypatch.setattr(research_module, "run_agent", _agent)

    with client.stream("POST", "/api/v1/research/ask", json={"question": "q"}) as resp:
        resp.read()

    run_id = _only_run_id()
    with client.stream("GET", f"/api/v1/research/runs/{run_id}/stream") as resp:
        frames = _frames(resp)

    assert frames[0]["type"] == "run"
    assert frames[0]["v"]["run_id"] == run_id


async def test_reconnect_does_not_duplicate_text(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, api_db: AsyncSession
) -> None:
    """重连**不能**把正文发两遍。

    回放与实时增量重叠的话，用户会看到同一段正文出现两次——那比重连
    失败还糟。
    """

    async def _agent(question: str, *, user_id: int, **_: Any) -> AsyncIterator[AgentEvent]:
        yield DeltaEvent(node_id="writer", text="唯一的一段")
        yield DoneEvent(session_id="s", elapsed_ms=1, turns=1, input_tokens=1, output_tokens=1)

    await _login(client, api_db)
    monkeypatch.setattr(research_module, "run_agent", _agent)

    with client.stream("POST", "/api/v1/research/ask", json={"question": "q"}) as resp:
        resp.read()

    run_id = _only_run_id()
    with client.stream("GET", f"/api/v1/research/runs/{run_id}/stream") as resp:
        frames = _frames(resp)

    texts = _deltas(frames)
    assert texts.count("唯一的一段") == 1, f"正文重复了：{texts}"


# ── 鉴权 ──────────────────────────────────────────────────────


async def test_reconnect_rejects_unknown_run(client: TestClient, api_db: AsyncSession) -> None:
    """不存在的 run id → 404。"""
    await _login(client, api_db)
    resp = client.get("/api/v1/research/runs/根本不存在的-id/stream")
    assert resp.status_code == 404


async def test_reconnect_requires_login(client: TestClient, api_db: AsyncSession) -> None:
    """没登录 → 401。"""
    resp = client.get("/api/v1/research/runs/某个-id/stream")
    assert resp.status_code == 401


async def test_reconnect_rejects_other_users_run(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, api_db: AsyncSession
) -> None:
    """别人的 run 拿不到——404（不是 403）。

    用 404 而不是 403：403 会泄露「这个 run id 存在」，那是别人的会话。
    """

    async def _agent(question: str, *, user_id: int, **_: Any) -> AsyncIterator[AgentEvent]:
        yield DoneEvent(session_id="s", elapsed_ms=1, turns=1, input_tokens=1, output_tokens=1)

    await _login(client, api_db, tag="owner")
    monkeypatch.setattr(research_module, "run_agent", _agent)

    with client.stream("POST", "/api/v1/research/ask", json={"question": "q"}) as resp:
        resp.read()
    run_id = _only_run_id()

    # 换成另一个用户
    client.cookies.set(SESSION_COOKIE, "")
    await _login(client, api_db, tag="other")

    resp = client.get(f"/api/v1/research/runs/{run_id}/stream")
    assert resp.status_code == 404


# ── 并发槽位 ──────────────────────────────────────────────────


async def test_slot_is_released_after_the_run_finishes(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, api_db: AsyncSession
) -> None:
    """研究跑完后槽位必须归还。

    槽位跟着**研究**走，不跟着 HTTP 连接走——研究是后台任务，HTTP 响应
    早就发完了。漏还的话跑几次之后全部请求 503。

    槽位用 ``task.add_done_callback`` 还，不是任务体里的 finally——
    任务在开始执行前就被取消时 finally 根本不执行，槽位会永久泄漏。
    """
    finished = threading.Event()

    async def _agent(question: str, *, user_id: int, **_: Any) -> AsyncIterator[AgentEvent]:
        yield DoneEvent(session_id="s", elapsed_ms=1, turns=1, input_tokens=1, output_tokens=1)
        finished.set()

    await _login(client, api_db)
    monkeypatch.setattr(research_module, "run_agent", _agent)

    with client.stream("POST", "/api/v1/research/ask", json={"question": "q"}) as resp:
        resp.read()

    assert finished.wait(5.0), "agent 没跑完"
    # done_callback 是异步的，等它跑完。
    for _ in range(200):
        if not research_module._slots.locked():
            break
        await asyncio.sleep(0.01)

    assert not research_module._slots.locked(), "研究结束后槽位没归还"


# ── URL 方案：按 id 精确取消 + 最近一轮查询 ──────────────────


async def test_asking_again_cancels_only_the_named_run(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, api_db: AsyncSession
) -> None:
    """重问时取消的是**指定的那一轮**，不是「用户最近一轮」。

    ## 要防的回归

    用户可能开着两个标签页各跑一个研究。按「用户最近一轮」取消的话，
    第二个标签页一提问就把第一个标签页的生成掐掉——那一个标签页的人
    正盯着正文往上长，突然停了。

    前端知道**自己**这个标签页正在跑哪一轮（URL 里的 run id），所以
    精确传上来。

    ## 为什么用 spy 而不是真的取消

    真的取消需要让 run 一直「在跑」，而 agent 卡住会让每个请求等它结束
    ——实测三个请求就跑了 95 秒。而且真跑起来时「那一轮是否已收尾」
    成了时序问题，测的是时序不是行为。

    spy 直接断言「端点把哪个 id 传给了 cancel_by_id」——那才是这条要守
    的契约（**按 id 精确**，不是按「用户最近一轮」）。取消本身由
    ``test_cancel_by_id_cancels_the_named_run``（注册表层）守住。
    """
    seen: list[tuple[str, int]] = []
    real_cancel = get_run_registry().cancel_by_id

    async def _spy(run_id: str, user_id: int) -> bool:
        seen.append((run_id, user_id))
        return await real_cancel(run_id, user_id)

    async def _agent(question: str, *, user_id: int, **_: Any) -> AsyncIterator[AgentEvent]:
        yield DoneEvent(session_id="s", elapsed_ms=1, turns=1, input_tokens=1, output_tokens=1)

    await _login(client, api_db)
    monkeypatch.setattr(research_module, "run_agent", _agent)
    monkeypatch.setattr(get_run_registry(), "cancel_by_id", _spy)

    target = "some-run-id"
    with client.stream(
        "POST",
        "/api/v1/research/ask",
        json={"question": "q", "replace_run_id": target},
    ) as resp:
        resp.read()

    assert seen, "端点没有调用 cancel_by_id——replace_run_id 没被处理"
    assert seen[0][0] == target, f"取消的是 {seen[0][0]}，不是前端指定的 {target}"


async def test_replace_run_id_ignores_other_users_run(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, api_db: AsyncSession
) -> None:
    """别人的 run 不能被取消。

    ``replace_run_id`` 是客户端传来的 id——不校验归属的话，任何人都能
    掐掉别人的研究。
    """

    async def _agent(question: str, *, user_id: int, **_: Any) -> AsyncIterator[AgentEvent]:
        yield DoneEvent(session_id="s", elapsed_ms=1, turns=1, input_tokens=1, output_tokens=1)

    await _login(client, api_db, tag="owner")
    monkeypatch.setattr(research_module, "run_agent", _agent)

    with client.stream("POST", "/api/v1/research/ask", json={"question": "q"}) as resp:
        resp.read()
    owner_run_id = _only_run_id()

    # 换成另一个用户，试着取消 owner 的 run
    client.cookies.set(SESSION_COOKIE, "")
    await _login(client, api_db, tag="intruder")

    with client.stream(
        "POST",
        "/api/v1/research/ask",
        json={"question": "q2", "replace_run_id": owner_run_id},
    ) as resp:
        resp.read()

    owner_run = get_run_registry().get(owner_run_id)
    assert owner_run is not None
    assert not owner_run.cancelled, "别人的 run 被取消了——鉴权漏了"


async def test_latest_run_returns_the_most_recent_one(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, api_db: AsyncSession
) -> None:
    """``GET /runs/latest`` 返回最近一轮的 id 与问题。

    前端从别的页面直接点进 ``/explore``（地址栏里没有 run id）时靠它
    找回当前那一轮，并把 id 补进 URL。
    """

    async def _agent(question: str, *, user_id: int, **_: Any) -> AsyncIterator[AgentEvent]:
        yield DoneEvent(session_id="s", elapsed_ms=1, turns=1, input_tokens=1, output_tokens=1)

    await _login(client, api_db)
    monkeypatch.setattr(research_module, "run_agent", _agent)

    with client.stream("POST", "/api/v1/research/ask", json={"question": "第一个问题"}) as resp:
        resp.read()
    first_id = _only_run_id()

    with client.stream("POST", "/api/v1/research/ask", json={"question": "第二个问题"}) as resp:
        resp.read()

    resp = client.get("/api/v1/research/runs/latest")
    assert resp.status_code == 200
    body = resp.json()
    assert body["run_id"] != first_id, "返回的不是最近一轮"
    assert body["question"] == "第二个问题"


async def test_latest_run_returns_404_without_any_run(
    client: TestClient, api_db: AsyncSession
) -> None:
    """没有任何 run 时 404——前端据此停在空态。"""
    await _login(client, api_db)
    resp = client.get("/api/v1/research/runs/latest")
    assert resp.status_code == 404


# ── 新建会话：取消 ────────────────────────────────────────────


async def test_cancel_endpoint_stops_the_run(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, api_db: AsyncSession
) -> None:
    """``DELETE /runs/{id}`` 停掉那一轮。

    「新建会话」时上一轮若还在跑，它会继续烧 token、继续占着并发槽位
    （闸门只有 4 个）。而生成跑在服务端，**断开连接不会终止它** ——
    所以必须显式取消。
    """
    await _login(client, api_db)

    # 建一个 run（不在跑，但也没收尾——所以「可取消」）。
    #
    # 为什么不在这里挂真的后台任务：那条任务属于**测试的**事件循环，
    # 而 DELETE 请求跑在 TestClient 的另一个循环（portal）里 ——
    # `cancel()` 里的 `await gather(task)` 会撞「Future attached to a
    # different loop」。
    #
    # 分开测：「任务被打断」由 ``test_runs.py`` 的
    # ``test_cancel_interrupts_the_background_task`` 守（同循环，无跨循环
    # 问题）；这里守的是**端点接线** —— 找到 run、取消它、返回 200。
    run = get_run_registry().create(user_id=1, question="q")

    resp = client.delete(f"/api/v1/research/runs/{run.id}")
    assert resp.status_code == 200
    assert resp.json()["cancelled"] is True

    assert run.cancelled, "端点返回了 200，但 run 没被标记为已取消"


async def test_cancel_endpoint_rejects_unknown_run(
    client: TestClient, api_db: AsyncSession
) -> None:
    """不存在的 run → 404。"""
    await _login(client, api_db)
    resp = client.delete("/api/v1/research/runs/根本不存在的-id")
    assert resp.status_code == 404


async def test_cancel_endpoint_rejects_other_users_run(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, api_db: AsyncSession
) -> None:
    """别人的 run 不能被取消 —— 一律不给停。"""

    async def _agent(question: str, *, user_id: int, **_: Any) -> AsyncIterator[AgentEvent]:
        yield DoneEvent(session_id="s", elapsed_ms=1, turns=1, input_tokens=1, output_tokens=1)

    await _login(client, api_db, tag="owner")
    monkeypatch.setattr(research_module, "run_agent", _agent)

    with client.stream("POST", "/api/v1/research/ask", json={"question": "q"}) as resp:
        resp.read()
    run_id = _only_run_id()

    client.cookies.set(SESSION_COOKIE, "")
    await _login(client, api_db, tag="intruder")

    resp = client.delete(f"/api/v1/research/runs/{run_id}")
    assert resp.status_code == 404

    run = get_run_registry().get(run_id)
    assert run is not None
    assert not run.cancelled, "别人的 run 被取消了——鉴权漏了"


async def test_latest_run_skips_cancelled_runs(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, api_db: AsyncSession
) -> None:
    """已取消的 run 不算「最近一轮」。

    用户点了「新建会话」，那一轮被取消。离开再回来时回退逻辑会问
    「最近一轮是什么」—— 拿到刚被取消的那个，会接回来一个空界面。
    他明明要的是空白的新会话。
    """

    async def _agent(question: str, *, user_id: int, **_: Any) -> AsyncIterator[AgentEvent]:
        yield DoneEvent(session_id="s", elapsed_ms=1, turns=1, input_tokens=1, output_tokens=1)

    await _login(client, api_db)
    monkeypatch.setattr(research_module, "run_agent", _agent)

    with client.stream("POST", "/api/v1/research/ask", json={"question": "唯一一轮"}) as resp:
        resp.read()
    run_id = _only_run_id()

    # 这一轮已经跑完（closed）。取消对已收尾的 run 不生效（没什么可停的），
    # 但**已取消状态**才是这条要守的性质——所以直接把它标成取消。
    run = get_run_registry().get(run_id)
    assert run is not None
    await run.cancel()

    resp = client.get("/api/v1/research/runs/latest")
    assert resp.status_code == 404, "已取消的 run 还被当成最近一轮"


# ── 取消时落盘：已生成的正文不能丢 ────────────────────────────


async def test_cancelled_run_persists_the_partial_report(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, api_db: AsyncSession
) -> None:
    """取消时，已生成的那半截正文要**落盘**。

    ## 为什么

    用户点了「新建会话」，这一轮已经烧掉的 token 就白烧了 —— 但
    **已经生成的那半截正文是有价值的**。主流项目的做法也是「停止生成后，
    那条消息仍然在历史里」（ChatGPT 的停止按钮）。

    不落盘的话：用户点了「新建会话」，回头在历史报告里找不到这轮 ——
    他明明看到了一半的报告。

    ## 怎么测

    跑**真的** ``run_agent``（落盘逻辑在它的 ``CancelledError`` 分支里），
    只把 ``_run_turn`` 换成会卡住的桩 —— 产出一段正文后卡住，等着被取消。
    """
    from sqlalchemy import select

    from app.models import Report
    from app.services import agent as agent_module
    from app.services.agent import TurnChunk

    release = threading.Event()

    async def _fake_turn(cl: Any, messages: Any, tools: Any) -> AsyncIterator[Any]:
        yield TurnChunk(kind="text", text="这是取消前已经写好的一段正文。")
        await asyncio.to_thread(release.wait, 10.0)

    monkeypatch.setattr(agent_module, "_run_turn", _fake_turn)
    await _login(client, api_db)

    task = asyncio.create_task(
        _drain(agent_module.run_agent("取消测试", user_id=1, db=api_db, vec_engine=None))
    )
    await asyncio.sleep(0.1)  # 让它先产出那段正文

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    release.set()

    rows = (await api_db.execute(select(Report))).scalars().all()
    assert rows, "取消后没有落盘——用户看不到已生成的那半截"
    assert "取消前已经写好" in rows[0].content
    # 取消的报告是**不完整**的，历史列表要能把它和完整报告区分开。
    assert rows[0].truncated is True


async def _drain(agen: Any) -> None:
    """消费一个异步生成器，把事件丢掉（这里只关心落盘）。"""
    async for _ in agen:
        pass
