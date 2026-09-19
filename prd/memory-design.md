# Argus — 长期记忆设计

> Version: 0.1.0 · Date: 2026-09-18

## 1. 总览

Argus 的长期记忆解决两个问题：
1. **跨会话**：用户过去的研究偏好、订阅主题、查询历史。
2. **跨 agent run**：同一会话内 agent 反思 / 学到的信息。

通过 Mem0 集成 + 抽象 backend 接口实现，可替换为自研实现。

## 2. 记忆类型

### 2.1 User Memory（用户层）

| 类别 | 示例 | 存储 |
|---|---|---|
| 偏好 | "用户偏好中文报告"、"用户关心 AI 行业" | Mem0 + Postgres mirror |
| 主题订阅 | ["AI 行业动态", "英伟达财报"] | Postgres 主存 |
| 研究历史 | 上周查询过 "H100 vs Blackwell" | Postgres + Mem0 |
| 反馈 | "报告太长，3 段即可" | Mem0 |
| 实体关注 | {company: "NVIDIA", last_asked: ...} | Postgres |

### 2.2 Agent Memory（agent 层）

| 类别 | 示例 |
|---|---|
| 反思 | "上次用户不满意的报告是因为引用模糊" |
| 工具偏好 | "复杂查询用 web_scrape 而非 tavily" |
| 用户习惯 | "这位用户喜欢 markdown 表格 + 简短摘要" |

## 3. MemoryBackend 接口

抽象层让 Mem0 / Letta / 自研实现可互换：

```python
from abc import ABC, abstractmethod
from typing import List, Optional

class MemoryItem(BaseModel):
    id: str
    user_id: str
    content: str
    category: str  # preference / topic / history / reflection / entity
    importance: float  # 0.0 - 1.0
    created_at: datetime
    metadata: dict

class MemoryBackend(ABC):
    @abstractmethod
    async def add(self, item: MemoryItem) -> str: ...

    @abstractmethod
    async def search(self, user_id: str, query: str, top_k: int = 10,
                     categories: Optional[List[str]] = None) -> List[MemoryItem]: ...

    @abstractmethod
    async def update(self, item_id: str, content: str) -> MemoryItem: ...

    @abstractmethod
    async def delete(self, item_id: str) -> bool: ...

    @abstractmethod
    async def reflect(self, user_id: str, recent_items: List[MemoryItem]) -> List[MemoryItem]:
        """反思：合并 / 升级 / 删除过时记忆"""
        ...
```

## 4. Mem0 适配器

```python
from mem0 import AsyncMemory

class Mem0Backend(MemoryBackend):
    def __init__(self, config: Mem0Config):
        self.client = AsyncMemory(config=config)

    async def add(self, item: MemoryItem) -> str:
        result = await self.client.add(
            messages=[{"role": "user", "content": item.content}],
            user_id=item.user_id,
            metadata={
                "category": item.category,
                "importance": item.importance,
                **item.metadata,
            },
        )
        return result["id"]

    async def search(self, user_id, query, top_k=10, categories=None) -> List[MemoryItem]:
        filters = {"AND": [{"user_id": user_id}]}
        if categories:
            filters["AND"].append({"category": {"in": categories}})
        results = await self.client.search(
            query=query,
            user_id=user_id,
            limit=top_k,
            filters=filters,
        )
        return [self._to_item(r) for r in results["results"]]
```

## 5. 写入触发

### 5.1 显式触发

- 用户在 UI 点「记住这个偏好」按钮
- 用户填写 onboarding 表单

### 5.2 隐式触发（agent 推理后写入）

```python
# 在 Supervisor 决策时插入
async def maybe_write_memory(state: ResearchState):
    # 当 Supervisor 完成一轮调度后，检查是否需要写入
    if state.get("user_expressed_preference"):
        await memory.add(MemoryItem(
            user_id=state["user_id"],
            content=state["user_expressed_preference"],
            category="preference",
            importance=0.8,
        ))
```

### 5.3 反思触发（每会话结束）

会话结束或 cron 周期触发反思：

