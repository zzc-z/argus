# Argus — 评测体系设计

> Version: 0.1.0 · Date: 2026-09-18

## 1. 总览

Argus 用**三层评测**确保能力可量化、可回归：
1. **单元 / 集成测试**（pytest）— 模块功能
2. **Phoenix trace + evaluate** — agent 运行时行为
3. **端到端 e2e + 自研指标** — 用户感知质量

## 2. 三层评测矩阵

| 层 | 工具 | 覆盖 | 频率 |
|---|---|---|---|
| L1: 单元 | pytest | 工具 / chunker / embedder / retriever | 每次 PR |
| L2: 集成 | pytest + LangGraph test | agent 节点 + 状态机 | 每次 PR |
| L3: 端到端 | Playwright + Phoenix | 全链路 + 报告质量 | 每次 PR + 每周回归 |
| L4: 数据集回归 | Phoenix Datasets | retrieval / faithfulness | 每周 + 模型/embedding 切换时 |

## 3. 评测数据集

### 3.1 Retrieval Eval Dataset

`eval/datasets/retrieval_v1.jsonl`：

```json
{
  "id": "q001",
  "query": "英伟达 H100 与 Blackwell 性能对比",
  "ground_truth_doc_ids": ["doc-h100-spec-001", "doc-blackwell-spec-002"],
  "relevant_chunk_ids": ["doc-h100-spec-001#0", "doc-h100-spec-001#5", "doc-blackwell-spec-002#3"],
  "category": "tech_comparison",
  "difficulty": "medium"
}
```

200 条 query，覆盖：
- 50 条 tech comparison
- 50 条 company news
- 30 条 trend analysis
- 30 条 policy / regulation
- 20 条 product launch
- 20 条 investor relation

### 3.2 Faithfulness Eval Dataset

`eval/datasets/faithfulness_v1.jsonl`：

```json
{
  "id": "f001",
  "report": "NVIDIA Q2 数据中心收入达 $39.2B，同比 +154% [1]。",
  "sources": [
    {"id": "src-001", "content": "Q2 FY26 data center revenue was $39.2 billion, up 154% year-over-year."}
  ],
  "expected_faithful": true,
  "category": "earnings_quote"
}
```

100 条样本，由人工标注「忠实 / 幻觉 / 部分幻觉」。

### 3.3 Agent Task Eval Dataset

`eval/datasets/agent_tasks_v1.jsonl`：

```json
{
  "id": "a001",
  "user_query": "对比英伟达 H100 与 AMD MI300 在 LLM 推理场景下的性能与价格",
  "expected_tools": ["tavily_search", "web_scrape", "rag_retrieve"],
  "expected_views": ["report", "comparison_table"],
  "ground_truth_report_id": "gt-a001",
  "rubric": {
    "completeness": 4,
    "accuracy": 5,
    "citations": 4,
    "format": 3
  }
}
```

30 条高难度任务，每条配专家写的 ground truth 报告。

## 4. 自研指标

### 4.1 Retrieval 指标

```python
def precision_at_k(retrieved: List[str], relevant: List[str], k: int) -> float:
    return len(set(retrieved[:k]) & set(relevant)) / k

def recall_at_k(retrieved: List[str], relevant: List[str], k: int) -> float:
    return len(set(retrieved[:k]) & set(relevant)) / len(relevant)

def mrr(retrieved: List[str], relevant: List[str]) -> float:
    for i, r in enumerate(retrieved):
        if r in relevant:
            return 1.0 / (i + 1)
    return 0.0

def ndcg_at_k(retrieved: List[str], relevance: dict, k: int) -> float:
    # relevance: {item_id: score}
    dcg = sum(rel / math.log2(i + 2) for i, item in enumerate(retrieved[:k])
              for rel in [relevance.get(item, 0)])
    ideal = sum(sorted(relevance.values(), reverse=True)[:k])
    return dcg / ideal if ideal > 0 else 0.0
```

### 4.2 Faithfulness 指标

```python
async def faithfulness_score(report: str, sources: List[Source]) -> float:
    """0.0 - 1.0，分数越高越忠实"""
    claims = extract_claims(report)  # 拆分为 atomic claims
    scores = []
    for claim in claims:
        score = await llm_judge_faithful(claim, sources)
        scores.append(score)
    return sum(scores) / len(scores)
```

### 4.3 Agent 协作指标

```python
@dataclass
class AgentRunMetrics:
    run_id: str
    total_tokens: int
    duration_seconds: float
    node_visits: dict[str, int]  # supervisor / researcher / ...
    critic_passes: int
    critic_iterations: int
    human_interruptions: int
    tool_calls: dict[str, int]
    error_count: int
    final_passed: bool
```

