# Argus — 部署与运维设计

> Version: 0.1.0 · Date: 2026-09-18

## 1. 总览

Argus 双部署路径：
- **开发 / 演示**：Docker Compose 一键起所有服务（5 分钟）
- **生产**：前端 Vercel + 后端 Docker Compose on VPS / K8s

## 2. Docker Compose（本地 + VPS）

### 2.1 服务清单

```yaml
# docker-compose.yml
version: '3.9'

services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: argus
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: argus
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./infra/postgres/init.sql:/docker-entrypoint-initdb.d/init.sql
    ports: ["5432:5432"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U argus"]
      interval: 5s

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]

  api:
    build: ./apps/api
    command: uvicorn gateway.main:app --host 0.0.0.0 --port 8000
    env_file: .env
    depends_on:
      postgres: { condition: service_healthy }
      redis: { condition: service_healthy }
    ports: ["8000:8000"]

  scheduler:
    build: ./apps/api
    command: python -m scheduler.main
    env_file: .env
    depends_on: [postgres, redis]

  phoenix:
    image: arizephoenix/phoenix:version-13.18.0  # 官方命名规则：version-X.X.X（非 :latest，确保可重现构建）
    ports: ["6006:6006"]
    environment:
      PHOENIX_SQL_DATABASE_URL: postgresql://argus:${POSTGRES_PASSWORD}@postgres:5432/phoenix

  web:
    build: ./apps/web
    ports: ["3000:3000"]
    environment:
      NEXT_PUBLIC_API_URL: http://localhost:8000

  minio:
    image: minio/minio
    command: server /data --console-address ":9001"
    ports: ["9000:9000", "9001:9001"]
    environment:
      MINIO_ROOT_USER: ${MINIO_USER}
      MINIO_ROOT_PASSWORD: ${MINIO_PASSWORD}

volumes:
  postgres_data:
```

### 2.2 一键启动

```bash
# 1. 准备环境变量
cp .env.example .env
# 编辑 .env，填入 ANTHROPIC_API_KEY / OPENAI_API_KEY / TAVILY_API_KEY / COHERE_API_KEY / GITHUB_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_ID / ...

# 2. 启动
docker compose up -d

# 3. 等待健康
docker compose ps
# 5 分钟后所有服务 healthy
```

### 2.3 端口
- 3000: Web UI
- 8000: FastAPI
- 5432: Postgres
- 6379: Redis
- 6006: Phoenix
- 9000/9001: MinIO

## 3. 环境变量模板

```bash
# .env.example

# Database
POSTGRES_PASSWORD=changeme
DATABASE_URL=postgresql+asyncpg://argus:changeme@postgres:5432/argus

# Redis
REDIS_URL=redis://redis:6379/0

# S3 / MinIO
S3_ENDPOINT=http://minio:9000
S3_ACCESS_KEY=changeme
S3_SECRET_KEY=changeme
S3_BUCKET=argus-files

# LLM
ANTHROPIC_API_KEY=sk-ant-...             # Anthropic 模型：Sonnet 5 / Haiku 4.5（注意：Sonnet 4.5 已在 2026-09-29 退役，必须用 sonnet-5）
OPENAI_API_KEY=sk-...                    # OpenAI：text-embedding-3-small（1536 → 512 维度）
COHERE_API_KEY=...                       # Cohere Rerank v3（SDK 7.1+）
TAVILY_API_KEY=tvly-...                  # Tavily Search
FIRECRAWL_API_KEY=fc-...                 # Firecrawl Scrape
ASSEMBLYAI_API_KEY=...                   # AssemblyAI 视频/音频转写

# Memory
MEM0_API_KEY=...

# OAuth
GITHUB_OAUTH_CLIENT_ID=...
GITHUB_OAUTH_CLIENT_SECRET=...
GOOGLE_OAUTH_CLIENT_ID=...
GOOGLE_OAUTH_CLIENT_SECRET=...
JWT_SECRET=...
OAUTH_REDIRECT_BASE=http://localhost:3000

# Phoenix
PHOENIX_COLLECTOR_ENDPOINT=http://phoenix:6006

# App
APP_ENV=development
LOG_LEVEL=INFO
CORS_ORIGINS=http://localhost:3000
```

## 4. Vercel 部署（前端）

### 4.1 自动部署

`apps/web` 推到 GitHub → Vercel 自动 build & deploy。

```json
// vercel.json
{
  "buildCommand": "pnpm --filter web build",
  "outputDirectory": "apps/web/.next",
  "framework": "nextjs",
  "rootDirectory": "apps/web",
  "env": {
    "NEXT_PUBLIC_API_URL": "@api-url"
  }
}
```

### 4.2 环境变量

Vercel Dashboard 配置：
- `NEXT_PUBLIC_API_URL`：生产 API 地址
- `NEXT_PUBLIC_SUPABASE_URL`（如果用 Supabase）

## 5. 后端生产部署

### 5.1 单 VPS 部署（推荐 MVP）

```bash
# VPS: Ubuntu 22.04 / 4GB RAM / 80GB SSD

# 安装 Docker
curl -fsSL https://get.docker.com | sh

# 拉代码
git clone https://github.com/yourname/argus.git
cd argus

# 配置环境
cp .env.example .env
nano .env

# 启动
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# 反向代理 + HTTPS（Caddy）
sudo apt install -y caddy
# /etc/caddy/Caddyfile
api.yourdomain.com {
  reverse_proxy localhost:8000
}
web.yourdomain.com {
  reverse_proxy localhost:3000
}

sudo systemctl reload caddy
```

