"""单轮模型请求：拼请求、发流式、收结果。

## 为什么独立成模块

主循环（``agent.py``）管的是「多轮之间怎么推进」，这一层管的是
「一轮请求怎么发出去」。两者各自都够长，合在一个文件里会超 800 行。

## 三条硬约束

1. **正文边收边发**。攒完再发 = 用户看到「憋十几秒然后整段蹦出来」。
2. **thinking block 原样回传**。模型的扩展思考带 signature，改动或丢失
   会导致下一轮请求被拒。它是内部推理过程，前端要的是研究结论不是思维链。
3. **流被掐断时整轮重发**。已发出的正文撤不回来，只能整轮重来——
   重发前必须先发 ``reset`` 让前端清零（少了它用户会看到同一段正文两遍）。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, cast

from anthropic import AsyncAnthropic

from app.config import get_settings
from app.services.llm import (
    STREAM_INTERRUPT_BACKOFF_SECONDS,
    STREAM_INTERRUPT_RETRIES,
    is_stream_interrupt,
)
from app.services.stream import Typewriter
from app.services.tools import ToolSpec, tool_schemas

logger = logging.getLogger(__name__)

# 单轮输出总预算。thinking 有自己的上限（THINKING_BUDGET_TOKENS）。
MAX_OUTPUT_TOKENS = 4096

# 扩展思考的独立预算。
#
# 不设它，思考会膨胀到把 MAX_OUTPUT_TOKENS 吃光，正文一个字写不出来
# （表现为 empty_response）。**重试没用**——实测连打 5 次全部同样被吃光，
# 是确定性的不是偶发。详见 ``_build_turn_request`` 的说明。
THINKING_BUDGET_TOKENS = 2048

# 只写**跨工具的编排规则**，不写「有工具 X 可用」——那些已经在各自的
# description 里了（见 app/services/tools.py 的 *_SPEC.description）。
#
# Anthropic 官方的分工是：工具的「是什么/何时用」属于 tool description，
# system prompt 负责「when and when not to use」这类编排。重复写一遍是
# 冗余 token，还会和 tools 数组脱节——写死在这里的 tavily_search 在
# 没配 key 时并不存在，模型却被指示去调它。
#
# 下面第 2 条是**唯一**必须在 system prompt 里说的：它是跨两个工具的
# 优先级顺序，任何单个 description 都承载不了这个信息。
SYSTEM_PROMPT = """你是 Argus 的研究助手，回答用户的研究类问题。

工作方式：
- 你有若干可用工具，各工具的适用场景写在它自己的描述里，按描述选择。
- 检索优先级：先用私有资料工具查用户自己的文档；它没有覆盖的部分，
  再考虑联网搜索。私有资料是用户特意上传的，优先级高于公开搜索结果。
- 检索到的链接用 dedup 清理，避免把同一篇文章当成多份独立证据。
- 资料不足时，明确说明缺什么，不要编造数据或引用。
- 最终回答用中文，结构清晰；涉及数据时写明来源。

