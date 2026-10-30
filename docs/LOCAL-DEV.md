# 本地开发环境（argus）

**2026-10-23 立。** 新会话接手时先读这份 —— 下面几件事做错不会报错，只会「看起来正常但数据是旧的」。

## 1. 跑起来

```bash
# 后端（apps/api）
cd apps/api
uv run uvicorn app.main:app --port 8000

# 前端（仓库根）
pnpm --filter web dev
```

前端默认打 `http://localhost:8000`（`apps/web/lib/api/client.ts` 的 `API_BASE`），
可用 `NEXT_PUBLIC_API_BASE` 覆盖。

## 2. 改了后端代码 → 必须重启

**后端没开 `--reload`。** 改了 Python 文件不重启，进程跑的还是旧代码。

最容易踩的是 **schema 变更**（改了 `app/models/` 或 `app/schemas/`）：

| 你改了什么 | 不重启的后果 |
|---|---|
| 加了响应字段（如 `reports.truncated`） | 前端拿到 `undefined` —— 字段**静默消失**，不报错。列表页会全都显示成「已交叉验证」 |
| 加了请求字段 | 后端读不到，前端传了等于没传 |
| 改了分类逻辑 | 报错文案还是旧的，用户看到「暂时不可用」而不是具体原因 |

**判断方法**：改了后端却看到旧行为，先怀疑没重启。

前端是 Next.js dev server，有热更新，不用管。

## 3. 改了数据库结构 → 先跑迁移

```bash
cd apps/api
uv run alembic upgrade head          # 应用迁移
uv run alembic current               # 看当前版本
uv run alembic downgrade -1          # 回退一条（可逆才做）
```

**改了 `app/models/*.py` 就要写迁移**。仓库用 Alembic，迁移文件在
`alembic/versions/`。

### 3.1 SQLite 的坑

- **Alembic 的 `add_column` 对 SQLite 是「重建表」**，不是真的 ALTER。
  表越大越慢（argus.db 约 50MB，几十秒级）。
- **加 NOT NULL 列必须给 `server_default`**。ORM 里的 `default=False`
  只是 Python 层的默认值，SQLite 加列时拿不到 → 迁移会失败。
  写法：`sa.Column("truncated", sa.Boolean(), nullable=False, server_default=sa.false())`。
- **`downgrade` 里的 `drop_column` 同样走重建表**，数据会丢。回退前先备份。

### 3.2 备份

```bash
cp apps/api/argus.db /tmp/argus.db.backup
```

`argus.db` 是 dev 库，但里面有本地向量索引（`chunk_embeddings` vec0 表），
重建要重跑嵌入 —— 别随手删。

### 3.3 迁移要幂等

迁移文件的 `upgrade()` 里先检查列在不在：

```python
if _has_truncated_column():
    return
```

理由：`alembic stamp` 之后手工改过表、或从别的分支 merge 过来时，
schema 状态和版本号可能对不上。上一条迁移（`d4e8f1a29b73`）就踩过这个。

## 4. 改了前端类型 → 两边都要改

前端类型**不是自动生成**的，是手写的镜像：

| 后端 | 前端 |
|---|---|
| `app/schemas/report.py` | `apps/web/lib/api/reports.ts` |
| `app/services/stream.py` | `apps/web/lib/api/sse.ts` |

改了后端 schema 要手动同步前端类型。`reports.ts` 的注释里写着
「改了那边必须同步改这里」。

## 5. 质量门（提交前必跑）

```bash
# 后端
cd apps/api
uv run ruff check app/ tests/ alembic/
uv run ruff format --check app/ tests/ alembic/
uv run mypy app/
uv run pytest tests/ -q --no-header -p no:cacheprovider

# 前端
pnpm --filter web lint
pnpm --filter web exec tsc --noEmit
```

**`pnpm --filter web tsc --noEmit` 是空命令**——`apps/web/package.json` 里没有
`tsc` script，它会打印「None of the selected packages has a "tsc" script」然后
**退出码 0**，什么都没跑。必须用 `exec tsc --noEmit`。

`ruff format --check` 在全库目前是红的（ruff 版本差异导致的既有状态，
改动前就红）。只保证**你改动的文件**干净，别去格式化别人的代码。

## 6. 已知的环境事实

- **数据库是 SQLite**（`apps/api/argus.db`），不是 Postgres。
  向量用 `sqlite-vec` 扩展，维度 1536（写死在 vec0 表 DDL 里）。
- **嵌入服务走阿里云百炼**（`EMBEDDING_API_KEY`）。欠费时
  `local_search` 的向量召回整个挂掉，报告会是 0 引用但**不报错**。
  实测：`cd apps/api && .venv/bin/python -c "import asyncio; from app.services.embedder import embed_texts; print(len(asyncio.run(embed_texts(['t']))[0]))"`
  返回 1536 就是正常。
- **模型服务走中转站** `llmapi.pro`（`ANTHROPIC_BASE_URL`）。它会在 SSE
  流消费途中随机断连，报 `RemoteProtocolError`。代码里有整轮重发兜底
  （`app/services/agent.py` 的 `_run_turn`），但重发 3 次全失败就会
  看到「模型连接在生成途中被中断」。**这是上游问题，不是代码 bug。**
- **中转站的 key 有多套，额度各算各的**。`apps/api/.env` 的
  `ANTHROPIC_API_KEY` 与 `~/.claude/settings.json` 的
  `ANTHROPIC_AUTH_TOKEN` **不是同一个令牌**（格式一样、额度池不同）。
  中转站报 403「Trial quota used up」时先拿另一个 key 试一次——同一个
  base_url、同一个模型，一个能用一个不能，就是令牌不同，跟服务无关。
- **中转站的配额错误会伪装成权限错误**。试用额度用完时上游返回
  **403 + permission_error**，message 才是真因
  （「Trial quota (40 requests) used up」）。只看状态码会报成
  「没有该模型的权限」，把排查方向带偏。
- **`httpx2` 与 `httpx` 的异常类不通用**。`httpx2.ConnectError` 不是内建
  `ConnectionError` 的子类，判网络类异常时两个都得认。
- **扩展思考会吃光输出预算**。请求里不设 `thinking.budget_tokens` 时，
  思考没有上限，会膨胀到把 `max_tokens` 吃光，正文一个字写不出来
  （表现为 `empty_response`）。**重试没用**——实测连打 5 次全部同样被
  吃光，是确定性的不是偶发。详见 `app/services/agent.py` 的
  `THINKING_BUDGET_TOKENS`。

## 链接

- [AGENTS.md（仓库根）](../AGENTS.md) — 硬配置、收尾流程
- [apps/api/CONTRIBUTING.md](../apps/api/CONTRIBUTING.md) — 后端贡献指南
- [docs/CONVENTIONS.md](CONVENTIONS.md) — 编码与设计约定
- [docs/CODE-QUALITY.md](CODE-QUALITY.md) — 代码质量约定
