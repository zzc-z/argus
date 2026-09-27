---
name: api-doc
description: 为 argus 后端 FastAPI 路由生成 OpenAPI 文档片段、API 调用示例、Markdown 文档草稿。触发场景：(1) 用户说"写 API 文档"/"加 endpoint 文档"；(2) 新增/修改 FastAPI 路由；(3) 用户提到 OpenAPI / Swagger / 接口契约。Read apps/api/app/ 下的路由文件 + pyproject.toml。
---

# api-doc — argus 后端 API 文档生成

## 必读清单

开始之前必须 Read：

1. `~/Desktop/argus/apps/api/pyproject.toml` — 项目元信息、依赖（FastAPI 0.141+、Pydantic 2.10+）
2. `~/Desktop/argus/apps/api/app/` 下的路由文件（`routers/*.py` 或 `api/*.py`）
3. `~/Desktop/argus/apps/api/app/main.py`（或入口文件）— FastAPI app 实例

## 工作流程

### A. 生成 OpenAPI JSON

```bash
cd ~/Desktop/argus/apps/api
uv run python -c "
from app.main import app
import json
print(json.dumps(app.openapi(), indent=2))
" > /tmp/openapi.json
```

### B. 按路由分组生成 Markdown 表格

输出到 `apps/api/docs/endpoints.md`，每个路由一节：

```markdown
## POST /api/v1/topics

创建订阅主题。

**Request body**:
| 字段 | 必填 | 类型 | 说明 |
|------|------|------|------|
| name | ✅ | string | 主题名称 |
| query | ❌ | string | 初始查询 |

**Response 200**:
| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主题 ID |
| created_at | datetime | 创建时间 |

**Errors**: 422（参数错误）/ 401（未鉴权）
```

### C. 调用示例（curl / Python httpx）

```bash
curl -X POST http://localhost:8000/api/v1/topics \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"AI 监管"}'
```

```python
import httpx
async with httpx.AsyncClient() as client:
    r = await client.post(
        "http://localhost:8000/api/v1/topics",
        json={"name": "AI 监管"},
        headers={"Authorization": f"Bearer {token}"},
    )
    r.raise_for_status()
```

## 风格约束

- 中文表格（与项目 AGENTS.md 一致）
- 路径前缀用 `apps/api/docs/endpoints.md` 维护
- 不要重写已有路由代码——只生成文档
- 鉴权说明：当前是 `Bearer JWT`，W2 接 Supabase 后会改用 Supabase session