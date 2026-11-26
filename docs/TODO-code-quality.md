# 待办：代码质量已知问题

> 2026-11-25 立。只记实测到的问题与证据，不含实现方案；修之前先复核现状。
> a11y 与主题问题见 `TODO-frontend-a11y-platform-ui.md`，这里不重复。
> 测的是当天的工作区（含未提交改动）。

## 后端

### B1. 7 个接口收到超大整数会 500

`id` 或 `offset` 超过 2⁶³−1 时，抛 `OverflowError: Python int too large to convert to
SQLite INTEGER`。复现：已登录访问 `/api/v1/sources/9223372036854775808`。

- `GET /reports`（`offset`）、`GET` / `DELETE /reports/{report_id}`
- `GET` / `DELETE /sources/{source_id}`、`GET /sources/{source_id}/chunks`、
  `PATCH /sources/{source_id}/activate`

严重度：minor（正常用户碰不到）。修好后删 `tests/test_api_fuzz.py` 的 `KNOWN_OVERFLOW` 对应行。

### B2. 5 个依赖有已知漏洞

pip-audit 2.10.1，按 `uv.lock` 导出的生产依赖。**是否影响 argus 均未核实。**

| 包 | 当前 | 修复版本 | 编号 |
|---|---|---|---|
| authlib | 1.8.0 | 1.9.1 | PYSEC-2026-4355 ~ 4360、CVE-2026-96760、CVE-2026-116672 |
| certifi | 2026.7.22 | 2026.10.18 | PYSEC-2026-4320 |
| joserfc | 1.7.5 | 1.7.6 | CVE-2026-119284 |
| langgraph-sdk | 0.4.5 | 0.4.6 | CVE-2026-118667 |
| opentelemetry-api | 1.45.0 | 1.45.2 | CVE-2026-114603、CVE-2026-126360 |

- authlib 优先：登录在用（`app/gateway/auth.py:25-26`，`generate_token` 与 Starlette `OAuth`）。
- `app/` 里没有 import `langgraph` / `langchain_core` / `opentelemetry`，但 pyproject 声明了前两个；
  是否能删依赖待评估。
- 升级后删 `.github/workflows/ci.yml` 里对应的 `--ignore-vuln`。

### B3. 安全相关代码的测试覆盖率偏低

整体 93.91%（含分支），最低的几处是安全代码：`services/secret_store.py` 71.56%、
`gateway/auth.py` 74.86%、`services/token.py` 77.14%。CI 没有覆盖率门槛
（`fail_under = 80` 只在带 `--cov` 时生效）。

### B4. schemathesis 没覆盖的接口

`/research/*`、`/auth/*`、`/sources/url`、`/healthz`、`/readyz` 被排除（会真调模型、OAuth、外网或开发库）。
且只查 5xx，不查越权——「A 用户看不到 B 的数据」仍靠手写测试。

### B5. `uv.lock` 落后于 `pyproject.toml`

`uv lock --check` 不通过。`pyproject.toml` 有未提交改动（新增 `cryptography`），提交前要 `uv lock`。

### B6. 待人工复核的静态检查结果

ruff 扩展规则：`S608`（字符串拼 SQL）13 处，在 `bm25.py` / `ingest.py` / `vectorstore.py`；
`BLE001`（捕获宽泛异常）4 处：`dashboard.py:148`、`health.py:50`、`agent.py:511`、`fetcher.py:273`。
是否真有问题未核实。

### B7. 文件超过 800 行

`services/errors.py` 994、`services/tools.py` 885。

## 前端

### F1. `import * as React`

100 个文件，其中 45 个没用到 `React.x`；`components/ui` 的 6 个是 shadcn 生成，不动。
具名导入改写在副本上验证过：94 个文件改完 tsc 0 错误，未跑 build 和页面。

### F2. 无必要的 `useMemo` / `useCallback`

全项目 81 处调用，`memo(` 0 处；原型规则标出约 50 处疑似，**有误报，要逐个看**
（如 `StreamingReport/index.tsx:131` 是真实的重计算）。确认没用的示例：`settings/page.tsx:51,55`。

### F3. 没有自动化测试

`apps/web` 测试文件 0 个。

### F4. 其他 lint 结果

数组索引做 key 25 处；返回 Promise 的函数传给期望 void 的属性 8 处；`explore/page.tsx` 957 行。

## 工程

### E1. 格式门禁缺口

Prettier 不合格 40 个文件，且 pre-commit 与 CI 都不跑；`ruff format` 不合格 28 个（CI 只查改动文件）。

### E2. 审查规则引用失效

`CLAUDE.md`、`.claude/rules/web.md` 引用的 `~/.claude/rules/cr-python.md`、`cr-typescript.md`、
`cr-react.md` 和全局 `CLAUDE.md` §5 都已不存在；现行的是 `gen-*.md` 与 `~/.claude/docs/CR-GUIDE.md`。

### E3. ESLint 9 已停止维护

npm 标记为不再支持，升级要等 `eslint-config-next` 兼容情况。
