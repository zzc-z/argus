# 前端去 mock —— 交接（2026-10-19）

> 新会话从这份文档接手。**最新章节在最上面**，往下是历史。

## 一句话状态

Word (.docx) 支持 + add-sources 修复 + 登录态改造**全部完成并验证**。
后端 516 测试全绿，前端 `tsc` / `eslint` / `next build` 全绿。
**全部未提交**，工作区 35 个 tracked + 6 个新目录。

---

# 🔴 当前状态（2026-10-19）

## 本次会话做了什么

### A. add-sources 页修复

**硬 bug：CSS Modules 引用了不存在的类**（解析成 `undefined`，样式静默失效）

| 文件 | 缺失 | 死类 |
|---|---|---|
| `QueueMonitor/index.module.css` | `headCount` `empty` `failedBadge` `itemStage` `errorText` `barFillFailed` | 25 个已删 |
| `UrlRssTabs/index.module.css` | `card` `header` `titleHint` | 21 个已删 |
| `add-sources/page.module.css` | `error` | 13 个已删 |

**文案与后端事实冲突**（逐条核对过后端源码）

| 原文案 | 改成 | 依据 |
|---|---|---|
| `MAX 100MB / FILE` | `50MB` | `storage.py` `MAX_UPLOAD_BYTES = 50MB` |
| `自动 OCR 与图表语义解析` | `文本型 PDF，扫描件暂不支持` | `parser.py` 提不出文字直接抛 ParseError，后端无 OCR |
| `支持多文件并发上传` | `一次可传多个文件` | `page.tsx` 是 `for...of await` 顺序传 |
| `资料名称（后端必填…）` | `（默认取自网址，可改）` | 实现细节不该漏给用户 |

**其他修复**
- URL 抓取失败显示两遍 → 拆 `urlError` / `uploadError` 两个 state
- 失败文案出现三遍 → `progressLabel` 失败时只给阶段名，删重复的 `statusRow`
- URL 建源 `size_bytes` 为 null → 渲染成孤儿分隔符 `文稿 · ·`，改条件渲染
- 队列尾部徽章显示英文枚举 `queued` → 中文短词（`stageLabel`）
- `barFillLive` 无宽度无动画（注释声称有）→ 补滑入动画 + `prefers-reduced-motion`

### B. 登录态（用户明确要求删除所有「未登录/已登录」文案）

- 删顶栏「GitHub 登录」标签、未登录时的「登录」链接及其 CSS
- `(dashboard)/layout.tsx` 加 `AuthGuard`：未登录 `replace('/login?next=...)`
- **`AuthStatus` 四态**：`loading` / `authenticated` / `anonymous` / `unreachable`
  - 只有 401 才是 `anonymous`；网络失败 / 500 / 后端重启都是 `unreachable`
  - `unreachable` 显示「连不上服务端 + 重试按钮」，**不踢登录页**
  - 实测：停掉后端 → 显示重试，URL 保持原页；点重试直接恢复
- layout 保持 **Server Component**，只有 `AuthGuard` 一个 client 文件

### C. Word (.docx) 支持（用户开的 deploy-light）

**为什么不能并进 `SourceType.TEXT`**：docx 是 ZIP 包，`TextParser` 会拿 utf-8
解二进制，产出乱码且**不报错**。必须新增 `SourceType.DOCX`。

| 文件 | 改动 |
|---|---|
| `pyproject.toml` + `uv.lock` | `python-docx>=1.2`（MIT）。**这是 tester 抓出的部署阻塞**——先写了 `import docx` 却没声明依赖，别人 `uv sync` 直接 ImportError |
| `models/source.py` | `SourceType.DOCX` |
| `services/parser.py` | `DocxParser` |
| `services/ingest.py` | `_PARSERS` 注册 + **`asyncio.to_thread`** 挪出事件循环 |
| `gateway/sources.py` | `_EXT_TO_TYPE` 加 `.docx`、415 文案 |
| `gateway/auth.py` | OAuth 深链 `next`（签名 cookie 存） |
| 前端 4 处 | `SourceTypeV`、`KIND_LABEL`/`ICON_NAME`/`TYPE_TO_FILTER`/`countByType`、`KIND`、`ACCEPTED`+chip |

**浏览器实测**：传真 docx → 7 个切片，表格按行进入且顺序正确，`page` 为 null，
队列显示「Word · 37.0 KB · 已索引」。sources 页「纯文本」tab 计数 3、点进去 3 行。

### D. CR 抓出并已修的 4 个严重

| | 问题 | 修法 |
|---|---|---|
| C1 | 嵌套表格整张丢失（`_Cell.text` 不含嵌套表 → 整行判空跳过） | `_walk` 递归下降 |
| C2 | `w:sdt`（Word 自动目录 / 内容控件 / 封面页）整块被丢 | 加进 `_CONTAINER_TAGS` |
| C3 | 解压放大可打爆内存 + 解析同步卡死事件循环 | `_guard_xml_size()` 读 ZIP 目录的 `file_size`（不解压）+ `asyncio.to_thread` |
| C4 | 合并单元格去重吃掉合法数据（`2024\|2024` → `2024`） | 判据换成 **tc 元素身份** |

