"""Supervisor / Analyst 两个节点的测试。

这两个节点走 ``client.messages.create``（不经过主循环的 ``_run_turn``），
所以 ``test_agent_loop`` 里的桩拦不住它们——本文件自己造桩。

覆盖的三个不变量：

1. **失败不崩**：模型调用失败、JSON 不合法、返回垃圾结构时，一律降级成
   空结果，主循环照常跑。
2. **降级要能被看见**：降级不是静默的——它要么有产出，要么日志里有一条。
3. **token 要记账**：这两个节点真的调了模型，不记的话用量统计系统性偏低。
"""

from typing import Any

import pytest

from app.services import stages

# ── 测试替身 ──────────────────────────────────────────────────


class _FakeMessage:
    def __init__(self, text: str, input_tokens: int = 10, output_tokens: int = 5) -> None:
        self._text = text
        self.usage = type(
            "Usage", (), {"input_tokens": input_tokens, "output_tokens": output_tokens}
        )()

    def model_dump(self, exclude_none: bool = True) -> dict[str, Any]:
        return {"content": [{"type": "text", "text": self._text}]}


class _FakeMessages:
    """模拟 ``client.messages``。按脚本依次返回。"""

    def __init__(self, script: list[Any]) -> None:
        self._script = list(script)
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> _FakeMessage:
        self.calls.append(kwargs)
        item = self._script.pop(0) if self._script else None
        if isinstance(item, Exception):
            raise item
        return _FakeMessage(item or "")


class _FakeClient:
    def __init__(self, script: list[Any]) -> None:
        self.messages = _FakeMessages(script)


# ── Supervisor ────────────────────────────────────────────────


async def test_plan_parses_subtasks() -> None:
    """正常返回：子任务被解析出来。"""
    client = _FakeClient(['{"subtasks": ["查市场规模", "查主要玩家"]}'])

    plan = await stages.plan_subtasks(client, "市场规模多大？", has_local=True)

    assert plan.subtasks == ["查市场规模", "查主要玩家"]


async def test_plan_reports_token_usage() -> None:
    """token 必须能拿到——调用方要记进用量账本。"""
    client = _FakeClient(['{"subtasks": ["a"]}'])

    plan = await stages.plan_subtasks(client, "q", has_local=True)

    assert plan.input_tokens == 10
    assert plan.output_tokens == 5


async def test_plan_degrades_on_model_error() -> None:
    """模型报错时降级成空结果，**不抛**。

    抛出去会让整轮研究崩掉——正文已经流给用户了。
    """
    client = _FakeClient([RuntimeError("上游炸了")])

    plan = await stages.plan_subtasks(client, "q", has_local=True)

    assert plan.subtasks == []


async def test_plan_degrades_on_invalid_json() -> None:
    """模型返回的不是 JSON 时降级，不抛。"""
    client = _FakeClient(["这不是 JSON，只是一段话。"])

    plan = await stages.plan_subtasks(client, "q", has_local=True)

    assert plan.subtasks == []


async def test_plan_ignores_non_string_items() -> None:
    """模型混进数字/null 时只留字符串项。

    非字符串直接拼进提示会渲染成 "None" 之类的东西喂回模型。
    """
    client = _FakeClient(['{"subtasks": ["好的", 123, null, "  ", "也好"]}'])

    plan = await stages.plan_subtasks(client, "q", has_local=True)

    assert plan.subtasks == ["好的", "也好"]


async def test_plan_mentions_missing_local_search() -> None:
    """没有私有资料时，提示里必须说明——否则模型会规划依赖私有库的子任务。"""
    client = _FakeClient(['{"subtasks": []}'])

    await stages.plan_subtasks(client, "q", has_local=False)

    prompt = client.messages.calls[0]["messages"][0]["content"]
    assert "无法检索用户的私有资料" in prompt


async def test_plan_caps_subtask_count() -> None:
    """子任务最多 5 个——再多就是模型在划水。"""
    client = _FakeClient(['{"subtasks": ["1","2","3","4","5","6","7"]}'])

    plan = await stages.plan_subtasks(client, "q", has_local=True)

    assert len(plan.subtasks) == 5


# ── Analyst ───────────────────────────────────────────────────


def _evidence(count: int) -> list[stages.Evidence]:
    return [
        stages.Evidence(n=i, title=f"来源{i}", excerpt=f"第{i}条证据的内容")
        for i in range(1, count + 1)
    ]