```python
async def reflect_session(user_id: str, session_id: str):
    recent = await db.get_recent_items(user_id, since=timedelta(days=7))
    new_items = await memory.reflect(user_id, recent)
    for item in new_items:
        await memory.add(item)
```

## 6. 读取路径

### 6.1 Researcher 召回

每次 Researcher 启动时，先调一次 memory recall：

```python
async def researcher_node(state: ResearchState):
    # 1. 先回忆
    memories = await memory.search(
        user_id=state["user_id"],
        query=state["query"],
        top_k=5,
        categories=["preference", "history", "entity"],
    )

    # 2. 把记忆注入 prompt
    memory_context = "\n".join([f"- [{m.category}] {m.content}" for m in memories])

    # 3. 再开始检索
    plan = await llm.plan_research(
        query=state["query"],
        memory_context=memory_context,
    )
    return {"plan": plan}
```

### 6.2 Writer 注入风格偏好

```python
async def writer_node(state: ResearchState):
    style = await memory.search(
        user_id=state["user_id"],
        query="报告风格",
        top_k=3,
        categories=["preference", "reflection"],
    )
    style_hint = "\n".join([m.content for m in style])
    report = await llm.write(
        findings=state["structured_findings"],
        style_hint=style_hint,
    )
    return {"draft_report": report}
```

## 7. 反思策略

### 7.1 何时反思

- 用户结束会话
- cron 每日凌晨 3 点
- 用户手动点「反思我的偏好」

### 7.2 反思 prompt

```python
REFLECT_PROMPT = """你是 Argus 的记忆整理助手。基于以下最近的用户交互，提取/合并/升级/删除记忆。

# 最近记忆
{recent_items}

# 最新交互
{new_interaction}

# 输出 JSON
{{
  "to_add": [
    {{"content": "...", "category": "...", "importance": 0.X}}
  ],
  "to_update": [
    {{"id": "...", "new_content": "..."}}
  ],
  "to_delete": ["..."]
}}

规则：
1. 同一偏好的多条记忆 → 合并成最新一条
2. 已不再相关（如 3 个月前订阅但近 1 月无查询的主题）→ 标记删除
3. 重要性评分：高频 0.9 / 中频 0.5 / 低频 0.2
4. 不要保存敏感信息（密码 / token / 个人隐私）
"""
```

## 8. 与 LangGraph 集成

```python
# agents/graph.py
from langgraph.graph import StateGraph

builder = StateGraph(ResearchState)

# 在 Researcher 节点前插入 memory recall
builder.add_node("memory_recall", memory_recall_node)
builder.add_node("researcher", researcher_node)
builder.add_edge("__start__", "memory_recall")
builder.add_edge("memory_recall", "researcher")

async def memory_recall_node(state: ResearchState):
    memories = await memory_backend.search(
        user_id=state["user_id"],
        query=state["query"],
    )
    return {"memories": memories}
```

## 9. Postgres mirror 表

部分高频访问的记忆（如主题订阅、实体关注）缓存到 Postgres 以避免每次远程调用 Mem0：

```sql
CREATE TABLE user_memories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    category VARCHAR(50) NOT NULL,
    content TEXT NOT NULL,
    importance FLOAT NOT NULL DEFAULT 0.5,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    INDEX idx_memories_user_category (user_id, category)
);
```

同步策略：Mem0 是 source of truth，Postgres 是 cache（每 5 分钟 sync）。

## 10. 隐私与用户控制

- 用户可在 UI 「记忆设置」中查看 / 删除 / 导出全部记忆
- 「清空所有记忆」按钮（二次确认）
- 反思 prompt 显式禁止保存敏感信息
- 记录每次 add / delete 操作到 audit log

## 11. 评估

| 指标 | 定义 | 目标 |
|---|---|---|
| Recall 命中率 | 二次会话 agent 自动调用的偏好占比 | ≥ 60% |
| 反思合并准确率 | 人工评估合并是否合理 | ≥ 80% |
| 记忆延迟 | search P95 | ≤ 200ms |
| 用户删除响应 | 删完到 search 不可见 | ≤ 5s |