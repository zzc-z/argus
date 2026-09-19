# Argus · Risk & Compliance Register

> **目的**：集中登记所有第三方依赖的**退役警告 / 安全 CVE / 许可证 / 已知边界**。
> **维护人**：W0 文档阶段完成；后续在每次依赖升级时同步更新。
> **最后更新**：2026-09-18

---

## 1. ⚠ 紧急退役警告（影响 MVP）

| 依赖 | 退役日期 | 距今 | Argus 应对 |
|---|---|---|---|
| **Claude Sonnet 4.5** | 2026-09-29 | **11 天** | 全 agent 已升级到 Sonnet 5（已完成） |
| **Claude Haiku 4.5** | 2026-10-15 | **28 天** | 暂用，MVP 完成后须升 Haiku 5（2026-10 中旬前必须完成） |

**行动要求**：
- W1 Day 3（单 agent 接入）必须用 `claude-sonnet-5`，**禁止使用 Sonnet 4.5**
- W4 Day 27 复盘检查 Haiku 4.5 是否仍在 MVP 服务中——是，则立即升级

---

## 2. 安全 CVE 提醒

| CVE | 影响库 | 受影响版本 | 修复版本 | Argus 应对 |
|---|---|---|---|---|
| **CVE-2026-28498** | authlib | < 1.6.9 | ≥ 1.6.9 | pyproject 已要求 `authlib>=1.8`，**部署前必须确认 pip 拉到 ≥1.6.9** |
| （持续跟踪中） | | | | |

**说明**：CVE-2026-28498 是 authlib OIDC ID Token 验证的 **fail-open** 漏洞——遇到不支持的算法签名直接返回 True，可被伪造 ID Token 绕过完整性检查。Argus 用 authlib 做 OAuth（GitHub + Google），**虽不直接用 OIDC ID Token**，但作为依赖存在仍建议升级。

---

## 3. 版本锁定基线（联网核实于 2026-09-18）

| 包 | 当前 PyPI | Argus pyproject | 备注 |
|---|---|---|---|
| langgraph | 1.2.11（2026-08-11） | `>=1.2` | 1.x GA，老代码用 `langgraph-classic` |
| langchain | 1.3.x | `>=1.3` | 1.0 GA 于 2025-10-22 |
| langchain-core | 1.6.x | `>=1.6` | |
| langchain-mcp-adapters | 0.3.1（2026-07-27） | （可选）`>=0.3.1` | MCP 协议原生集成 |
| anthropic（Claude SDK） | 0.84+（2026-03 后改名） | `>=0.84` | 0.84+ 提供原生 MCP helpers |
| openai | 3.14.1（2026-09-15） | `>=3.14` | 1.x → 3.x 主版本跨度大 |
| cohere | 7.1.1（2026-08-31） | `>=7.1` | |
| tavily-python | 0.8.1（2026-09-11） | `>=0.8` | |
| firecrawl-py | 4.34.0（2026-08-04） | `>=4.34` | |
| assemblyai | 0.65+（2026-08） | `>=0.65` | 0.65+ 引入 asyncio AsyncTranscriber |
| mem0ai | 2.0.7（2026-06-17） | `>=2.0` | 默认 OpenAI gpt-5-mini + 1536 维 embedding |
| arize-phoenix | 13.18.0+ | `>=13.0` | 含 prompt diff + structured evals |
| arize-phoenix-evals | 2.12.0+ | `>=2.12` | |
| authlib | 1.8.0（2026-05-06） | `>=1.8` | ≥1.6.9 修复 CVE-2026-28498 |
| fastapi | 0.141.1（2026-07 后） | `>=0.141` | OpenAPI 3.1 + Pydantic v2 native |
| pydantic | 2.x（持续更新） | `>=2.10` | Rust-backed validation |
| sqlalchemy | 2.0.36（2026-04 后） | `>=2.0.36` | 2.0 API + native async sessions |
| asyncpg | 0.30.0 | `>=0.30` | |

---

## 4. 许可证矩阵

| 包 | 许可证 | 商业可用 | 备注 |
|---|---|---|---|
| langgraph | MIT | ✅ | |
| langchain | MIT | ✅ | |
| anthropic | MIT | ✅ | |
| openai | Apache-2.0 | ✅ | |
| cohere | MIT | ✅ | |
| tavily-python | MIT | ✅ | |
| firecrawl-py | MIT | ✅ | |
| assemblyai | MIT | ✅ | |
| mem0ai | Apache-2.0 | ✅ | |
| arize-phoenix | Apache-2.0 | ✅ | Self-hosted 版本，**Enterprise 版另收费** |
| authlib | BSD-3-Clause | ✅ | |
| pgvector | PostgreSQL | ✅ | |
| FastAPI | MIT | ✅ | |
| Next.js | MIT | ✅ | |

**Argus 自身**：**未发布 / 私有项目**（2026-09-19 用户决策：仓库 Private，暂不发布 LICENSE / 不开源）

---

## 5. 已知能力边界

| 边界 | 说明 | 缓解 |
|---|---|---|
| 中文 embedding 略弱于英文 | OpenAI text-embedding-3-small 在中英混合场景下表现有差异 | 备选 BGE-M3（本地） |
| 跨语言检索 | zh ↔ en 混合查询 | 需 cross-lingual embedding（备选 BGE-M3） |
| 大文档（>1000 页 PDF）| 单 chunk 模型处理能力有限 | 分层摘要 + 多轮 RAG |
| 多模态 chunk 检索 | 图片 / 视频转写后的检索精度 | 走 OCR 文本 + image_caption，向量同源 |
| Tavily 搜索深度限制 | 免费版每月 1000 次 | 监控配额，超限降级到本地缓存 |
| Mem0 云 API 依赖 | Mem0 不可用时长期记忆失效 | 抽象 MemoryBackend，可降级到 Postgres 自研 |
| pgvector 性能 | 100k+ documents 后延迟上升 | 备选 Qdrant / Milvus |

---

## 6. Anthropic 模型迁移路径

```
2026-09-18  Argus MVP 当前使用
├── Sonnet 5    （GA 于 2026-06）
└── Haiku 4.5   （2026-10-15 退役）

2026-10-15 后  必须迁移
└── Haiku 5     （待 Haiku 5 GA 公告）

2026-09-29   紧急迁移完成（Sonnet 4.5 → Sonnet 5）✅
```

**Haiku 5 何时切**：
- Anthropic 公告 Haiku 5 GA 后，立即同步 tech-stack.md / pyproject / 多 agent 路由代码
- 不强求 Sonnet 5 + Haiku 5 同步切换（可分两次 PR）

---

## 7. 监控与告警

W4 部署时需配置的告警：

- **token 用量超预算**：1h 内 tokens > 1M → Slack
- **Anthropic API 错误率 > 5%**：可能 Sonnet 5 临时故障 → 自动降级 Sonnet 4.5（**注意 09-29 后不可用**）
- **Phoenix trace 失败**：trace 上报错误 → 检查 OTLP endpoint
- **Mem0 API 错误率 > 10%**：触发 MemoryBackend 降级

---

## 8. 更新机制

每次升级依赖时：
1. 更新本文件 §3 版本基线
2. 更新 `tech-stack.md` pyproject
3. 更新 `CHANGELOG.md`
4. 跑 CI：`uv lock && uv sync` → 确认依赖锁文件无冲突
5. 跑回归测试：`pytest + playwright`

**CI 门禁**：任何 pyproject 变更必须同时更新本文件 + CHANGELOG，否则 CI 失败。