**页码取舍**（用户已确认）：docx 无页码概念，`ParsedBlock.page` 恒为 `None`。
报告引用退化成 `[1]` 而非 `[1, p.3]`。

**页眉页脚不抽**（用户已确认，注入回归验过）：页眉是所有页共用的一个 part，
抽进来会按页数重复 N 份稀释正文权重，且给不出真实页码。3 条测试钉住这个决策。

---

## 门禁（已跑，全绿）

```bash
# 后端
cd apps/api
.venv/bin/python -m pytest tests -q          # 516 passed
.venv/bin/python -m mypy app                 # 42 files, 0 issue
.venv/bin/python -m ruff check app tests     # All checks passed

# 前端
cd apps/web
pnpm exec tsc --noEmit                       # 0 error
pnpm exec eslint app components lib --max-warnings=0   # 0 error
pnpm build                                  # 14/14 static pages
```

## 怎么验（关键，之前绕了很久）

后端**必须重启**——8000 端口跑旧进程时 `/sources` 和 `/reports` 全 404：

```bash
lsof -ti:8000 | xargs kill
cd apps/api && .venv/bin/python -m uvicorn app.main:app --port 8000
```

登录只有 GitHub OAuth，但后端有个现成脚本 `apps/api/scripts/dev_login.py`
（它会确保 `dev@argus.local` 这个用户存在，并把他的 JWT 打到 stdout）：

```bash
# 必须在 apps/api 下跑：Settings 用 env_file=".env"，换 cwd 就找不到配置
cd apps/api && uv run python scripts/dev_login.py > /tmp/jwt.txt
# token 走管道，不要回显到终端或对话里
curl -H "Cookie: argus_session=$(cat /tmp/jwt.txt)" http://localhost:8000/api/v1/sources
```

要在**浏览器**里看认证态，得手动注入 HttpOnly cookie。造 state 文件
（**必须同源**，跨域 fetch 会被 CORS 挡）：

```python
# 在 apps/api 下跑，token 不要 print 到 transcript
from app.services.token import create_access_token
import json, pathlib
pathlib.Path('/path/to/apps/web/public/_state.json').write_text(json.dumps({
    "cookies": [{"name": "argus_session", "value": create_access_token(9),
                 "domain": "localhost", "path": "/", "httpOnly": True,
                 "secure": False, "sameSite": "Lax", "expires": -1}],
    "origins": []}))
```

拷到 `apps/web/public/`，浏览器里 `fetch('/_state.json')` 再
`document.cookie = ...`。**用完立刻删**——它含真实 token。

**用户是 user_id=9**（`e2e@test.local`）。后端按用户隔离数据，用错 user_id
会得到**看起来像缺路由的 404**（`/sources/1` 对 user 1 是 404，对 user 9 是 200）。

---

## 技术债（2026-10-19 已清）

CR 报的后端 4 严重 + 前端 13 重要，**本轮全清**（用户明确说"技术债直接处理"）。

### 已清

- **I10 轮询定时器**（`add-sources/page.tsx`）：`setInterval` 依赖 `[]` 永不停
  → 改成**自调度链**（每个 pending id 一条链，请求完成才安排下一拍）。
  慢请求不再堆叠；资料进入终态（indexed/failed）即停。
  浏览器实测：8 秒内对 2 条已 indexed 的资料**一个请求都没发**（旧代码会发 10+ 个）。
- **I11a 上传错误覆盖**：`setUploadError` 是覆盖不是追加 → 改成 `uploadErrors[]` 累积。
- **I11b 初次加载吞错**：`.catch(() => undefined)` 吞掉 500 和网络错误 →
  非 401 的错误现在显示「加载资料列表失败」。实测后端 500 时页面留在原地并提示。
- **I7 TYPE_TO_FILTER 值域**：`TabKey` 从字面量联合派生，「映射到不存在的 tab」
  现在是**编译错误**（实测 `docx: 'epub'` → TS2322）。这是 CR 说的
  「唯一没有编译期保护的一处」。
- **I8 countByType 返回类型**：`Record<SourceTypeV, number>` → `Record<TabKey, number>`，
  不再有恒为 0 的 `counts.docx` 静默错误。
- **I9 死代码**：删掉 `SourceRow.progress` / `STAGE_LABEL` / `processing`
  （上一轮删了 ProgressBar 渲染，这边没跟上）。
- **I12 矛盾注释**：修掉「UserMenu 负责」（现在�� AuthGuard）、
  `meta` 字段注释自相矛盾、`parser.py:80` 硬编码行号（已漂到 :86）。
- **docx 标签两页不一致**：`DOCX` vs `Word` —— 两份 `Record` 各写一遍，
  改一处忘另一处无提示。提取到 `sources/lib/sourceKind.ts` 共享，
  两页各自的措辞（`libraryLabel` / `queueLabel`）保留。