派生指标：
- 完成率 = `sum(final_passed) / total_runs`
- 平均 token = `mean(total_tokens)`
- 平均步骤数 = `mean(sum(node_visits.values()))`
- Critic 通过率 = `mean(critic_passes == 1)`

## 5. Phoenix 集成

### 5.1 Trace

每个 agent_run 创建一个 Phoenix span tree：

```
agent_run (root)
├── supervisor (node)
│   ├── llm_call (sonnet-5)
│   └── tool_call: plan_research
├── researcher (node)
│   ├── llm_call (sonnet-5)
│   ├── tool_call: tavily_search
│   ├── tool_call: web_scrape
│   └── tool_call: rag_retrieve
├── analyst (node)
│   └── tool_call: dedup
├── writer (node)
│   └── llm_call (sonnet-5)
└── critic (node)
    └── llm_call (haiku-4.5)
```

每个 span 记录：inputs / outputs / latency / tokens / cost / model。

### 5.2 Evaluate

```python
from phoenix.experimental.evals import (
    FaithfulnessEvaluator,
    RelevanceEvaluator,
    QAEvaluator,
)

faithfulness_eval = FaithfulnessEvaluator(model="claude-haiku-4-5")
relevance_eval = RelevanceEvaluator(model="claude-haiku-4-5")
```

在每次 agent_run 完成后异步跑：

```python
async def evaluate_run(run: AgentRun):
    traces = phoenix.get_traces(run.trace_id)

    # 报告忠实度
    faithfulness = await faithfulness_eval.evaluate(
        question=run.query,
        context=[s.content for s in run.sources],
        answer=run.report,
    )

    # 答案相关性
    relevance = await relevance_eval.evaluate(
        question=run.query,
        answer=run.report,
    )

    # 写到 Phoenix + Postgres
    await db.insert_eval(run.id, {
        "faithfulness": faithfulness.score,
        "relevance": relevance.score,
    })
```

### 5.3 Datasets

Phoenix datasets 提供：
- 每次评估的 run / trace / eval 结果
- 时间序列趋势
- 模型对比（A/B test）
- 退化报警

## 6. CI 集成

### 6.1 GitHub Actions

```yaml
# .github/workflows/eval.yml
name: eval
on: [pull_request]
jobs:
  retrieval-eval:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run retrieval eval
        run: |
          docker compose up -d postgres
          uv run python -m eval.retrieval --dataset eval/datasets/retrieval_v1.jsonl
      - name: Compare with baseline
        run: |
          uv run python -m eval.diff --current results/current.json --baseline results/baseline.json
```

### 6.2 退化门禁

```python
def check_regression(current: dict, baseline: dict, threshold: float = 0.05):
    for metric in ["precision@5", "recall@10", "faithfulness"]:
        delta = baseline[metric] - current[metric]
        if delta > threshold:
            raise EvalRegressionError(f"{metric} regressed by {delta:.2%}")
```

PR 中指标退化 > 5% 失败。

## 7. 报告与可视化

### 7.1 Phoenix UI

- `http://localhost:6006` 看 trace
- 按时间 / 模型 / 用户筛选
- drill-down 到具体 run

### 7.2 Grafana Dashboard

- token 用量（按模型 / agent / 天）
- 检索延迟 P50 / P95 / P99
- Faithfulness 趋势
- 失败率

### 7.3 README 徽章

```
[![Retrieval P@5](https://img.shields.io/badge/P@5-0.78-green)]()
[![Faithfulness](https://img.shields.io/badge/Faithfulness-0.87-green)]()
```

## 8. 人工评估

每 2 周抽样 30 条最新 run 做人工评估：
- 报告质量（completeness / accuracy / format）1-5 分
- 引用真实性（点击追溯）
- 用户满意度（如果接入了 feedback）

抽样结果存 `eval/human_eval/2026-W{n}.json`。

## 9. 评测任务清单

- [ ] 编写 200 条 retrieval 数据集
- [ ] 编写 100 条 faithfulness 数据集
- [ ] 编写 30 条 agent task 数据集
- [ ] 接入 Phoenix Client + SpanExporter
- [ ] 编写 LLM-as-judge prompt
- [ ] GitHub Actions 配置
- [ ] Grafana dashboard 模板
- [ ] 人工评估 protocol 文档

## 10. 不在 MVP 范围

- RLHF / 用户反馈学习循环（stretch）
- 自动 A/B 流量分配（stretch）
- 第三方 benchmark 接入（如 HotpotQA）（stretch）