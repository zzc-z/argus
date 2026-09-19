# Argus — PRD

> 多视角新闻 / 舆情 / 趋势追踪研究助手
> Version: 0.1.0 · Date: 2026-09-18 · Status: Draft

## 1. 一句话定位

Argus 是一个**个人 / 小团队用**的多 agent 研究助手：用户上传文档、订阅主题或粘贴 URL，Supervisor agent 自动调度 Researcher / Analyst / Writer / Critic 四类子 agent，从多源（用户资料库 + 实时网页 + 长期记忆）聚合、去重、分析、写作，最终以「报告 / 对比表 / 决策清单」多视图交付带引用的研究产出。

希腊神话里 Argus Panoptes 百眼巨人——多视角、不遗漏。

## 2. 问题与机会

### 2.1 问题
- 单一 ChatGPT / Perplexity 类工具**没有持久记忆**，跨会话上下文丢失。
- 单 agent 难以同时处理「查资料 + 写报告 + 自检引用 + 反思修正」，输出质量上限低。
- 私人 / 团队**私域资料库**（内部 RSS、订阅 newsletter、行业报告）难以与公开网络检索整合。
- 没有针对「舆情趋势」这种**时间维度 + 多源去重**任务优化的工具。

### 2.2 机会
- LLM API 成本下降，**多 agent 编排**成为可行工程化方向。
- LangGraph / Phoenix / Mem0 / pgvector 等开源栈成熟，**自研可控的 RAG + agent runtime** 成为可能。
- 个人简历 / 求职作品集**对 agent 能力的需求激增**（2025-2026 趋势）。

## 3. 目标与非目标

### 3.1 目标（Goals）
1. **完整闭环**：从「用户输入」到「带引用报告」全链路跑通，可视化展示 agent 协作过程。
2. **四能力并重**：工具调用 / RAG / 多 agent / 长期记忆 均在 MVP 中可演示。
3. **评测驱动开发**：核心能力（检索质量、报告忠实度、agent 协作效率）有量化指标。
4. **可部署**：Vercel + Docker Compose 双路径，个人 / 小团队能 5 分钟跑起来。

### 3.2 非目标（Non-Goals）
- 不做企业级 SSO / RBAC / 计费 / 多租户。
- 不做实时流式推送（仅 cron 周期拉取 + UI 内通知）。
- 不做视频 / 音频转写的端到端质量（仅做基础转写 + 摘要）。
- 不做模型微调（默认调用 Anthropic / OpenAI API）。
- 不做移动端 App（仅 Web UI，响应式适配）。

## 4. 用户与场景

### 4.1 用户
- **个人研究者 / 投资分析师 / 产品经理 / 行业顾问**：跨源追踪主题、整理周报、做趋势判断。
- **技术决策者**：评估技术栈、对比竞品、整合内部资料。
- **小团队（3-10 人）协作**：共享主题订阅、研究笔记、报告归档。

### 4.2 用户故事（核心 5 条）
1. 作为**用户**，我希望订阅「AI 行业动态」主题，系统每 6 小时自动拉取新文章并生成摘要，让我不打开网站也能掌握动态。
2. 作为**用户**，我希望上传一份 PDF 报告并提问「这份报告与 X 公司最新战略有何差异」，系统能从我上传的资料库 + 网络检索中给出带引用的对比表。
3. 作为**用户**，我希望看到一个研究主题的「时间线视图」，按周 / 月聚合相关事件，帮助我判断趋势走向。
4. 作为**用户**，我希望 agent 记住我过去研究过的方向（长期记忆），下次自动优先检索我关心的子主题，减少重复劳动。
5. 作为**用户**，我希望对 agent 报告的某段引用「点击追溯原文」，验证它真的从资料里来（faithfulness / 可追溯）。

## 5. 核心能力范围

| 能力                 | 描述                                                                                         | MVP 必须 | Stretch |
| -------------------- | -------------------------------------------------------------------------------------------- | -------- | ------- |
| 工具调用             | 自定义工具（search / fetch / scrape / parse / dedup / sentiment / image_caption / 记忆读写） | ✅        | —       |
| RAG 检索             | chunking + embedding + rerank + 多源融合 + 可追溯引用                                        | ✅        | —       |
| 多 agent 编排        | LangGraph Supervisor + Researcher/Analyst/Writer/Critic 状态机                               | ✅        | —       |
| 长期记忆             | Mem0 / Letta 集成：用户偏好 + 主题历史 + 反思记忆                                            | ✅        | —       |
| 主动追踪             | 订阅主题 + cron 后台拉取 + UI 内通知                                                         | ✅        | —       |
| 多视图输出           | 报告 / 对比表 / 时间线 / 决策清单                                                            | ✅        | —       |
| 多用户 / 登录        | OAuth (GitHub + Google) + 订阅隔离                                                           | ✅        | —       |
| 评测体系             | Phoenix trace + 自研指标 + 数据集                                                            | ✅        | —       |
| 部署                 | Vercel (前端) + Docker Compose (后端)                                                        | ✅        | —       |
| CI                   | ruff + pytest + Playwright e2e                                                               | ✅        | —       |
| 多模态输入           | 文本 + 图片                                                                                  | ✅        | —       |
| 视频 / 音频转写      | 通过外部 API（whisper / assemblyai）基础转写 + 摘要                                          | —        | ✅       |
| 邮件 digest          | 周期汇总邮件                                                                                 | —        | ✅       |
| Webhook / Slack 推送 | 团队集成                                                                                     | —        | ✅       |

