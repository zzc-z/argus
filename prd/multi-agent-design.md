# Argus — 多 Agent 编排设计

> Version: 0.1.0 · Date: 2026-09-18

## 1. 角色与职责

Argus 采用 **Supervisor + Worker** 模式，5 个 agent 协同：

> **模型选型（2026-09 升级）**：Sonnet 4.5 → **Sonnet 5**（2026-06 末 GA，Sonnet 4.5 在 09-29 退役）。Haiku 4.5 仍可用，10-15 退役。

### 1.1 Supervisor（调度者）
- **模型**：**Claude Sonnet 5**
- **职责**：
  - 接收用户研究任务
  - 拆解为子任务
  - 决定下一步调度哪个 worker
  - 监控 worker 进度，必要时终止或重试
  - 决定何时结束（产出可用时）
- **不允许**：直接调用外部工具；只调度 worker

### 1.2 Researcher（资料员）
- **模型**：**Claude Sonnet 5**
- **工具**：
  - `tavily_search(query, top_k=10)` — 实时网络搜索
  - `web_fetch(url)` — 单 URL 结构化抓取
  - `web_scrape(urls[], include_media=True)` — 多 URL 批量抓取（含视频转写 / OCR）
  - `rag_retrieve(query, top_k=20, filters)` — 私有资料库检索
  - `memory_recall(user_id, query)` — 长期记忆召回
- **输出**：raw_evidence list（带 url / source_type / credibility_score / excerpt / timestamp）

### 1.3 Analyst（分析员）
- **模型**：**Claude Haiku 4.5**
- **工具**：
  - `dedup(items)` — 跨源去重（URL canonical + simhash）
  - `sentiment(text)` — 舆情倾向
  - `classify(items, taxonomy)` — 主题分类
  - `extract_entities(text)` — 实体抽取（公司 / 人名 / 产品）
  - `timeline(items)` — 构建时间线
  - `compare(items[], dim)` — 多维度对比
- **输出**：structured_findings dict（含 confidence / source_ids / reasoning）

### 1.4 Writer（写作员）
- **模型**：**Claude Sonnet 5**
- **工具**：
  - `generate_report(findings, format)` — 生成长文（带 [n] 引用）
  - `generate_comparison_table(items, dims)` — 对比表
  - `generate_timeline(items)` — 时间线
  - `generate_decision_list(question, findings)` — 决策清单
- **输出**：draft_report（markdown + structured json）

### 1.5 Critic（评审员）
- **模型**：**Claude Haiku 4.5**
- **工具**：
  - `verify_citation(claim, sources)` — 验证引用真实性
  - `check_faithfulness(report, sources)` — 忠实度评分
  - `detect_hallucination(report)` — 幻觉检测
  - `score_relevance(report, original_query)` — 相关性
- **输出**：review dict（passed / issues / score / suggestions）

## 2. LangGraph 状态机

### 2.1 State Schema

```python
from typing import TypedDict, Annotated, List
from langgraph.graph.message import add_messages

class ResearchState(TypedDict):
    # 任务
    user_id: str
    query: str
    session_id: str

    # 计划
    plan: List[SubTask]
    current_step: int

    # 资料
    raw_evidence: Annotated[List[Evidence], append]
    structured_findings: Annotated[List[Finding], append]

    # 输出
    draft_report: str
    review: Review

    # 元数据
    messages: Annotated[List[BaseMessage], add_messages]
    token_usage: dict
    trace_id: str
```

### 2.2 节点图（含中文注解）

```
                      【起点】
                    ┌─────────────────┐
                    │   __start__     │ ←── 研究任务进入
                    └────────┬────────┘
                             │ 初始化 ResearchState（query / user_id / 空白 evidence）
                             ▼
                    ┌─────────────────────────────────┐
            ┌──────│       Supervisor（调度者）        │◄──────┐
            │      │  · 拆解子任务（plan）           │       │
            │      │  · 决定下一步调度哪个 Worker     │       │
            │      │  · 监控 token / 终止条件        │       │
            │      └────────┬────────────────────────┘       │
            │               │ 派发 SubTask                      │
            │    ┌──────────┼──────────┐                       │
            │    ▼          ▼          ▼                       │
            │ 【研究员】  【分析员】  【写作员】                 │
            │ Researcher  Analyst    Writer                   │
            │  检索+抓取   去重/分类  生成报告/                  │
            │  调 Tavily   实体抽取   对比表/时间                │
            │  调 RAG      舆情分析   线/决策清单                │
            │    │          │          │                       │
            │    │   evidence & findings 汇总回 State          │
            │    └──────────┼──────────┘                       │
            │               │                                  │
            │               ▼                                  │
            │         ┌─────────────────┐                     │
            │         │  Critic（评审员）│                     │
            │         │  · 校验引用真实性│                     │
            │         │  · 忠实度评分    │                     │
            │         │  · 检测幻觉      │                     │
            │         └────────┬────────┘                     │
            │                  │ review.passed?                │
            │     ┌────────────┴────────────┐                 │
            │     │ 通过 → END（写报告落库）│                 │
            │     │ 不通过 → 让 Supervisor  │─────────────────┘
            │     │         重新派发         │  （回环重写）
            │     └─────────────────────────┘
            │
            └──── 每个 Supervisor 调用都会更新 plan / current_step
```

