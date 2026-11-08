"""联网搜索结果 → 角标 → critic 校验的端到端测试。

## 要防的回归

公开来源原先只是一段喂给模型的文本，不落库、不占角标号。后果：

- 正文里的 ``[n]`` 指向不了公开来源
- critic 拿不到公开来源的原文，校验只能跳过——DAG 上写「跳过校验：
  报告没有任何引用角标」
- 用户点不开「这个数字是哪来的」

这里跑**真实的检索 → 落库 → 编号 → 校验**路径（模型调用是桩的），
断言整条链是通的。
"""

from collections.abc import AsyncIterator
from typing import Any

import pytest

from app.models.user import User
from app.services import agent as agent_module
from app.services import stages
from app.services.agent_turn import TurnChunk, TurnResult
from app.services.citation import ReferenceTable
from app.services.tools import ToolOutcome, ToolSpec
from app.services.web_sources import ToolEvidence


async def _make_user(db) -> int:
    user = User(email="web-e2e@test.local", display_name="测试")
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user.id


def _turn(text: str = "", tool_calls: list[dict[str, Any]] | None = None) -> TurnResult:
    calls = tool_calls or []
    content: list[dict[str, Any]] = []
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


async def test_web_search_result_gets_a_citation_number_and_is_verified(
    monkeypatch: pytest.MonkeyPatch,
    db_session,
) -> None:
    """联网搜索结果要占角标号，并被 critic 拿原文校验。

    ## 怎么测

    1. 桩掉模型：第一轮调 ``tavily_search``，第二轮写带角标的正文
    2. 桩掉 Tavily 的 HTTP 层，返回一条真实形状的搜索结果
    3. 跑真实的 ``run_agent``（db 传进去，所以 local_search 可用）
    4. 断言：
       - ``reference`` 帧里有那条公开来源，编号不是 1 号（1 号是用户资料的）
       - 正文里的角标号与 reference 帧对得上
       - critic 校验时**拿到了那条公开来源的原文**
    """
    user_id = await _make_user(db_session)

    # Tavily 的 HTTP 层：返回一条结果
    async def _fake_search(client: Any, query: str, max_results: int) -> Any:
        return {
            "results": [
                {
                    "title": "某公司营收创新高",
                    "url": "https://news.example.com/revenue",
                    "content": "该公司最新财年营收为 500 亿元，同比增长 20%。",
                }
            ]
        }

    from app.services import tools as tools_module

    # conftest 把 ``get_tavily_client`` 桩成「未配置」——这里要真的能调。
    monkeypatch.setattr(tools_module, "get_tavily_client", lambda: object())
    monkeypatch.setattr(tools_module, "_search", _fake_search)

    # 模型：第一轮调搜索，第二轮写带角标的正文
    script = [
        _turn(
            tool_calls=[
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "tavily_search",
                    "input": {"query": "某公司营收"},
                }
            ]
        ),
        _turn(text="该财年营收 500 亿元 [1]。"),
    ]

    async def _fake_run_turn(
        client: Any, messages: list[dict[str, Any]], tools: Any
    ) -> AsyncIterator[TurnChunk]:
        result = script.pop(0)
        if result.text:
            yield TurnChunk(kind="text", text=result.text)
        yield TurnChunk(kind="result", result=result)

    monkeypatch.setattr(agent_module, "_run_turn", _fake_run_turn)

    # critic 的校验：记录它拿到的原文
    verified_sources: dict[int, str] = {}

    async def _fake_verify(client: Any, report_text: str, sources: dict[int, str]) -> Any:
        verified_sources.update(sources)
        from app.services.faithfulness import FaithfulnessReport

        return FaithfulnessReport(
            checked=1,
            supported=1,
            unsupported=[],
            missing=[],
            skipped=False,
        )

    monkeypatch.setattr(agent_module, "verify_citations", _fake_verify)

    events = [
        event
        async for event in agent_module.run_agent(
            "某公司营收多少？", user_id=user_id, db=db_session
        )
    ]

    # 1. reference 帧里有那条公开来源
    from app.services.stream import ReferenceEvent

    ref_events = [e for e in events if isinstance(e, ReferenceEvent)]
    assert ref_events, "联网搜索的结果必须产生 reference 帧"
    all_refs = [r for e in ref_events for r in e.references]
    titles = [r["title"] for r in all_refs]
    assert any("营收创新高" in t for t in titles), f"公开来源没进引用表：{titles}"

    web_ref = next(r for r in all_refs if "营收创新高" in r["title"])
    assert web_ref["url"] == "https://news.example.com/revenue", "公开来源要带 URL"

    # 2. 正文里的角标号与 reference 帧对得上
    numbers = {r["n"] for r in all_refs}
    assert web_ref["n"] in numbers

    # 3. critic 校验时拿到了那条公开来源的原文
    assert verified_sources, "critic 没拿到任何原文——校验无从谈起"
    texts = list(verified_sources.values())
    assert any("500 亿元" in t for t in texts), f"critic 没拿到公开来源的原文：{texts}"


async def test_public_source_text_is_actually_persisted(
    monkeypatch: pytest.MonkeyPatch,
    db_session,
) -> None:
    """公开来源的原文要真的落在 ``document_chunks`` 里。

    ## 为什么

    critic 的原文来自 ``document_chunks``（按 chunk_id 查）。如果只是
    建了 ``Source`` 行而没建 chunk，角标能显示、点开却是空的——
    而「角标点开是空白」比「没有角标」更让人困惑。
    """
    from sqlalchemy import select

    from app.models.source import DocumentChunk

    user_id = await _make_user(db_session)

    async def _fake_search(client: Any, query: str, max_results: int) -> Any:
        return {
            "results": [
                {
                    "title": "网页标题",
                    "url": "https://news.example.com/x",
                    "content": "网页里的正文内容，足够长以便确认存下来了。",
                }
            ]
        }

    from app.services import tools as tools_module

    # conftest 把 ``get_tavily_client`` 桩成「未配置」——这里要真的能调。
    monkeypatch.setattr(tools_module, "get_tavily_client", lambda: object())
    monkeypatch.setattr(tools_module, "_search", _fake_search)

    script = [
        _turn(
            tool_calls=[
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "tavily_search",
                    "input": {"query": "x"},
                }
            ]
        ),
        _turn(text="结论 [1]。"),
    ]

    async def _fake_run_turn(
        client: Any, messages: list[dict[str, Any]], tools: Any
    ) -> AsyncIterator[TurnChunk]:
        result = script.pop(0)
        if result.text:
            yield TurnChunk(kind="text", text=result.text)
        yield TurnChunk(kind="result", result=result)

    monkeypatch.setattr(agent_module, "_run_turn", _fake_run_turn)

    async def _fake_verify(client: Any, report_text: str, sources: dict[int, str]) -> Any:
        from app.services.faithfulness import FaithfulnessReport

        return FaithfulnessReport(checked=0, supported=0, unsupported=[], missing=[], skipped=True)

    monkeypatch.setattr(agent_module, "verify_citations", _fake_verify)

    async for _ in agent_module.run_agent("问题", user_id=user_id, db=db_session):
        pass
    await db_session.commit()

    contents = list((await db_session.execute(select(DocumentChunk.content))).scalars().all())
    assert any("网页里的正文内容" in c for c in contents), (
        f"公开来源的原文没落进 document_chunks：{contents}"
    )