写作要求：
- 先给结论，再给依据。
- 用 Markdown 组织内容，该用小标题和列表就用。
- 不要输出思考过程，只输出结论与依据。"""


@dataclass(frozen=True, slots=True)
class TurnResult:
    """一轮模型请求的结果。

    ``content`` 是原样回传给下一轮的 assistant 内容——含 thinking block
    及其 signature。``text`` 是这轮产出的正文，供前端流式展示。
    """

    content: list[dict[str, Any]]
    text: str
    tool_calls: list[dict[str, Any]]
    stop_reason: str
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True, slots=True)
class TurnChunk:
    """一轮流式请求里的一个片段。

    ``kind="text"`` 是正文增量（已经过展示切片，可以直接发给前端）；
    ``kind="result"`` 是这一轮的收尾——usage / stop_reason / tool_calls；
    ``kind="reset"`` 表示「已发出的正文作废，从头再来」——只在流被掐断
    后整轮重发时出现。
    """

    kind: str  # "text" | "result" | "reset"
    text: str = ""
    result: TurnResult | None = None


async def _run_turn(
    client: AsyncAnthropic,
    messages: list[dict[str, Any]],
    tools: tuple[ToolSpec, ...],
) -> AsyncIterator[TurnChunk]:
    """跑一轮流式请求，**边收边发**。

    ## 为什么必须是生成器而不是「收完再返回」

    原实现是 ``await stream.get_final_message()`` —— 把整轮流攒完再返回，
    主循环随后一次性把正文切好发出去。用户看到的是「憋十几秒，然后整段
    蹦出来」，完全没有打字机效果。

    而上游**本来就是真流式**（实测 2026-10-30，中转站 llmapi.pro）：

    | 正文长度 | 上游到达方式 |
    |---|---|
    | 156 字 | 49 个 text_delta 全在 4.082s 那一刻挤着到 |
    | 1662 字 | 526 个 text_delta，5.0s→13.9s 渐进到达 |

    也就是说长文本的上游逐字吐，我们把增量全丢掉、攒成整段才发。
    改成消费 ``content_block_delta`` 就能拿到真流式。

    ## 正文与工具调用分家

    一轮响应里既有 text 块也有 tool_use 块（实测 thinking → text →
    tool_use 的顺序）。只有 **text 块**的增量能发给用户：tool_use 的
    ``partial_json`` 是工具入参，发出去会漏出模型没打算展示的内容，
    而且前端会把它当正文渲染。

    ## 流被掐断时的整轮重发

    中转站会在 SSE 流消费途中随机断开连接，而 SDK 的 ``max_retries`` 只覆盖
    建连阶段，够不到这里。见 ``llm.is_stream_interrupt`` 的说明。断流后
    **整轮重发**——已发出的正文不能撤，只能整轮重来。

    重发会从头再生成一遍，而上游有随机性（实测同一 prompt 连发 4 次，
    字数 1653/1155/1737/2164 各不相同），没法靠裁剪前缀去重。所以重发前
    发一个 ``reset`` 标记，让前端把这一轮已收到的正文清零——少了它，
    用户会看到同一段正文出现两遍。
    """
    request = _build_turn_request(messages, tools)
    last_exc: BaseException | None = None
    # 这一轮是否已经往用户那里发过正文。断流重发时要靠它决定
    # 要不要发 reset 标记。
    sent_any = False

    for attempt in range(STREAM_INTERRUPT_RETRIES + 1):
        try:
            async for chunk in _stream_turn_once(client, request):
                if chunk.kind == "text":
                    sent_any = True
                yield chunk
            return
        except Exception as exc:
            if not is_stream_interrupt(exc):
                raise
            last_exc = exc
            logger.warning(
                "模型流被中断，第 %d 次重发整轮请求：%s",
                attempt + 1,
                type(exc).__name__,
            )
            # 已经发出去的正文作废——重发会从头再来一遍。
            # 只在**确实发过东西**时才发 reset：纯工具轮断流，
            # 前端正文区是空的，清它没有意义。
            if sent_any:
                yield TurnChunk(kind="reset")
            if attempt < STREAM_INTERRUPT_RETRIES:
                # 指数退避：第 n 次重发等 ``基数 * 2**(n-1)`` 秒（1s → 2s）。
                #
                # 固定间隔的实测问题（2026-11-01）：本机网络层抖动时
                # （Tavily 与 Anthropic 同秒断开），3 次重发挤在同一秒里
                # 全挂在同一个坏窗口内。指数退避把最后一次重发推到
                # 3 秒之后，抖动窗口大概率已过。
                await asyncio.sleep(STREAM_INTERRUPT_BACKOFF_SECONDS * (2**attempt))
            continue

    # 走到这里说明每次尝试都被掐断了。把最后一次的异常原样抛出去——
    # 调用方要靠它判断「流中断」还是别的错误来决定错误文案。
    assert last_exc is not None
    raise last_exc


async def _stream_turn_once(
    client: AsyncAnthropic,
    request: dict[str, Any],
) -> AsyncIterator[TurnChunk]:
    """跑一次流式请求，把上游事件翻译成 ``TurnChunk``。

    产出顺序：正文增量（``kind="text"``，可以有多段）→ 整轮结果
    （``kind="result"``）。``result`` 一定在最后——它是这一轮的收尾
    （usage / stop_reason / tool_calls），调用方靠它记账。
    """
    typewriter = Typewriter()

    async with client.messages.stream(**cast("Any", request)) as stream:
        async for event in stream:
            event_type = getattr(event, "type", "")
            if event_type != "content_block_delta":
                continue
            delta = getattr(event, "delta", None)
            chunk_text = getattr(delta, "text", None)
            # text_delta 才有 text；input_json_delta 是 partial_json——
            # 那是工具入参，不能发给用户（会漏出模型没打算展示的内容）。
            if not isinstance(chunk_text, str):
                continue
            # 切完立刻发。不攒着：攒到最后就退化成「收完再发」，
            # 那正是这个改动要修的问题。
            async for piece in typewriter.feed(chunk_text):
                yield TurnChunk(kind="text", text=piece)

        # 流结束：把尾巴切出来，与前面的片段同一粒度。
        async for piece in typewriter.flush():
            yield TurnChunk(kind="text", text=piece)

        final = await stream.get_final_message()

    yield TurnChunk(kind="result", result=_to_turn_result(final))


def _build_turn_request(
    messages: list[dict[str, Any]],
    tools: tuple[ToolSpec, ...],
) -> dict[str, Any]:
    """拼出一轮请求的载荷。空 tools 时不带 tools 参数。

    ## 为什么必须单独限制 thinking 预算

    不设 ``thinking`` 时模型的扩展思考**没有上限**，会一直膨胀到把
    ``max_tokens`` 吃光——正文一个字都写不出来。实测（2026-10-29，中转站
    llmapi.pro，claude-sonnet-5，max_tokens=4096）：

    | 请求里的 thinking | thinking 消耗 | 正文 |
    |---|---|---|
    | **不设（现状）** | 吃满 4096 | **0 字** ❌ |
    | ``budget_tokens=1024`` | 独立预算 | 6443 字 ✅ |
    | ``budget_tokens=2048`` | 独立预算 | 1523 字 ✅ |
    | ``type=disabled`` | 关掉 | 6456 字 ✅ |

    症状是 ``stop_reason="max_tokens"`` 且正文为空 → 循环跑完 → ``empty_response``：
    「模型未产出内容，请重试」。而重试**没用**——实测连打 5 次全部同样被吃光
    （每次 output_tokens 都是 4096、正文 0 字），它是确定性的，不是偶发。

    所以修复点是**限制 thinking 预算**，而不是加大 ``max_tokens``（那只是让
    思考吃更多）。``max_tokens`` 保持不变：它管总输出上限，thinking 有自己的
    上限，两者不冲突。

    ## 为什么选 2048

    实测三个预算都能出正文，但 1024 时思考空间偏小（模型会更快转向正文、
    深度不足）；3072 时留给正文的余量变少。2048 是「思考够用、正文够写」
    的折中。改这个值前请重跑上表那组实测——**不同问题对思考深度的需求不同**。

    注意 ``stop_reason="max_tokens"`` 在设了 thinking 预算之后**仍然常见**
    （实测每次都是）：它表示「总输出触顶」，在 thinking 有独立预算后**不再
    等于失败**。判据是「有没有正文」，不是 stop_reason。
    """
    settings = get_settings()
    request: dict[str, Any] = {
        "model": settings.anthropic_complex_model,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "system": SYSTEM_PROMPT,
        "messages": messages,
        "thinking": {"type": "enabled", "budget_tokens": THINKING_BUDGET_TOKENS},
    }
    if tools:
        request["tools"] = tool_schemas(tools)
    return request


def _to_turn_result(final: Any) -> TurnResult:
    """把 SDK 的 Message 收成 TurnResult。"""
    # exclude_none：text block 的 citations 字段在无引用时是 None。
    # 中转站实测能接受，但直连官方 API 时可能被严格模式拒收，
    # 带上 exclude_none 没有代价。
    content = cast("list[dict[str, Any]]", final.model_dump(exclude_none=True)["content"])

    text = "".join(b.get("text", "") for b in content if b.get("type") == "text")
    tool_calls = [b for b in content if b.get("type") == "tool_use"]

    return TurnResult(
        content=content,
        text=text,
        tool_calls=tool_calls,
        stop_reason=final.stop_reason or "end_turn",
        input_tokens=final.usage.input_tokens,
        output_tokens=final.usage.output_tokens,
    )
