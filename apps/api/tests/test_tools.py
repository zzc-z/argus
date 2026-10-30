"""工具执行分发测试。

不打真实网络——``_search`` 是模块级私有函数，用 monkeypatch 换成桩。
测的是 argus 自己的逻辑：参数校验、结果裁剪、去重规则、失败降级。
"""

import asyncio
from typing import Any

import pytest

from app.services import tools as tools_module
from app.services.llm import LLMNotConfiguredError
from app.services.tools import (
    ToolOutcome,
    available_tools,
    canonicalize_url,
    execute_tool,
    tool_schemas,
)


@pytest.fixture
def _with_tavily_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """让 get_tavily_client 返回真客户端（配置齐全的场景）。"""
    monkeypatch.setattr(tools_module, "get_tavily_client", lambda: object())


def _raise_not_configured() -> object:
    raise LLMNotConfiguredError("TAVILY_API_KEY 未配置")


# ── URL 规范化 ────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # utm 跟踪参数不参与身份判定
        ("https://a.com/x?utm_source=weibo", "https://a.com/x"),
        ("https://a.com/x?utm_source=a&utm_medium=b", "https://a.com/x"),
        # fragment 是锚点，不影响页面内容
        ("https://a.com/x#section-2", "https://a.com/x"),
        # host 大小写与 www 前缀
        ("https://WWW.A.com/X", "https://a.com/X"),
        # 尾斜杠
        ("https://a.com/x/", "https://a.com/x"),
        ("https://a.com/", "https://a.com/"),
        # 参数顺序不同视为同一条
        ("https://a.com/x?b=2&a=1", "https://a.com/x?a=1&b=2"),
        # 非跟踪参数必须保留
        ("https://a.com/x?id=42", "https://a.com/x?id=42"),
    ],
)
def test_canonicalize_url(raw: str, expected: str) -> None:
    assert canonicalize_url(raw) == expected


def test_canonicalize_ignores_case_in_query_key() -> None:
    """UTM_SOURCE 大写形式也要认得出是跟踪参数。"""
    assert canonicalize_url("https://a.com/x?UTM_SOURCE=w") == "https://a.com/x"


# ── dedup ─────────────────────────────────────────────────────


async def test_dedup_merges_tracking_variants() -> None:
    """同一篇文章的不同分享链接合并成一条。"""
    outcome = await execute_tool(
        "dedup",
        {
            "urls": [
                "https://a.com/x?utm_source=weibo",
                "https://a.com/x",
                "https://a.com/x#top",
                "https://b.com/y",
            ]
        },
    )
    assert outcome.ok is True
    assert outcome.content.count("https://") == 2
    assert "去掉重复 2 条" in outcome.preview


async def test_dedup_preserves_first_occurrence() -> None:
    """保留第一次出现的那个 URL 原样，不做替换。"""
    outcome = await execute_tool("dedup", {"urls": ["https://WWW.a.com/x", "https://a.com/x"]})
    assert outcome.content == "https://WWW.a.com/x"


async def test_dedup_empty_list() -> None:
    outcome = await execute_tool("dedup", {"urls": []})
    assert outcome.ok is True
    assert outcome.content == "（全部 URL 去重后为空）"


async def test_dedup_rejects_non_array() -> None:
    """urls 传错类型时返回错误而不是抛异常。"""
    outcome = await execute_tool("dedup", {"urls": "https://a.com"})
    assert outcome.ok is False
    assert outcome.content == "urls 必须是数组。"


async def test_dedup_skips_blank_entries() -> None:
    """空串不算一条，跳过并计入 ignored。"""
    outcome = await execute_tool("dedup", {"urls": ["https://a.com", "", "   "]})
    assert outcome.content.startswith("https://a.com")
    assert "忽略 2 条" in outcome.preview


# ── dispatch 容错 ─────────────────────────────────────────────


async def test_unknown_tool_returns_error_not_raises() -> None:
    """模型幻觉出的工具名要变成错误文本，不是 KeyError。"""
    outcome = await execute_tool("no_such_tool", {})
    assert outcome.ok is False
    assert "不存在名为 no_such_tool 的工具" in outcome.content
    # 错误文本要告诉模型有哪些工具可选
    assert "tavily_search" in outcome.content


async def test_tavily_search_without_key_returns_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """没配 key 时返回明确中文错误，agent 循环照常跑完。

    **走分类器**：code 与其它失败路径统一（``tool_not_configured``），
    文案带上具体缺哪个配置项。
    """

    def _raise() -> None:
        raise LLMNotConfiguredError("TAVILY_API_KEY 未配置，无法调用该能力")

    monkeypatch.setattr(tools_module, "get_tavily_client", _raise)
    outcome = await execute_tool("tavily_search", {"query": "x"})
    assert outcome.ok is False
    assert "TAVILY_API_KEY" in outcome.content
    assert outcome.preview == "tavily_search 未配置"