## 6. 验收指标（Definition of Done）

### 6.1 功能验收
- [ ] 用户上传 PDF / URL / 图片 → 30 秒内进入可检索状态。
- [ ] 用户提问 → Supervisor 自动调度 ≥2 个子 agent → 产出带引用报告。
- [ ] 用户订阅主题 → cron 6 小时内拉到新内容 → UI 通知中心可见。
- [ ] 长期记忆：第二次会话 agent 自动调用过去偏好。
- [ ] 多视图：同一研究主题可切换报告 / 对比表 / 时间线 / 决策清单 4 种视图。

### 6.2 质量验收
- [ ] RAG 检索 precision@5 ≥ 0.75（200 篇 AI / 科技 demo 数据集）。
- [ ] 报告 faithfulness ≥ 0.85（Phoenix 自评 + 人工抽样 30 条）。
- [ ] Agent 完成研究任务的平均 token 消耗 ≤ 15k（路由 Sonnet + Haiku）。
- [ ] E2E Playwright 覆盖：上传 / 提问 / 订阅 / 查看报告 4 条主流程。

### 6.3 工程验收
- [ ] `docker compose up` → 5 分钟内所有服务就绪。
- [ ] CI：lint + test + e2e 全绿，PR 模板齐全。
- [ ] README 中英双语，部署文档可按步骤跑通。
- [ ] 完整开源包装：LICENSE / CONTRIBUTING / Issue Templates / CHANGELOG。

## 7. 演示数据集

预置 200 篇 AI / 科技领域公开文章（arXiv / 各大科技博客 RSS / 公开报告），覆盖：
- 100 篇 LLM / Agent 相关
- 50 篇 机器人 / 自动驾驶
- 30 篇 芯片 / 硬件
- 20 篇 政策 / 监管

数据采集脚本：`scripts/seed_demo_data.py`（在 W1 末完成）。

## 8. 风险与缓解

| 风险                  | 等级 | 缓解                                                                 |
| --------------------- | ---- | -------------------------------------------------------------------- |
| LLM API 成本失控      | 高   | Haiku 处理简单任务、Sonnet 处理复杂任务、token 监控 + 限额           |
| 多 agent 调试难       | 高   | Phoenix 全链路 trace + LangGraph Studio 可视化 + 每个 agent 独立测试 |
| RAG 检索质量不达标    | 中   | rerank 模型 + 多路召回 + 评估集回归                                  |
| 多 agent 协作不稳定   | 中   | 状态机 + 兜底规则 + Critic agent 自检                                |
| Mem0 / Letta API 变动 | 中   | 抽象 `MemoryBackend` 接口，可替换自研实现                            |
| pgvector 性能瓶颈     | 低   | HNSW 索引 + 定时 ANALYZE + 大数据集考虑 Qdrant                       |
| 部署复杂度            | 中   | Docker Compose 一键起 + Vercel 自动部署前端 + README 5 分钟验证      |

## 9. 时间线（4 周）

| 周  | 目标                                                           |
| --- | -------------------------------------------------------------- |
| W1  | Repo 骨架 + FastAPI 后端 + 单 agent + 工具调用闭环 + UI 基础页 |
| W2  | RAG pipeline + 多 agent 编排 + 长期记忆集成 + demo 数据集      |
| W3  | 主动追踪 cron + 多视图输出 + 多用户 Auth + 评测指标            |
| W4  | 部署 + CI + 开源包装 + 文档 + 演示视频                         |

详见 `sprint-plan.md`。

## 10. 关键决策记录

- **场景**：新闻 / 舆情 / 趋势追踪（不做论文方向）
- **数据源**：用户上传 + 网页抓取（含视频转写 / OCR）
- **抓取深度**：重量级（多模态）
- **多模态输入**：文本 + 图片
- **演示数据**：200 篇 AI / 科技
- **语言**：中英双语 README + UI 中文默认
- **主动追踪**：订阅主题 + cron 后台拉
- **推送渠道**：UI 内通知
- **多用户**：OAuth（GitHub + Google）+ 订阅隔离
- **agent 编排**：LangGraph 1.2.x（1.x 已 GA，原生 Postgres checkpointer + streaming v3 + interrupt 增强）
- **长期记忆**：Mem0 / Letta 集成
- **RAG 框架**：LangChain 1.3.x（仅用 loader / splitter；老 API 在 `langchain-classic`）
- **LLM 路由（2026-09 升级）**：Claude **Sonnet 5**（复杂任务）/ **Haiku 4.5**（轻量任务）；Sonnet 4.5 已弃用（09-29 退役），Haiku 4.5 待升级（10-15 退役）
- **评测**：Arize Phoenix 13.x + `arize-phoenix-evals` 2.12+
- **向量存储**：pgvector 一体
- **部署**：Vercel + Docker Compose
- **评测**：Phoenix + 自研指标
- **CI**：lint + test + Playwright e2e
- **开源**：完整开源