**协作规则**：
- 所有 Worker **不直接通信**，全部经 Supervisor 调度 + State 传递 evidence / findings
- Supervisor 是**唯一**允许调用 LLM 决策「下一步派谁」的节点
- Critic 不通过时，Supervisor 决定「重写」还是「换 Worker 补证据」

### 2.3 条件边

```python
def route_supervisor(state: ResearchState) -> str:
    if state["review"] and state["review"].passed:
        return END
    if state["token_usage"]["total"] > 50_000:
        return "force_end"
    if len(state.get("structured_findings", [])) == 0:
        return "researcher"
    if not state.get("draft_report"):
        return "analyst" if not done_analysis(state) else "writer"
    return "critic"

def route_critic(state: ResearchState) -> str:
    return "supervisor" if not state["review"].passed else END
```

## 3. 工具调用协议

### 3.1 Tool Schema（Anthropic / OpenAI 兼容）

```python
# tools/researcher.py
TOOL_TAVILY = {
    "name": "tavily_search",
    "description": "实时网络搜索，返回 top_k 条结果（标题 / url / 摘要）",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "top_k": {"type": "integer", "default": 10},
            "topic": {"type": "string", "enum": ["general", "news"]}
        },
        "required": ["query"]
    }
}

TOOL_RAG = {
    "name": "rag_retrieve",
    "description": "从用户私有资料库检索相关 chunks",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "top_k": {"type": "integer", "default": 20},
            "filters": {"type": "object"}
        },
        "required": ["query"]
    }
}
```

### 3.2 错误恢复

每个工具调用包 `tenacity` 重试：
- 网络错误：指数退避重试 3 次
- LLM API 429：等待 retry-after
- 工具执行失败：返回错误给 Supervisor 决定重试或换工具

## 4. 持久化

### 4.1 Postgres Checkpointer（LangGraph 1.x）

```python
# LangGraph 1.2+ 用 langgraph-checkpoint 4.x
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

checkpointer = AsyncPostgresSaver.from_conn_string(DB_URL)
graph = builder.compile(checkpointer=checkpointer)
```

每个 `agent_run` 对应一个 `thread_id`，state 自动快照。LangGraph 1.2.x 还支持 **DeltaChannel（beta）** —— 只存增量而非全量快照，大 state 图节省存储。

### 4.2 Human-in-the-Loop

LangGraph 1.x 的 `interrupt` 比老版本更细粒度（per-node / per-tool-call）：

```python
graph = builder.compile(
    checkpointer=checkpointer,
    interrupt_before=["critic"],   # 节点级暂停
    interrupt_after_tool_calls=True,  # 工具调用后暂停（1.2+ 新增）
)
```

UI 提供「继续 / 修改计划 / 终止 / 反馈」按钮，状态机恢复后继续执行。

### 4.3 Streaming v3（LangGraph 1.x 新增）

```python
# 按 channel 订阅，避免全 state 推流
async for chunk in graph.astream(
    {"messages": [HumanMessage(content=query)]},
    config={"configurable": {"thread_id": run_id}},
    stream_mode="values",  # 仅 values 通道
):
    await sse.send(chunk)
```

适合 SSE 推送给前端的场景。

## 5. 协作消息协议

```python
# 子 agent 间不直接通信，全部经 Supervisor state
class SubTask(TypedDict):
    id: str
    agent: Literal["researcher", "analyst", "writer", "critic"]
    instruction: str
    dependencies: List[str]  # 依赖其他 subtask 的 id
    status: Literal["pending", "running", "done", "failed"]
    output: Any
    error: Optional[str]
```

## 6. 可观测性

每个节点：
- 入口 span：记录输入 state 大小、token 预估
- 出口 span：记录输出大小、实际 token、耗时
- LLM call：记录 prompt / completion / model / cost
- Tool call：记录 tool / args / result / error

全部送 Phoenix project：`argus-{env}`。

## 7. 评测指标

针对多 agent 协作：
- **完成率**：成功产出报告的 run 占比（目标 ≥ 95%）
- **平均 token**：每个研究任务的 token 消耗（目标 ≤ 15k）
- **平均步骤数**：节点访问次数（目标 ≤ 8）
- **Critic 通过率**：首次评审通过率（目标 ≥ 70%）
- **人机干预率**：需要用户决策的占比（目标 ≤ 10%）