async def test_tavily_search_empty_query(
    monkeypatch: pytest.MonkeyPatch, _with_tavily_key: None
) -> None:
    outcome = await execute_tool("tavily_search", {"query": "   "})
    assert outcome.ok is False
    assert "关键词不能为空" in outcome.content


async def test_tavily_search_exception_becomes_failed_outcome(
    monkeypatch: pytest.MonkeyPatch, _with_tavily_key: None
) -> None:
    """底层抛异常要转成 ok=False，不能炸掉 SSE 流。"""

    async def _boom(client: Any, query: str, max_results: int) -> Any:
        raise ConnectionError("代理拒绝连接")

    monkeypatch.setattr(tools_module, "_search", _boom)
    outcome = await execute_tool("tavily_search", {"query": "test"})
    assert outcome.ok is False
    # 网络类异常可重试，且**不把内部细节喂给模型**
    assert outcome.preview == "外部服务不可用"
    assert "代理拒绝连接" not in outcome.content
    assert "暂时无法连接" in outcome.content


async def test_tavily_search_timeout_becomes_failed_outcome(
    monkeypatch: pytest.MonkeyPatch, _with_tavily_key: None
) -> None:
    """超时要变成给模型看的重试提示。"""

    async def _hang(client: Any, query: str, max_results: int) -> Any:
        await asyncio.sleep(99)

    monkeypatch.setattr(tools_module, "_search", _hang)
    monkeypatch.setattr(tools_module, "TAVILY_HARD_TIMEOUT_SECONDS", 0.05)
    outcome = await execute_tool("tavily_search", {"query": "test"})
    assert outcome.ok is False
    assert "超时" in outcome.content


# ── 结果裁剪 ──────────────────────────────────────────────────


async def test_search_result_content_truncated(
    monkeypatch: pytest.MonkeyPatch, _with_tavily_key: None
) -> None:
    """单条 content 超长时截断，且留下可见标记。"""

    async def _fake(client: Any, query: str, max_results: int) -> Any:
        return {"results": [{"title": "长文", "url": "https://a.com", "content": "啊" * 5000}]}

    monkeypatch.setattr(tools_module, "_search", _fake)
    outcome = await execute_tool("tavily_search", {"query": "x"})
    assert outcome.ok is True
    assert "本条已截断" in outcome.content
    assert len(outcome.content) < 1200


async def test_search_results_capped_and_marked(
    monkeypatch: pytest.MonkeyPatch, _with_tavily_key: None
) -> None:
    """总量超上限时截断，且告诉模型「还有几条没显示」。"""

    async def _fake(client: Any, query: str, max_results: int) -> Any:
        return {
            "results": [
                {"title": f"标题{i}", "url": f"https://a.com/{i}", "content": "内容" * 790}
                for i in range(8)
            ]
        }

    monkeypatch.setattr(tools_module, "_search", _fake)
    outcome = await execute_tool("tavily_search", {"query": "x", "max_results": 5})
    # 两种截断分开报，且数字必须准确——报错条数比实际多报会让模型
    # 去找本来就没请求的资料。
    assert "另有 1 条未显示" in outcome.content
    assert "max_results=5 裁掉另外 3 条" in outcome.content
    # 实际展示 4 条
    assert outcome.content.count("URL:") == 4


async def test_search_no_results(monkeypatch: pytest.MonkeyPatch, _with_tavily_key: None) -> None:
    async def _empty(client: Any, query: str, max_results: int) -> Any:
        return {"results": []}

    monkeypatch.setattr(tools_module, "_search", _empty)
    outcome = await execute_tool("tavily_search", {"query": "x"})
    assert outcome.ok is True
    assert outcome.content == "没有搜到相关结果。"


async def test_max_results_clamped(monkeypatch: pytest.MonkeyPatch, _with_tavily_key: None) -> None:
    """模型要 100 条时要夹到上限，不能真发 100 条请求。"""
    seen: dict[str, int] = {}

    async def _fake(client: Any, query: str, max_results: int) -> Any:
        seen["n"] = max_results
        return {"results": []}

    monkeypatch.setattr(tools_module, "_search", _fake)
    await execute_tool("tavily_search", {"query": "x", "max_results": 100})
    assert seen["n"] == tools_module.SEARCH_MAX_RESULTS


async def test_max_results_garbage_falls_back(
    monkeypatch: pytest.MonkeyPatch, _with_tavily_key: None
) -> None:
    """max_results 传了非数字时退回默认，不抛异常。"""
    seen: dict[str, int] = {}

    async def _fake(client: Any, query: str, max_results: int) -> Any:
        seen["n"] = max_results
        return {"results": []}

    monkeypatch.setattr(tools_module, "_search", _fake)
    outcome = await execute_tool("tavily_search", {"query": "x", "max_results": "很多"})
    assert outcome.ok is True
    assert seen["n"] == 3


# ── 工具列表按配置过滤 ────────────────────────────────────────