### 5.2 升级

```bash
git pull
docker compose pull
docker compose up -d --build
docker system prune -a
```

### 5.3 备份

```bash
# Postgres 每日 cron 备份
0 3 * * * docker exec argus-postgres pg_dump -U argus argus | gzip > /backup/argus-$(date +\%F).sql.gz

# 保留 30 天
find /backup -name "argus-*.sql.gz" -mtime +30 -delete
```

## 6. CI/CD

### 6.1 GitHub Actions

```yaml
# .github/workflows/ci.yml
name: ci
on: [pull_request]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: '3.12'}
      - uses: astral-sh/ruff-action@v1
      - uses: pnpm/action-setup@v4
      - run: pnpm install --frozen-lockfile
      - run: pnpm --filter web lint

  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: pgvector/pgvector:pg16
        env:
          POSTGRES_USER: argus
          POSTGRES_PASSWORD: test
          POSTGRES_DB: argus_test
      redis:
        image: redis:7
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
      - run: uv sync
      - run: uv run pytest --cov=apps/api --cov-report=xml
      - uses: codecov/codecov-action@v4

  e2e:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
      - uses: pnpm/action-setup@v4
      - name: Start services
        run: docker compose -f docker-compose.test.yml up -d
      - name: Wait
        run: sleep 30
      - name: Playwright
        run: pnpm --filter web test:e2e
      - uses: actions/upload-artifact@v4
        if: failure()
        with:
          name: playwright-report
          path: apps/web/playwright-report/
```

### 6.2 Release

- main 分支通过 CI → 自动创建 GitHub release（v0.1.0, v0.2.0 ...）
- tag 推送触发 Docker image 构建 + 推 Docker Hub
- 前端 merge to main → Vercel 自动部署 production

## 7. 监控

### 7.1 日志

```python
import structlog

log = structlog.get_logger()

# JSON 输出，Loki / Vector 解析
log.info("agent_run_completed",
    user_id=user_id,
    run_id=run_id,
    duration=duration,
    tokens=tokens,
    passed=passed,
)
```

### 7.2 指标（Prometheus）

`apps/api/gateway/metrics.py`：

```python
from prometheus_client import Counter, Histogram

agent_runs_total = Counter("argus_agent_runs_total", "Total agent runs", ["status"])
agent_run_duration = Histogram("argus_agent_run_duration_seconds", "Run duration")
token_usage = Counter("argus_tokens_total", "Token usage", ["model"])
retrieval_latency = Histogram("argus_retrieval_latency_seconds", "Retrieval latency")
```

暴露 `/metrics` 给 Prometheus 抓取。

### 7.3 Trace

Phoenix 自动收集所有 agent 调用的 span。

### 7.4 Alert

`infra/alerts/alerts.yml`：

```yaml
groups:
- name: argus
  rules:
  - alert: AgentRunFailureHigh
    expr: rate(argus_agent_runs_total{status="failed"}[5m]) > 0.05
    for: 10m
    annotations:
      summary: "Agent 失败率 > 5%"

  - alert: TokenBudgetExceeded
    expr: rate(argus_tokens_total[1h]) > 1000000
    for: 1h
    annotations:
      summary: "Token 用量超预算"

  - alert: RetrievalSlow
    expr: histogram_quantile(0.95, argus_retrieval_latency_seconds) > 1.0
    for: 15m
    annotations:
      summary: "检索 P95 > 1s"
```

Webhook → Slack / Discord / Email。

## 8. 安全清单

- [ ] 所有 secret 走 `.env`，不进 git
- [ ] OAuth state 参数防 CSRF
- [ ] JWT 用 RS256 / HS256 + refresh rotation
- [ ] Postgres RLS 启用 + 测试覆盖
- [ ] S3 presigned URL 限 5 分钟有效期
- [ ] API 限流：每用户 60 req/min
- [ ] CORS 严格白名单
- [ ] 依赖安全扫描（`pip-audit` / `pnpm audit`）每周 cron
- [ ] 容器镜像非 root 运行
- [ ] HTTPS only（Caddy / Cloudflare）

## 9. 灾难恢复

| 场景 | RTO | RPO | 策略 |
|---|---|---|---|
| 单容器崩溃 | < 5min | 0 | Docker restart policy |
| 数据库损坏 | < 1h | 24h | 每日 pg_dump + WAL 归档 |
| 误删数据 | < 30min | 0 | soft delete + admin 恢复 |
| LLM API 故障 | < 1min | 0 | 路由降级到备份模型 |
| 全机房故障 | < 24h | 24h | VPS 备份 + 镜像异地 |

## 10. 成本估算（参考）

| 项 | 单价 | 月用量 | 月成本 |
|---|---|---|---|
| Anthropic Sonnet 5 | $2/M input + $10/M output | 50M input + 10M output | $200 |
| Anthropic Haiku 4.5 | $0.25/M + $1.25/M | 100M + 20M | $50 |
| OpenAI Embedding | $0.02/M | 10M tokens | $0.20 |
| Cohere Rerank | $1/1k search | 100k searches | $100 |
| Tavily | $0.005/search | 100k | $500 |
| Mem0 | $0.001/memory op | 1M ops | $1000 |
| VPS (4GB) | $24/mo | 1 | $24 |
| Vercel Pro | $20/mo | 1 | $20 |
| **总计** | | | **~$2000/mo** |

MVP 阶段用 Sonnet + Haiku 路由、Mem0 限频、缓存 → 可压到 $300-500/mo。