### 没清（有意留下）

- **I13 搜索框没接逻辑**：`SourceFilterBar` 的输入框无 `value`/`onChange`，
  用户输关键词列表不动。docstring 声称"不是假功能"——**这句话是错的**。
  属上一轮 de-mock 组，本轮未动。下轮要么接上要么删掉输入框。

### 页面 mock（范围外，用户明确不改）

- `explore/mock.ts` 残留：`DAG_STATS.pipeline`、`HARDWARE_METRICS`、`ANALYST_RAW_STATE`
- `AgentNode.tokens` 永不被后端更新（`NodeEventV` 没有 per-node token 字段）
- `report/[id]` 页仍是 mock（但有真接口 `GET /reports/{id}`）
- `dashboard/` `topics/` `reports/` `notifications/` `settings/` 全部 mock

---

## 教训（本次踩的坑）

1. **prettier 会在 `cd` 进子目录后作用于整个仓库**。`cd apps/web/app/x && prettier --write .`
   把 61 个无关文件格式化了。**必须传显式文件列表**，或用 `--ignore-path`。
   回滚清单在 `/tmp/revert-safe.txt`（已用完）。

2. **`useSearchParams` 必须包在 Suspense 里**，哪怕调用方是 Server Component。
   本次 `(dashboard)` 组里的 `/error-404` 会被静态预渲染，next build 直接以
   `missing-suspense-with-csr-bailout` 失败。

3. **CSS Modules 里没定义的类会解析成 `undefined`**，模板字符串拼成字面量
   `"undefined"` 的 class 名，**样式静默失效不报错**。改 CSS 后要核对
   tsx 里的 `styles.x` 与 css 里的定义是否一致。

4. **lxml 的 `XMLSyntaxError` 继承 `SyntaxError` 而不是 `ValueError`**。
   `except (BadZipFile, ValueError)` 漏掉它 → 用户看到 500 而不是「这份文件读不了」。

5. **清洗危险输入不如整条拒**。`_safe_next` 原先「剥掉不可打印字符」，
   `/path\r\nX-Injected: 1` 变成 `/pathX-Injected: 1`——注入内容原封不动还在。
   是注入测试抓出来的。

6. **「相邻文本相同」不能当合并单元格的代理**。判据是 **tc 元素身份**：
   横向合并 `row.cells` 返回同一个 `_tc`；纵向合并每行各有自己的 tc；
   合法重复（`2024|2024`）是两个不同 tc。

7. **长函数改动先整体 Read 再一次性重写**。本次 `_walk` 写错两次
   （重复 → 全丢），靠逐个场景实测才收敛。

8. **凭记忆写后端 schema 会漏字段**（上一轮的教训，仍然成立）。

---

# 历史：2026-10-18（去 mock 第一轮）

## 任务

把 explore / sources / add-sources 三个页面的 mock 数据换成真实后端接口。
后端零端点的另 5 个页面（dashboard / reports / topics / settings / notifications）
**不在范围内**——它们的 mock 是「后端还没做」而不是「忘了接」。

## 批 1：后端 reports 落盘（commit `915d150`）

前端 sources 页要显示「关联报告 N 篇」，但后端既没有 reports 表、报告也从不停留。

- 新表 `reports` + `report_sources`，migration `c3d9e1f27a04`
- `run_agent` 在 done 帧之前落盘，失败降级为 `report_id=None` 不中断流
- `GET /api/v1/reports`（列表）/ `GET /reports/{id}` / `DELETE /reports/{id}`
- `SourceResponse.citation_count`，按**报告去重**

## 批 2 前半：sources 页接真接口（未提交）

已删 `sources/mock.ts`（全仓零引用后）。新增 `sources/lib/sourceTypes.ts` 做映射。

删掉的设计稿元素（后端没有对应，编不出来）：
- 分页按钮（`GET /sources` 无分页参数，一次返回全部）
- 侧栏的时间跨度 / 课题标签 / 向量库配额（`Source` 模型无 tags 字段）
- 表格的进度条（后端只有 6 个**阶段**，没有百分比）
- 批量操作里的「重新切片」「加入专题」（后端无对应端点）

新增 `components/common/EmptyState/`，区分两种空态：
- 库里没资料 → 引导上传
- 筛选后为空 → 给「清空筛选」**而不是**「上传资料」

## 批 2 后半：add-sources 页（未提交）

- 假 `setInterval` 进度条 → 真上传 + 轮询 `GET /sources/{id}`
- 新增 `add-sources/lib/queueTypes.ts`
- `UploadDropZone`：chip 从 4 个假的改成后端真收的 4 种；加扩展名校验
- `UrlRssTabs`：RSS tab 删掉（后端无订阅端点）；加 title 输入框
- `ProcessingOptions/` 组件整个删除
- `add-sources/mock.ts` 删除