def test_available_tools_excludes_tavily_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """key 没配时 tavily_search 不出现——模型看不到就不会调它。"""

    def _raise() -> None:
        raise LLMNotConfiguredError("TAVILY_API_KEY 未配置")

    monkeypatch.setattr(tools_module, "get_tavily_client", _raise)
    names = [spec.name for spec in available_tools()]
    assert "tavily_search" not in names
    assert "dedup" in names


def test_available_tools_includes_all_when_configured(
    monkeypatch: pytest.MonkeyPatch, _with_tavily_key: None
) -> None:
    assert {t.name for t in available_tools()} == {
        "tavily_search",
        "local_search",
        "dedup",
    }


def test_available_tools_drops_local_without_db(
    monkeypatch: pytest.MonkeyPatch, _with_tavily_key: None
) -> None:
    """没有数据库连接时摘掉 local_search——模型看不到就不会浪费一轮去调它。"""
    names = {t.name for t in available_tools(has_local=False)}
    assert "local_search" not in names
    assert "tavily_search" in names


def test_available_tools_drops_tavily_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tavily 没配时摘掉搜索工具，但本地检索要留着。"""
    monkeypatch.setattr(tools_module, "get_tavily_client", _raise_not_configured)
    names = {t.name for t in available_tools(has_local=True)}
    assert names == {"local_search", "dedup"}


def test_available_tools_order_is_stable(
    monkeypatch: pytest.MonkeyPatch, _with_tavily_key: None
) -> None:
    """工具顺序必须固定——set 的迭代顺序随 PYTHONHASHSEED 变，
    同一份配置两次启动给出不同的 tools 数组会让 prompt 缓存失效。"""
    first = [t.name for t in available_tools()]
    second = [t.name for t in available_tools()]
    assert first == second
    assert first == ["tavily_search", "local_search", "dedup"]


def test_tool_schemas_shape() -> None:
    """转成 API 格式后每个工具都有 name/description/input_schema。"""
    schemas = tool_schemas(available_tools())
    for schema in schemas:
        assert set(schema) == {"name", "description", "input_schema"}
        assert schema["input_schema"]["type"] == "object"


async def test_formats_real_tavily_response_shape(
    monkeypatch: pytest.MonkeyPatch, _with_tavily_key: None
) -> None:
    """字段名以**真实 Tavily 响应**为准，不是照文档猜的。

    2026-10-13 拿真 key 实测：顶层键是
    ``answer/follow_up_questions/images/query/request_id/response_time/results``，
    每条 result 是 ``content/id/raw_content/score/title/url``。

    此前所有测试都用 mock 字典，字段名对不对从没验证过——真把
    ``snippet`` 当 content 读，格式化出来全是空块，而测试照样全绿。
    """
    real_item: dict[str, object] = {
        "content": "The NVIDIA GB200 NVL72 is a liquid-cooled, rack-scale solution.",
        "id": "abc123",
        "raw_content": None,
        "score": 0.87,
        "title": "CoreWeave launches NVIDIA GB200 NVL72 instances",
        "url": "https://www.investing.com/news/coreweave-gb200",
    }

    async def _fake(client: Any, query: str, max_results: int) -> Any:
        return {
            "answer": None,
            "follow_up_questions": None,
            "images": None,
            "query": query,
            "request_id": "req-1",
            "response_time": 1.23,
            "results": [real_item],
        }

    monkeypatch.setattr(tools_module, "_search", _fake)
    outcome = await execute_tool("tavily_search", {"query": "GB200"})

    assert outcome.ok is True
    assert str(real_item["title"]) in outcome.content
    assert str(real_item["url"]) in outcome.content
    assert "liquid-cooled" in outcome.content


def test_tavily_search_schema_survives_without_key(
    monkeypatch: pytest.MonkeyPatch, _with_tavily_key: None
) -> None:
    """``tavily_search`` 的 schema 形状必须单独验——它不随环境变。

    ``test_tool_schemas_shape`` 走 ``available_tools()``，而 conftest 的
    autouse 隔离让那函数恒返回 ``{local_search, dedup}``。于是
    ``tavily_search`` 的 ``input_schema.properties`` 自 2026-10-13 起因
    「环境里没 key」就再没被任何测试碰到——这正是模型能不能正确传参
    的地方，漏了不会有任何报错。
    """
    schema = next(
        s for s in tool_schemas(available_tools(has_local=True)) if s["name"] == "tavily_search"
    )
    props = schema["input_schema"]["properties"]
    assert "query" in props
    assert props["query"]["type"] == "string"
    # query 必须是必填：模型漏传时上游返回 400，而 tools.py 里那句
    # `if not query: return 参数错误` 就永远走不到。schema 与实现脱节
    # 时症状是「模型传空 query → Tavily 报 BadRequest」，看着像配额问题。
    assert schema["input_schema"]["required"] == ["query"]
    assert "max_results" in props
    assert "max_results" in props
