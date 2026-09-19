# Argus — Sprint Plan（4 周）

> Version: 0.1.0 · Date: 2026-09-18

## 总览

| 周 | 主题 | 关键交付 |
|---|---|---|
| W1 | Repo + 单 agent + UI 骨架 | 可跑通「提问 → 单 agent 答」 |
| W2 | RAG + 多 agent + 记忆 | 可跑通「上传 PDF → 多 agent 协作出报告」 |
| W3 | 主动追踪 + 多视图 + Auth + 评测 | 完整产品形态 + 评测指标上线 |
| W4 | 部署 + CI + 开源包装 + 文档 | 公开 repo + 一键跑起来 |

每周日做 demo + 复盘 + 验收。

---

## W1：Repo 骨架 + 单 agent + UI

### 目标
- 可跑通的 monorepo + FastAPI + 单 agent + Next.js UI
- 完整 README + .env.example

### 每日任务

| 日 | 任务 |
|---|---|
| Day 1 (Mon) | monorepo init (pnpm + uv + Turborepo) / Docker Compose / Postgres + Redis 起本地服务 |
| Day 2 (Tue) | FastAPI 骨架 + SQLAlchemy + Alembic / OAuth 集成 (GitHub + Google) |
| Day 3 (Wed) | 单 agent (Anthropic SDK) + tool calling 闭环 + 2-3 个工具 (tavily / web_fetch / dedup) — **模型用 Sonnet 5** |
| Day 4 (Thu) | LangGraph 接入 + 简单 supervisor → researcher 单节点图 / Postgres checkpointer |
| Day 5 (Fri) | Next.js 14 骨架 + Tailwind + shadcn/ui / OAuth 登录流 / 「提问」页 + SSE 流式 |
| Day 6 (Sat) | 基础 agent 时间轴 UI / 连接 SSE / 显示工具调用过程 |
| Day 7 (Sun) | **W1 Demo**：输入主题 → 单 agent 联网搜 → 出报告 / 复盘 / 验收 |

### 验收
- [ ] `pnpm dev` 起前端，`docker compose up` 起后端
- [ ] OAuth 登录 GitHub 能拿到 token
- [ ] 输入「对比 H100 与 Blackwell」能在 30 秒内返回带引用的简短回答
- [ ] 前端能看到 agent 工具调用的实时过程
- [ ] README 中英双语，5 分钟跑通

---

## W2：RAG + 多 agent + 长期记忆

### 目标
- 上传 PDF → 自动入库 → 多 agent 协作 → 带引用报告
- 长期记忆接入

### 每日任务

| 日 | 任务 |
|---|---|
| Day 8 (Mon) | S3 / MinIO presigned URL 上传链路 / 前端上传组件 |
| Day 9 (Tue) | PyMuPDF / Tesseract parser / RecursiveTextSplitter chunker / OpenAI embedder / 写入 pgvector |
| Day 10 (Wed) | 检索服务（向量 + BM25 混合） / Cohere rerank / citation builder |
| Day 11 (Thu) | LangGraph 完整 5 agent 编排（Supervisor + Researcher + Analyst + Writer + Critic）— **路由 Sonnet 5 / Haiku 4.5** / Postgres checkpointer 持久化 |
| Day 12 (Fri) | Mem0 集成 / MemoryBackend 抽象 / Researcher 启动时 memory recall / Writer 注入风格 |
| Day 13 (Sat) | Critic faithfulness 校验 / 报告引用追溯 UI（点击 [n] 看原文） |
| Day 14 (Sun) | **W2 Demo**：上传 NVIDIA Q2 财报 PDF → 问「H100 与 Blackwell 差异」→ 出带引用对比表 / 复盘 / 验收 |

### 验收
- [ ] PDF 上传 30 秒内可检索
- [ ] 多 agent 协作流程在前端可视化展示
- [ ] 报告里每个 [n] 引用都可点击追溯到原文
- [ ] 第二次会话 agent 自动调用过去的偏好记忆
- [ ] Critic 通过率 ≥ 60%（首次评审）

---

## W3：主动追踪 + 多视图 + Auth + 评测

### 目标
- 完整产品形态：订阅主题 → cron 拉新 → 通知 → 多视图查看报告
- 评测指标上线

### 每日任务

