---
paths:
  - "apps/api/**/*.py"
  - "apps/api/**/*.toml"
  - "apps/api/**/*.yml"
---

# argus · 后端审查规则

> 适用 `apps/api/**` 改动。通用规则见根 `CLAUDE.md`，跨项目通用规则见全局 `~/.claude/CLAUDE.md` §5。
> 每条写成可判定的形式——审查时需要能引用原文说明违反哪条。

## A1. 类型与门禁

- **mypy strict**（`pyproject.toml` 的 `[tool.mypy] strict = true`）：
  缺类型标注、返回 `Any`、无理由的 `# type: ignore` → 违反。
- **ruff**：`app/ tests/ alembic/` 全过。

**这两条 CI 已经跑过，审查时不要重复报**——官方 CR 会单独跑门禁。

## A2. 错误必须分类并带用户可读文案

**违反判据**：`app/services/errors*.py` 之外直接抛裸异常，或绕过
`classify_llm_error` / `classify_tool_error` / `classify_embedding_error`。

**为什么严重**：前端的错误提示由**错误码**决定，不是异常类型。
不分类 = 用户看到「处理时发生内部错误」。

## A3. 注释里的技术断言必须与框架实际行为一致

**违反判据**：docstring / 注释里对框架行为的描述与实际源码相反。

**典型**：曾写过「session 不可用后任何 db 操作都抛 PendingRollbackError
——**包括 rollback 自己**」。查 SQLAlchemy 源码：`SessionTransaction.rollback`
的 `declare_states` **显式接受 DEACTIVE 状态**，rollback 不抛；
`PendingRollbackError` 只在 `_raise_for_prerequisite_state` 里对
commit/flush/execute 抛出。

**为什么是 critical**：注释不是描述现状，是**指示操作**。
照着错的前提做补救，会把正确的数据改坏。

**判定方法**：读框架源码（`.venv/` 里的库代码可以读），不要靠记忆。
框架行为随版本变，记忆不可靠。

## A4. 时间语义统一 UTC aware

**违反判据**：`datetime.now()`（无时区）、naive 与 aware 混用、
naive 分支直接 `return value` 却注释说「按 UTC 解读」。

**为什么严重**：SQLite 上 `CURRENT_TIMESTAMP` 按定义就是 UTC；
但 Postgres 上绑到 `timestamptz` 时按**会话 TimeZone GUC** 解释——
同一段代码在两个库上差 8 小时，静默。

（通用判据见全局 `~/.claude/rules/cr-python.md` P5；
本条只写 argus 的具体后果。）

## A5. 补偿覆盖全部状态 + 补偿自身可失败

见全局规则 §5.1、§5.2。argus 的具体形态：一次摄取写**四处**状态
——正文行 / FTS 虚表 / 向量虚表 / `sources.chunk_count`。
补偿清了前三处却漏 `chunk_count`，用户看到「失败」却配着「21 块」。

**argus 特有**：补偿代码写在 `try` 块**内部**，而原始异常恰恰来自
它要清理的那个资源——那种情况下补偿的第一行就会抛，整个补偿一行不跑。

## What NOT to Flag（argus 后端）

> 通用不报项见全局 `~/.claude/rules/cr-python.md` 的 What NOT to Flag
> 与全局 `~/.claude/CLAUDE.md` §5.0.4。以下是 **argus 特有**的：

- **ruff / mypy 能抓到的**——缺类型标注、unused import、行长、格式。
  官方 CR 会单独跑门禁，重复报只是噪音。
- **「这里应该用 Pydantic 校验」**——除非改动涉及对外 API 入参。
  argus 的错误分类机制已覆盖用户可见错误（A2）。
- **「应该加索引」/「应该改成分页」**——性能建议，除非改动引入了
  全表扫描这类**可复现的**问题。
- **SQLite vs Postgres 的兼容性担忧**——本项目就是 SQLite，
  见根 `CLAUDE.md` §1「审查时不要假设的技术栈」。
- **「缺少重试」**——除非改动明确让某个瞬时失败变成永久失败。
- **测试代码里的** fixture 不够、mock 过度。

---

**相关**：完整后端规范见 `apps/api/CONTRIBUTING.md`（人类阅读）。