async def test_analysis_finds_conflicts() -> None:
    """正常返回：矛盾被解析出来。"""
    client = _FakeClient(['{"conflicts": ["A 说 2024，B 说 2023"], "synthesis": "年份存疑"}'])

    analysis = await stages.analyze_evidence(client, _evidence(2))

    assert analysis.conflicts == ["A 说 2024，B 说 2023"]
    assert analysis.synthesis == "年份存疑"


async def test_analysis_skips_single_evidence() -> None:
    """只有一条证据时不调模型。

    一条证据没有「交叉」的对象——硬凑一次调用只烧 token。
    """
    client = _FakeClient(['{"conflicts": [], "synthesis": ""}'])

    analysis = await stages.analyze_evidence(client, _evidence(1))

    assert analysis.conflicts == []
    # 关键：根本没调模型
    assert client.messages.calls == []


async def test_analysis_degrades_on_model_error() -> None:
    """模型报错时降级成空结果，不抛。"""
    client = _FakeClient([RuntimeError("上游炸了")])

    analysis = await stages.analyze_evidence(client, _evidence(3))

    assert analysis.conflicts == []
    assert analysis.synthesis == ""


async def test_analysis_degrades_on_invalid_json() -> None:
    client = _FakeClient(["完全不是 JSON"])

    analysis = await stages.analyze_evidence(client, _evidence(3))

    assert analysis.conflicts == []


async def test_analysis_accepts_empty_conflicts() -> None:
    """没有矛盾是正常结果——不能当成失败。"""
    client = _FakeClient(['{"conflicts": [], "synthesis": "证据一致"}'])

    analysis = await stages.analyze_evidence(client, _evidence(3))

    assert analysis.conflicts == []
    assert analysis.synthesis == "证据一致"


async def test_analysis_reports_token_usage() -> None:
    client = _FakeClient(['{"conflicts": [], "synthesis": "x"}'])

    analysis = await stages.analyze_evidence(client, _evidence(3))

    assert analysis.input_tokens == 10
    assert analysis.output_tokens == 5


# ── 提示拼装 ──────────────────────────────────────────────────


def test_plan_prompt_line_is_empty_without_subtasks() -> None:
    """没有拆解结果时不能拼出空提示——那会让提示里多一段空白。"""
    assert stages.Plan().as_prompt_line() == ""


def test_plan_prompt_line_lists_subtasks() -> None:
    line = stages.Plan(subtasks=["查 A", "查 B"]).as_prompt_line()

    assert "查 A" in line
    assert "查 B" in line


def test_analysis_prompt_block_is_empty_without_findings() -> None:
    """没有矛盾也没有综合结论时，不拼提示块。"""
    assert stages.Analysis().as_prompt_block() == ""


def test_analysis_prompt_block_mentions_conflicts() -> None:
    """矛盾必须出现在给 Writer 的提示里——它要正面处理，不能并列成事实。"""
    block = stages.Analysis(conflicts=["A 与 B 冲突"], synthesis="综合").as_prompt_block()

    assert "A 与 B 冲突" in block
    assert "综合" in block


async def test_analysis_excerpt_is_truncated() -> None:
    """证据原文要截断——全文贴进 prompt 会膨胀到几万 token。"""
    client = _FakeClient(['{"conflicts": [], "synthesis": ""}'])
    long_text = "x" * 5000

    await stages.analyze_evidence(
        client,
        [
            stages.Evidence(n=1, title="t", excerpt=long_text),
            stages.Evidence(n=2, title="t", excerpt="y"),
        ],
    )

    prompt = client.messages.calls[0]["messages"][0]["content"]
    assert "x" * (stages.EVIDENCE_EXCERPT_CHARS + 1) not in prompt
    assert "x" * stages.EVIDENCE_EXCERPT_CHARS in prompt


async def test_uses_configured_model_override() -> None:
    """按角色的模型覆盖要生效（``ANTHROPIC_ANALYST_MODEL`` 等）。"""
    from app.config import get_settings

    settings = get_settings()
    original = settings.anthropic_analyst_model
    try:
        settings.anthropic_analyst_model = "some-other-model"
        client = _FakeClient(['{"conflicts": [], "synthesis": ""}'])

        await stages.analyze_evidence(client, _evidence(2))

        assert client.messages.calls[0]["model"] == "some-other-model"
    finally:
        settings.anthropic_analyst_model = original