| 日 | 任务 |
|---|---|
| Day 15 (Mon) | 主题订阅 UI + 数据模型 / RSS 源管理 |
| Day 16 (Tue) | APScheduler cron worker / RSS poller / dedup worker / summarizer |
| Day 17 (Wed) | 通知中心 UI / SSE 实时推送 / 「新内容」徽章 |
| Day 18 (Thu) | 多视图渲染器（报告 / 对比表 / 时间线 / 决策清单）/ 视图切换器 |
| Day 19 (Fri) | 完整 Auth（多用户 + RLS 隔离 + 会话管理）/ 登录后看到自己的资料库 |
| Day 20 (Sat) | Phoenix 接入 / LLM-as-judge faithfulness / 200 条 retrieval 数据集 |
| Day 21 (Sun) | **W3 Demo**：订阅「AI 行业动态」→ 等 cron 拉新 → 看通知 → 出报告 / 复盘 / 验收 |

### 验收
- [ ] 主题订阅 + cron 6 小时内拉到新内容
- [ ] 通知中心实时显示新内容
- [ ] 同一研究主题可在 4 种视图间切换
- [ ] 用户 A 看不到用户 B 的资料（RLS 测试通过）
- [ ] Retrieval P@5 ≥ 0.70（当前数据集）
- [ ] Faithfulness 自动评分 ≥ 0.80

---

## W4：部署 + CI + 开源包装 + 文档

### 目标
- 完整开源项目：CI 全绿 / 一键部署 / 文档齐全 / 可被外部 PR

### 每日任务

| 日 | 任务 |
|---|---|
| Day 22 (Mon) | GitHub Actions：lint + test + e2e Playwright / 覆盖率 ≥ 70% |
| Day 23 (Tue) | Docker Compose 一键启动脚本 / seed_demo_data.py（200 篇预置）/ 验证 5 分钟跑通 |
| Day 24 (Wed) | 部署文档（本地 / VPS / Vercel）/ 监控（Prometheus + Grafana）/ 备份脚本 |
| Day 25 (Thu) | 开源包装：LICENSE / CONTRIBUTING / Issue Templates / CHANGELOG / PR 模板 |
| Day 26 (Fri) | README 中英双语最终版 / 架构图 / Demo 视频 / Badges |
| Day 27 (Sat) | 全量回归测试 / 性能基线（token / 延迟）/ 修复发现的问题 / **检查 Anthropic Haiku 4.5 退役状态（如未退役，MVP 完成后再升级）** |
| Day 28 (Sun) | **W4 Demo & 发布**：发布 v0.1.0 GitHub Release / 公开 repo / 简历写入项目链接 / 复盘 |

### 验收
- [ ] `docker compose up` → 5 分钟内所有服务 healthy
- [ ] CI 全绿（lint + test + e2e + eval）
- [ ] README 中英双语、含 demo gif / 视频
- [ ] LICENSE / CONTRIBUTING / Issue Templates 完整
- [ ] 在真机上跑通「上传 → 提问 → 出报告 → 订阅 → 通知」全链路
- [ ] v0.1.0 GitHub Release 发布

---

## 关键里程碑

| 日期 | 里程碑 |
|---|---|
| Day 7  | 单 agent demo（W1 验收） |
| Day 14 | 多 agent + RAG demo（W2 验收） |
| Day 21 | 完整产品形态 demo（W3 验收） |
| Day 28 | 公开发布 + 简历可用（W4 验收） |

## 风险与回退

| 风险 | 触发条件 | 回退方案 |
|---|---|---|
| LLM API 成本失控 | 周成本 > $500 | 全部切 Haiku + cache |
| 多 agent 协作不稳定 | Critic 通过率 < 40% | 简化到 Supervisor + Writer 双 agent |
| Phoenix 集成耗时 | Day 20 仍未通 | 暂时只用 structlog + Postgres 自存 trace |
| Mem0 API 不稳定 | 调用失败 > 10% | 降级到 Postgres 自研简单记忆 |
| 部署复杂度 | Day 24 仍未 5 分钟跑通 | 只交付 Docker Compose，不接 Vercel |

## 每日复盘模板

```markdown
## YYYY-MM-DD

### 完成
- [ ] Task 1
- [ ] Task 2

### 阻塞
- 描述 + 影响 + 需要谁 / 什么时候解决

### 明日
- [ ] Task 1
- [ ] Task 2

### Token / 成本
- 总用量 / 峰值任务 / 异常任务
```

## 时间投入

- 全职 ~ 8h/天 × 28 天 = ~224h
- 兼职（每天 4h）也能完成但 demo 质量降低