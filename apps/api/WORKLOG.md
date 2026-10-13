# Argus API 开发工作日志

> 用途：上下文压缩后据此恢复开发状态。**最新的章节在顶部**。
> 最后更新：2026-10-13（TAVILY_KEY 已配，联网搜索实测跑通）

---

# 🔴 最新：TAVILY_API_KEY 已配——联网搜索第一次真正工作

## 进度

W2 Day 9/10/11 完成 + 补 CR 三轮完成，**430 tests 全绿**。
`TAVILY_API_KEY` 从 Day 9 起就挂在「未申请」栏里，现在申请到了，实测跑通。

## 实测（真实中转站 + 真实 Tavily + 真实本地资料）

提问「NVIDIA Blackwell 的能效提升和部署散热要求分别是什么？」，
本地存了一份只有两句话的技术笔记（能效 2.5 倍、GB200 120kW 液冷）：

```
节点: supervisor → researcher → writer → researcher → writer → ...
      researcher → researcher → researcher → researcher → writer
      → analyst → critic
工具: local_search(ok 470ms), local_search(ok 156ms),
      tavily_search(ok 3285ms), tavily_search(ok 5859ms),
      tavily_search(ok 3232ms), dedup(ok 0ms)
引用: 2 条，都来自本地资料（向量+BM25 / 向量）
done: turns=4 in=8747 out=2249 truncated=False
正文: 2304 字
```

模型表现值得记：联网之后它主动**修正了本地资料的口径**——本地只说
「能效提升 2.5 倍」，它查完补充「单芯片 TDP 其实是上升的（H100 700W →
Blackwell 1000W），能效增益来自单位能耗下的工作量而非单芯片更省电」，
并区分了系统级宣传口径与芯片级。这种「用外部证据修正内部资料」的行为
是 prompt 与检索都通了才会出现的。

## 中转站断连的实测行为

跑第二遍时撞上 `httpx2.RemoteProtocolError: peer closed connection
without sending complete message body`。**服务端行为是对的**：
`truncated=True` + `ErrorEvent(llm_unavailable)` 正常发出，连接没裸断。
`gateway/research.py` 的「所有异常都转 ErrorEvent」在真实故障下生效了。

（第一次观察到的「已收到的正文全丢」是测试脚本的问题——
用 `ASGITransport` 同步读全量响应，断连时客户端侧整个 buffer 没了。
真实浏览器是流式读，不会这样。别把客户端测试工具的缺陷记成服务端 bug。）

## 待办更新

| 事项 | 状态 |
|---|---|
| ~~`TAVILY_API_KEY` 未申请~~ | ✅ 已配，实测搜索与完整 agent 链路均跑通 |

---


# 🔴 最新：补 CR 三轮（对 Day 9/10/11 回头审查）

## 进度

W2 Day 9/10/11 全部完成，**415 tests 全绿**，mypy strict 37 文件零问题，
ruff 干净。已提交：`0a12bb9` / `b6b63e1` / `c865927`。

## 为什么要回头补 CR

Day 11 完成时 347 tests 全绿、mypy strict 干净、ruff 干净，**质量门一条
问题都没报**。起3 个 reviewer 审 Day 9/10/11（按改动规模与风险排序），
报出 2 严重 + 6 重要（Day 11）、4 严重 + 6 重要 + 8 细节（Day 9/10）。

**最关键的发现：报出的问题里大部分质量门查不出来。**

| 类型 | 能不能被测试发现 |
|---|---|
| 读错框架行为（以为 yield 依赖提前关闭） | ❌ 测试全绿 |
| 绕过依赖注入（测试静悄悄连开发库） | ❌ 测试全绿 |
| 注释引用不存在的常量 | ❌ 测试全绿 |
| 文档谎报消费者（断言前端会消费，实际没有） | ❌ 测试全绿 |
| 契约字段缺失 | ⚠️ 部分 |

## 修掉的（都有复现或实测支撑）

### 1. 并发闸门是 TOCTOU 竞态

`_reject_if_full()` 在端点内同步检查，真正 acquire 在生成器里，中间隔着
「响应开始发送」的 await。两个 reviewer 独立复现：10 个并发请求全部拿到
200，503 一次都不触发——闸门在需要它的时候完全不生效。排队的请求每个
pin 住一条 DB 连接，16 个并发就把连接池打爆。

**修法**：`_try_acquire_slot()` 把检查与获取合并进同一同步块。

半路踩坑：`asyncio.Semaphore` **没有** `acquire_nowait`（那是 threading 的
API）。改用「`locked()` 判断 + `acquire()` 走快路径」——读源码确认
`acquire()` 第一句就是 `if not self.locked(): self._value -= 1; return True`，
**一个 await 都没有**，所以在协程里调它本身就是原子的。

### 2. StaticPool 单连接导致已提交数据被静默吞掉

`async_creator` 让 SQLAlchemy 走StaticPool 分支，全进程共用一条 SQLite
连接，两个并发事务落进同一个事务里。

实测（我自己的复现，不是照抄报告）：

| | A 已提交的行 | 判定 |
|---|---|---|
| 修复前 StaticPool | 0 行 | ❌ 被 B 的回滚吞掉 |
| 修复后 AsyncAdaptedQueuePool | 1 行 | ✓ 保住了 |

**修法**：显式 `poolclass=AsyncAdaptedQueuePool` + `pool_size=4`。

**变异测试的教训**：第一次验证用 8 并发 × 20 条，修复前后都是 160/160
全对，看不出差别。换场景才复现出——**A 提交、B 回滚**。原因是并发写
不触发回滚路径。挑变异场景要对准机制。

### 3. `knn_search` 默认参数等于全库搜索

`source_ids: Sequence[int] | None = None` 里，漏传第三四个参数就会检索到
全库数据，然后 `find_many` 回查到别人的正文。**改成必填**：漏传从静默
串库变成 TypeError。

### 4. 向量 engine 绕过 dependency_overrides

与 Day 11 修的 `get_session` 同源。潜伏至今是因为路由测试都换成了假
agent，一旦有人写「真实 agent + local_search」的端到端测试就会踩到。
改成 `VecEngineDep = Annotated[AsyncEngine, Depends(get_vector_engine)]`。

### 5. 列表接口连带加载全部切片正文

`Source.chunks` 的 `lazy="selectin"` 是无条件 eager。实测列资料发 2 条
SQL，第二条把整份资料的正文拖回来——列表页只显示 title/status，一个
字符都用不上。改 `lazy="raise"`。

半路踩坑：`lazy="raiseload"` 在 SQLAlchemy 2.x 不存在，报 `Can't find
strategy (('lazy', 'raiseload'),)`。正确值是 `"raise"`。

### 6. 一个字的正文都没产出时仍以「成功」收尾

模型只回 thinking（`stop_reason="end_turn"`）或直接 refusal 时，循环照常
break、`truncated=False`、`tool_calls` 为空——前端把一份空白报告标成
「已完成」，DAG 上 writer 节点从未 activate，没有任何错误提示。

加 `produced_text` 标记 + `empty_response` 错误事件。

### 7. URL 建源真正抓取（另一个 agent 交的活）

新增 `app/services/fetcher.py`（277 行）+ 66 个测试。选型 httpx + trafilatura：
实测 HtmlParser 提出来的 Wikipedia 页面含 6 处导航噪音（「Jump to
content」「Main menu」），trafilatura 0 处——**导航文案进 embedding 会
直接污染检索**。

SSRF 防护：手动跟重定向 + 每跳复检，`ipaddress.is_global` 拦内网
（含 169.254.169.254 云 metadata）。实测 httpx 默认 `follow_redirects=True`
会一路跟到底，能读出内网内容。

## 两条方法论教训（已写进 AGENTS.md §7.5）

**1. 读源码下结论不可靠。** 我认定「FastAPI 的 yield 依赖在流式响应开始
前就关闭」，还专门读了 `routing.py:147-151` 当证据。实际FastAPI 0.118.0
把这个行为当 bug revert 了（release notes 原话举例的就是 SSE 拿不到 DB
session）。我读错了 stack——默认 `scope="request"` 的依赖挂的是**外层**
`request_stack`，外层在响应发完才关。

**先写实测脚本验，别只读源码。** 用 TestClient 跑一次完整 ASGI 栈，
三次真实 SQL 查询全部成功，才算确认。

**2. 变异测试要挑对场景。** 见上面 StaticPool 那条。

## 没修的

1. **中间口语粘进正文**——模型边调工具边说的话会被前端累加进最终报告。
   **这是前端问题**：后端语义是对的（那确实该给用户看），前端可以只累加
   `writer` 节点的 delta。留给 UI 会话。
2. **`run_agent` 145 行**（103 行有效代码，超项目 50 行上限两倍）——要拆出
   节点编排 / 工具分发 / 收尾三块，结构性重构建议单独一批。
3. **`DateTime(timezone=True)` 在 SQLite 上返回 naive**——今天没代码比较
   它所以没爆，但 sources 会进研报引用与时间线。
4. **向量与业务数据跨两条连接写入，无原子性**——摄取时可能一半切片有向量
   一半没有，而 status 已写成 indexed。
5. **`I2` FK pragma 只挂在 app.db.engine 上**，向量 engine 那条连接没开。

---

# 🔴 W2 Day 11 完成（Citation Builder + 本地检索接进 agent）

## 进度

W1 全完成，W2 Day 9 + 10 + 11 完成。**332 tests 全绿**（Day 10 结束时 296）。
mypy strict 36 文件零问题，ruff 零告警。

## 这一轮把什么接上了

Day 9/10 建好的切片 / 向量 / BM25 索引，在 Day 11 之前**查询侧一个都调不到**——
`run_agent` 只认 `tavily_search`，用户上传的 PDF 完全没进回答。现在闭环了：

    上传 PDF → 摄取建索引 → 用户提问 → agent 调 local_search
      → 混合检索命中切片 → Citation Builder 编 [n] 号
      → 模型据此写作并标引用 → 前端拿到 reference 事件渲染角标

## 新增文件

| 文件 | 作用 |
|---|---|
| `app/services/citation.py` | `ReferenceTable`（编号分配器）+ `render_evidence` + `citation_rules` |
| `tests/test_citation.py` | 19 条，编号与渲染 |
| `tests/test_local_search.py` | 11 条，工具接线与私域隔离 |

## 实测结论（本轮踩到的坑）

### 1. 引用编号必须跨多次工具调用稳定

模型完全可以连续调两次 `local_search`（「先查财务数据，再查产品规格」）。
如果每次调用各自从 1 开始编，正文里第一段的 `[1]` 指向财务数据、第三段的
`[1]` 却指向产品规格——**而且不会报任何错**，因为 `[1]` 一直是合法字符串，
只是指错了地方。症状是「用户点角标跳到的原文莫名其妙」。

所以 `ReferenceTable` 按 chunk_id 记账：已发过号的复用，新切片才取下一个号。
顺带解决去重——同一切片被两轮召回时不占两个号。

放在 `ToolContext` 里由 agent 循环持有，**不放模块级全局**：SSE 并发时
两个请求会互相串号。

### 2. ⚠️ 我读错了 FastAPI 源码，session 方案整个是错的

**这一条最重要，因为它是「以为自己验证过了」。**

CR 指出 `_stream` 自己开的 session 绕过了 `dependency_overrides`（`conftest`
的首要约定就是测试绝不碰开发库）。我确认了这点，但**对成因的判断搞反了方向**，
于是写了 `asynccontextmanager(get_session)()` 并在 docstring 里论证「这样
override 就能换掉」——实测证明 override 根本没被调用。

真正的事实（用 TestClient 跑完整 ASGI 栈实测，不是读源码猜的）：

```
dep OPEN → gen yield0 query=1 → yield1 query=1 → yield2 query=1
→ gen done → dep CLOSED → CLIENT 收到全部 chunk
```

**端点注入的 session 在整个流期间完全可用**，三次真实 SQL 查询都跑通了。

错在哪：`routing.py:147-152` 有两层 `AsyncExitStack`——

```python
async with AsyncExitStack() as request_stack:      # 外层
    scope["fastapi_inner_astack"] = request_stack
    async with AsyncExitStack() as function_stack:  # 内层
        response = await f(request)
    await response(scope, receive, send)            # ← 只有内层在此之前出栈
```

内层确实早关，但 `Depends()` 默认 `scope="request"`，依赖挂的是**外层**
（`dependencies/utils.py:664-667`：`use_astack = request_astack`），外层在响应
发完才关。只有显式 `Depends(scope="function")` 才早关。

**FastAPI 0.118.0 把「yield 依赖提前关闭」当 bug revert 了**，release notes
的原话举的例子就是这个场景：

> if you had a database session in a dependency with `yield`, the
> `StreamingResponse` would not be able to use that session while streaming data
> because the session would have already been closed

本项目装的是 **0.142.2**（不是 pyproject 里写的 `>=0.141` 的某个旧版）。

**教训**：读源码看到「某个 stack 在某行之前出栈」就下结论，是把两件事混了。
「内层 stack 早关」和「依赖挂在内层」是两回事，后者才是关键。改之前先写个
TestClient 实测脚本，10 行代码能验的事不该靠读源码推断。

最终方案就是**用端点注入的 `db`**——它走 `Depends()` 求解，override 才生效。
`tests/test_research_router.py` 里有两条测试守着这个：
`test_agent_gets_the_override_session`（拿到的是不是测试库那个对象）与
`test_agent_session_is_usable_during_stream`（生成器里能不能真的执行查询）。

**连接占用仍然存在**（db 活满 30-60 秒，pin 住池里一个连接）——那是
`scope="request"` 的既定行为，不是 bug。`MAX_CONCURRENT_STREAMS = 4` 是兜底。
上量前要改的话，方向是「每单位工作一个 session，跨边界只传 ID」
（tiangolo 与 YuriiMotov 在两个 issue 里指向同一个方向）。

### 3. jieba + BM25 的 OR 语义让「无关查询」照样有命中

以为「完全无关的词」是零命中，实际不是：

```
tokenize('完全无关的词') -> 完全 无关 的 词
tokenize('营业收入')    -> 营业 收入
```

BM25 查询串用 `OR` 连接所有词（Day 10 的设计，见 `bm25.py` 模块 docstring），
所以「的」「词」这类单字照样命中语料。要真的零命中只能用单个乱码词
（`zzzqqqxyz`）。写零命中测试时必须先验分词结果，不能凭直觉造词。

### 4. 前端早就有 `Citation` 契约了，别另立一套

`apps/web/app/(dashboard)/explore/mock.ts` 里已经定义了：

```ts
export interface Citation {
  id: number
  sourceTitle: string
  url: string
  date: string
}
```

`InspectorDrawer.buildCitationPayload` 直接吃这个形状。第一版后端发的是
`n` / `title` / `source_id`，对不上——前端得写一层转换才能用，而两边字段名
不一致时那个转换迟早会漏。现在 `Reference.to_citation()` 同时给两种命名
（`n` + `id`、`title` + `sourceTitle`），后端内部的检索语义用前者，
前端契约用后者。`tests/test_citation.py` 里有 5 条测试锁住这个对应关系。

`url` / `date` 这轮没给：本地资料是上传的 PDF，没有 URL 也没有发表日期
（`Source` 上只有 `created_at`）。前端只用来显示，缺了不会崩——但**编一个
日期会骗用户**，所以宁可不发。

### 5. 端到端冒烟第一次写错了，两次都是测试的问题不是代码的问题

- **PDF 中文提取成了 `···`**：造 PDF 时用了 `insert_text` 的默认字体，
  没有 CJK 字形。换成英文内容或 `insert_textbox` + 支持 CJK 的字体。
- **三个查询返回顺序完全一样**：一开始把三段内容用 `\n\n` 拼起来，
  总共 157 字 < `CHUNK_SIZE=512`，整份文档只切出 **1 片**。
  1 个候选当然排不出差异——这不是排序坏了，是根本没得排。

教训：**冒烟测试的样本必须先验证它能触发被测的那条路径**。
第一次跑出来「三个查询结果一样」时，先怀疑样本构造，再怀疑代码。

## 设计决策

| 决策 | 理由 |
|---|---|
| 编号从 1 起，且由 `ReferenceTable` 统一分配 | 让模型自己编号必然错配；详见上文实测 1 |
| `references` 返回**全量表**而非本轮增量 | 前端要的是整张映射表。第二次调用返回 `[1,2]` 是对的——第一片仍占 1 号 |
| 证据块给完整正文，引用表只给 120 字 excerpt | 模型要看确切措辞才能引用；全放进 SSE 帧会膨胀（8 条 × 500 字 ≈ 4KB） |
| `citation_rules` 显式写死「只能引用 [1]~[N]，严禁编造」 | 模型默认倾向是看到数字就顺手标一个。少了这段编造引用率明显上升 |
| 上界取 `table.all` 长度而非本轮新增数 | 模型可能第三轮才首次用工具，拿本轮号数当上界会漏掉前两轮 |
| `available_tools(has_local=False)` 摘掉 local_search | 没数据库连接时它必然执行不了；模型看不到就不会浪费一轮去调它 |
| 工具顺序固定按 `ALL_TOOLS_NAMES` 声明序 | `set` 迭代顺序随 PYTHONHASHSEED 变，会让 prompt 缓存失效 |
| 引用字段名对齐前端既有 `Citation` | 前端 `mock.ts` 已有 `{ id, sourceTitle, url, date }`，`InspectorDrawer.buildCitationPayload` 直接吃它。**另立一套字段名就得在前端多写一层转换，而那个转换迟早会漏**——WORKLOG 里本来就挂着这条警告 |

## 变异测试结果

| 变异 | 失败数 | 说明 |
|---|---|---|
| 编号不续编（每次从 1 重来） | 10 | 跨调用稳定性被守住 |
| `local_search` 传 `user_id=0`（去掉私域过滤） | 5 | 会漏别人的资料，被守住 |
| 证据块只给 excerpt 不给全文 | 1 | `test_evidence_full_body_not_excerpt` |

## 端到端实测输出

真实 3 页 PDF → 摄取出 3 片（页码分布 `[1,2,3]`）→ 三个查询各自命中正确的章节：

```
=== energy efficiency 与 Hopper 的差距  命中 3 条
  p1 向量+BM25 :: Section 1. NVIDIA Blackwell raises datacenter energy efficie
=== H200 的实测 QPS 是多少            命中 3 条
  p2 向量+BM25 :: Section 2. H200 measured inference throughput is 100000 QPS
=== quarterly revenue 增长多少          命中 3 条
  p3 向量+BM25 :: Section 3. Quarterly revenue reached 3.21 billion USD
```

---

# 🔴 W2 Day 10 完成（混合检索已通）

## 进度

W1 全完成，W2 Day 9 + Day 10 完成。**296 tests 全绿**（W1 结束时 157）。

```
ruff    ✅
mypy    ✅ 35 source files
pytest  ✅ 296 passed
```

已推送到 origin/master（`ce7830c..78124dd`）。

| commit | 内容 |
|---|---|
| `3ae4549` | **fix**：补齐 RAG 依赖声明 |
| `fac9e5c` | BM25 全文检索（jieba + FTS5） |
| `78124dd` | 混合检索（RRF k=60） |

## ⚠️ Day 10 的实测结论（都是跑出来的，不是照文档）

### 1. SQLite FTS5 自带分词器对中文全不可用——必须 jieba 预分词

| 分词器 | 「能效」「营收」「算力」「功耗」 |
|---|---|
| `unicode61`（默认） | 整句当一个词，**0 命中** |
| `trigram` | 要求 ≥3 字符，**所有 2 字词 0 命中** |

2 字词恰好是中文技术词汇的主力。jieba 预分词后全部命中。
PRD §7.2 写的是 Postgres 的 `to_tsvector('simple')`，在 SQLite 上完全用不上。

### 2. contentless FTS5 不支持 DELETE

`content=''` 省存储，但实测报 `cannot DELETE from contentless fts5 table`。
重跑摄取必须能删旧条目，所以用普通 FTS5。

### 3. BM25 漏同义词、向量漏专有名词——混合检索不是可选项

jieba 把「营业收入」切成「营业 收入」，查「营收」交集为空，一条命中不了
（2 字滑窗也救不了：原文滑窗是「业收」不是「营收」）。这类靠向量兜。

反过来问「H200 的实测 QPS」，BM25 靠专有名词命中、向量排第二——靠 BM25 兜。
端到端实测四组查询全对，这个互补关系是实测出来的，不是推演。

### 4. RRF 而不是加权平均

向量给 L2 距离（实测 0.0–1.3），BM25 给负分（−1 到 −10，**随语料规模漂移**）。
归一化参数（min-max 要看当次候选集、z-score 要看语料统计）在两路各自的
分布上都不稳定。RRF 只用排名，天然免疫量纲差异。

### 5. 虚表是运行时建的（Alembic 不认），入口必须收口

这个坑在 Day 10 **重复踩了三次**：`no such table: chunk_embeddings` ×2、
`no such table: chunk_fts`、`no such module: vec0`。全新部署上用户一份资料
都没摄取时必崩。现收口成 `ensure_index_tables()`，且 `bm25.search` /
`index_chunks` / `vectorstore.knn_search` 各自兜底。

### 6. `from x import f` 会让 monkeypatch 失效

导入时绑定了函数对象，patch 模块属性对它无效。`retriever.py` 改成
`embedder.embed_texts(...)` 模块级调用。**写测试打桩时要记住这条。**

## Day 10 的设计决策

1. **jieba 而非纯向量**——理由见实测 1
2. **RRF k=60**——PRD §7.1 指定值
3. **BM25 索引在「没有向量」的分支之前建**——全文检索不依赖嵌入服务，
   没配 key 时照样能用。只被 `vectors is None` 挡住的话，未配置嵌入的
   部署只剩空的那一路，等于没建索引
4. **`shared_db` 测试 fixture**——业务表与向量索引必须在**同一个** SQLite
   文件里，否则 `source_ids` 的过滤子查询永远查不到行。症状是「索引明明
   有数据却一条都检索不到」
5. **`retr...da` (PRIVATE_URL) `bm25.py` 的 `tokenize` 丢掉无字母数字的 token**——
   纯标点（`，。%`）在 FTS5 里是分隔符，留着只会让 MATCH 表达式变脏

### 变异测试（确认测试真在保护设计）

- 去掉 `source_ids` 过滤 → **3 个测试失败**（泄露别人的 chunk）
- 去掉 BM25 融合 → **2 个测试失败**

---

# W2 Day 9 完成（RAG 摄取管线已通）

## 进度

W1 全部完成（单 agent + tool calling + SSE）。W2 Day 9 完成：RAG 摄取管线
四步（解析 → 切片 → 嵌入 → 落库）已端到端跑通，HTTP 端点已就绪。

```
ruff    ✅ All checks passed
mypy    ✅ no issues found in 33 source files（strict）
pytest  ✅ 264 passed（W1 结束时 157）
```

## 新增文件

| 文件 | 行数 | 职责 |
|---|---|---|
| `app/models/source.py` | 180 | Source / DocumentChunk / SourceType / SourceStatus |
| `app/services/vectorstore.py` | 190 | sqlite-vec 接入：建表、写入、KNN 检索 |
| `app/services/parser.py` | 140 | PDF / HTML / 纯文本三个解析器 |
| `app/services/chunker.py` | 115 | 512 字切片 + 偏移量定位 |
| `app/services/embedder.py` | 130 | 嵌入调用、批处理、维度校验 |
| `app/services/ingest.py` | 180 | 四步编排 + 状态机 + 失败落库 |
| `app/services/storage.py` | 75 | 上传文件落盘 |
| `app/gateway/sources.py` | 200 | 6 个 HTTP 端点 |
| `app/schemas/source.py` | 77 | 请求/响应模型 |
| `alembic/versions/500a268181fc_*.py` | — | 建 sources / document_chunks |

## ⚠️ 接续开发必读：本次的实测结论

### 1. 嵌入走阿里云百炼，不走 OpenAI 官方

**OpenAI 官方这条路走不通**（实测）：

- `https://platform.openai.com` 屏蔽中国大陆 IP
- 开通后 429 `credit_balance_exhausted`——key 有效但余额为 0
- OpenAI **只收境外信用卡**，支付宝/微信/银联都不行

**百炼能用**（实测）：OpenAI 兼容端点，支付宝可付，新用户送 100 万 token
（90 天有效）。单价 0.0005 元/千 token，一份 50 页研报约 **2 毛钱**。
实测 4 条文本 0.32 秒，跨语言检索正常（中文查询命中中文内容，英文查询也能中）。

配置全走 `.env`，换服务商不改代码：

```
EMBEDDING_API_KEY = "sk-..."          # 百炼的 key
EMBEDDING_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
EMBEDDING_MODEL = "text-embedding-v4"
```

**tokenPlus 查过了，不行**：`/embeddings` 端点存在但模型广场「向量」分类是 0，
没有可用的嵌入模型。

### 2. 百炼的 text-embedding-v4 必须显式传 dimensions

不传时默认返回 **1024 维**，与索引表的 1536 不符 → `DimensionMismatchError`。
显式传 `dimensions=1536` 才行（实测 1536 / 1024 都支持）。

这正是维度校验的价值：没这道校验会把 1024 维向量写进 1536 维的 vec0 表，
然后**检索结果全是乱码但不报任何错**。

### 3. sqlite-vec 的加载：唯一可行入口是 `async_creator`

**不能用 SQLAlchemy 的 `connect` 事件加载扩展**——这是本次最大的坑。

事件回调里拿到的 `dbapi_conn.driver_connection` 是 `aiosqlite.Connection`，
它的 `enable_load_extension` 是 **async** 方法。同步回调里调用只造一个协程对象
就被丢弃，扩展**静默不加载**，之后所有 `vec_*` 调用报
`no such function: vec_version`，且加载期一句错都没有。

唯一可行入口：

```python
create_async_engine("sqlite+aiosqlite://", async_creator=lambda: _open(path))
```

### 4. vec0 返回的是 L2 欧氏距离，不是余弦距离

实测（单位向量，真实 cos=0.5304）：`distance=0.9692`，而 `1-cos=0.4696`、
`√(2-2cos)=0.9692`——与 L2 **逐位吻合**。

排序不受影响：单位向量下 `L2 = √(2-2cos)` 是 cos 的单调递减变换。
但**阈值不能跨度量套用**——「distance < 0.5」在两种度量下含义完全不同。
换 pgvector 时记得改。

由 `tests/test_vectorstore.py::test_distance_is_l2_not_cosine` 锁住。

### 5. 嵌入不是确定性的

同一段文本两次调嵌入服务，向量有 ~1e-3 量级浮点差异（累加顺序不同）。
实测中三个切片两两余弦接近时（0.4679 vs 0.4485），这点噪声足以让 top1/top2 互换。

**不要断言排名的绝对值**，只断言「正确答案在前列」。真实场景 top50 召回
再 rerank，单条抖动不影响结果。

### 6. 切片：不要传 PRD 那串自定义 separators

PRD §4.1 写的 `["\n\n", "\n", "。", ...]` 在「中文研报段落 + chunk_size=50」
时会切出一片孤立的 `。`——单字符片变成垃圾 embedding。

注意这不是普遍现象（换尺寸/换文本都不出现），但默认配置没这个问题。
用默认配置还有个好处：**overlap 看起来才正常**。自定义 separators 把标点留在
片头，会吃掉重叠窗口（实测 `test_overlap_repeats_text_between_chunks` 失败）。

### 7. SQLite 默认不执行外键——踩过

`PRAGMA foreign_keys` 默认 **0**。不开它，模型里所有 `ondelete="CASCADE"`
形同虚设：删用户会留下一堆孤儿 `sources` / `document_chunks`，而且**测试不会报警**
（我第一个 CASCADE 测试就是这么「通过」的，实际什么都没删）。

已在两处打开：`app/db.py::_enable_sqlite_foreign_keys`（挂 connect 事件）
与 `tests/conftest.py::db_session`。对 Postgres 是 no-op，不用分支。

### 8. pytest 的 faulthandler 插件与 pymupdf 在 Python 3.14 上冲突

`-p no:faulthandler` 写进了 `pyproject.toml` 的 `addopts`。不加的话
一 import pymupdf 就段错误，且崩在 C 扩展初始化期——faulthandler 打的栈
也定位不到根因。它本来只在崩溃时打栈，对我们没净收益。

同时加了 filterwarnings 规则忽略 SWIG 的 `has no __module__ attribute`。

### 9. pymupdf 的实测行为（1.28.2）

| 场景 | 行为 |
|---|---|
| 损坏文件 | `FileDataError` |
| 加密文件 | `needs_pass` 为真；直接读报 `ValueError: document closed or encrypted` |
| 空白页 | `get_text()` 返回空串，跳过即可（不是错误） |
| 全无文字 | 要单独报「需 OCR」，不能含糊成「解析失败」 |

`Document` 声明成 `Iterable[Never]`（没写 `__iter__` 签名），用
`range(doc.page_count)` + `doc[i]` 绕开可迭代协议，mypy 就自洽了。

### 10. 偏移量靠 `str.find` 顺序扫描定位

langchain 的 `create_documents` 不返回字符偏移，而引用高亮必须要有。
实测（中文/无分隔符连续字符/中英混排/重复段落）每个 chunk 都能在原文定位成功。

必须用**带 cursor 的顺序 find**，朴素 `find` 会让重复段落全部贴到文首。

### 11. `python-multipart` 是 FastAPI 收上传的硬依赖

不装的话 FastAPI 启动即报错。已加进 `pyproject.toml`。

## 设计决策（勿推翻）

1. **向量库用 sqlite-vec，W3 换 pgvector**——dev 环境无 Docker、5432 未开。
   向量逻辑全部收口在 `app/services/vectorstore.py`，换库只改这一个文件。
   模型/parser/chunker/embedder/ingest 都不碰数据库细节。
2. **向量不进 ORM 表**——存 `document_chunks`（正文，给全文检索）+ `chunk_embeddings`
   （vec0 虚拟表）两处，靠 `document_chunks.id == chunk_embeddings.chunk_id` 对齐。
   vec0 表没有列能放业务字段。
3. **摄取状态逐阶段 commit**——前端要显示「正在切片 142/180」，状态存内存
   刷新就没了。多几次写换可观测进度。
4. **摄取是后台任务，不阻塞 HTTP**——50 页 PDF 要 30-60 秒。端点只建源就返回 201，
   前端轮询状态端点。与 research 的 SSE 是两套机制（摄取不需要逐 token 反馈）。
5. **失败要落库**——`status=failed` + `error_message`，不能只抛异常。
   否则用户只看到请求超时就结束，无从重试。
6. **解析器抽不出文字时抛错，不返回空串**——空串会让摄取「成功」入库，
   然后检索时静默地什么都搜不到。扫描件单独报「需 OCR」。
7. **上传文件名用 uuid4 + 净化后的扩展名**——绝不用用户上传的原名
   （可能有 `../`、中文、超长、撞车）。
8. **越权一律 404 不是 403**——403 等于确认了这个 id 存在，是信息泄露。

## 已知缺口（不是设计，是没做）

1. **`DELETE /sources/{id}` 不清原始文件与向量**——向量表没外键，DB 级联删不到。
   当前用量下不影响正确��（检索按 chunk_id 回查，查不到就丢弃），但要补。
2. **URL 建源只登记不抓取**——抓取要接 Tavily/Firecrawl。
3. **没有任务队列**——进程重启会丢正在跑的摄取（status 卡在中间态）。
   YAGNI：先这样，真需要时接 Redis + worker。
4. **没有 rerank**——PRD §8 的 cross-encoder 重排。当前 top-50 直接给模型，
   精度够用，要提精度再上（`_rrf_fuse` 已按 PRD 预留 top-50 召回）。
5. **`Source.chunks` 的 lazy='selectin'** 会让每次查 source 都带出全部切片。
   列表页 `list_owned` 用不上，应该改成 `lazy='raise'` 或 `raiseload` + 显式查询。
6. **SSE 长连接 pin 住一个 DB 连接 30-60 秒**——`Depends()` 默认
   `scope="request"`，依赖活满整个响应（见 Day 11 实测 2，这是既定行为不是
   bug）。连接池默认 `pool_size=5`，4 条并发 SSE 就占掉 4 个。
   `MAX_CONCURRENT_STREAMS = 4` 是兜底，所以**当前不会**打穿池子。
   上量前要改的话方向是「每单位工作一个 session，跨边界只传 ID」
   ——不要改成 `Depends(scope="function")`，那会让流跑到一半 session 就关了。
7. **`SYSTEM_PROMPT` 是写死的常量，还在指示模型调 `tavily_search`**，
   完全没提 `local_search`。私有资料部署（没配 Tavily key）下，
   `available_tools()` 摘掉 `tavily_search` 后模型会被指示去调一个它看不到的
   工具，而 `local_search` 无人提及。**要改成按实际工具集动态拼接。**

## 下一步

**后端**（本会话可做）：
1. `run_agent` 145 行重构——拆节点编排 / 工具分发 / 收尾三块
2. `DateTime(timezone=True)` 在 SQLite 上返回 naive——sources 会进引用与
   时间线，早晚要比较
3. 向量与业务数据跨两条连接写入，无原子性（摄取可能一半切片有向量一半
   没有，而 status 已写成 indexed）
4. FK pragma 只挂在 app.db.engine，向量 engine 那条连接没开

**前端**（UI 会话在做，勿抢）：
- 中间口语粘进正文——前端只累加 writer 节点的 delta 即可
- explore 页消费 `reference` 事件，角标点击接真实 chunk

**规则**：`AGENTS.md §7.5` —— 每写完一批代码走「质量门 → 测试 → CR」，
CR 发现问题修完重跑并复审。含两条实证教训：读源码下结论不可靠、
变异测试要挑对场景。

---

## 历史：W2 Day 12（explore 页接线 + URL 抓取）—— URL 抓取已完成

Day 11 的 Citation Builder 与本地检索已完成（见上），剩下的：

1. **explore 页接上后端流**——现在 `explore/page.tsx` 还是 `setInterval` +
   硬编码字符串模拟整个流程。要改成 `fetch` + `ReadableStream` 消费
   `POST /research/ask`，并处理新加的 `reference` 事件
2. **点击角标跳转原文**——`Citation` 契约已对齐（见上），但
   `InspectorDrawer` 里的 `extracted_facts` / `relevance_score` 现在是
   硬编码，要换成 `reference` 事件里的真实字段
3. **URL 抓取**——`POST /api/v1/sources/url` 现在只登记不抓取，
   要接 Tavily extract 或 Firecrawl
4. **rerank**（PRD §8）——可选，先不做

⚠️ 前端 citation 契约已对齐到 `mock.ts` 的 `Citation`（见 Day 11 实测 4），
Day 12 改前端时直接用后端发的字段，不要再改后端字段名。

---

## W2 Day 10：混合检索（已提交）

### 实测结论（都是跑出来的，不是照文档）

**1. SQLite FTS5 的分词器对中文全不可用**

| 分词器 | 「能效」「营收」「算力」「功耗」 |
|---|---|
| `unicode61`（默认） | 整句当一个词，0 命中 |
| `trigram` | 要求 ≥3 字符，**所有 2 字词 0 命中** |

2 字词恰好是中文技术词汇的主体。必须 **jieba 预分词 → FTS5 存词**
（`app/services/bm25.py`）。装好后全部命中。

**2. 不能用 contentless FTS5（`content=''`）**

实测报 `cannot DELETE from contentless fts5 table`——它不支持 DELETE，
而重跑摄取必须能删旧条目。

**3. RRF 是对的选择，不是因为「业界流行」**

两路量纲完全不同：向量给 **L2 距离**（实测 0.0-1.3），BM25 给**负分**
（−1 到 −10，且随语料规模漂移）。加权平均要先归一化，而归一化参数
（min-max 要看当次候选集、z-score 要看语料统计）在两路各自的分布上都不稳定。
RRF 只用**排名**，天然免疫量纲差异。

**4. 混合检索不是可选项**

端到端实测：
- 问「H200 的实测 QPS」→ BM25 靠**专有名词 H200** 命中
- 问「股价最高到过多少」→ BM25 **完全没命中**（`b-`），全靠向量兜
- 问「revenue grew」→ BM25 命中不了「营业收入」（jieba 切出「营业 收入」，
  与「营收」交集为空）

**向量漏专有名词，BM25 漏同义词。** 两路都要。

### 踩过的坑

| 坑 | 说明 |
|---|---|
| **虚表要 ensure，已漏三次** | 虚表运行时建（Alembic 不认），原先 4 个调用点各自 ensure，结果报过 `no such table: chunk_embeddings` / `chunk_fts` / `no such module: vec0`。现收口成 `ingest.ensure_index_tables()` 单一入口，且 `bm25.search` / `index_chunks` / `knn_search` 各自兜底 |
| **`shared_db` fixture** | 业务表与向量索引必须在**同一个** SQLite 文件里。分两个库的话 `source_ids` 的过滤子查询永远查不到行——症状是「索引明明有数据却检索不到」 |
| **`from x import f` 打桩无效** | 函数对象在导入时绑定，monkeypatch 模块属性对它没用。改用 `embedder.embed_texts(...)` 调用形式 |
| **RAG 依赖装漏** | `pymupdf` / `langchain-text-splitters` / `sqlite-vec` 当初用 `uv pip install` 装的，没写进 `pyproject.toml`。`uv sync` 会卸掉它们——开发机正常，干净环境 import 失败。已补 |

### 变异测试（确认测试真在保护设计）

- 去掉 `source_ids` 过滤 → **3 个测试失败**（泄露别人的 chunk）
- 去掉 BM25 融合 → **2 个测试失败**

---

## 历史：W1 Day 4 完成（单 agent + tool calling + SSE 全链路已通）

### 已提交（W1 Day 4 时的状态）

| commit | 内容 |
|---|---|
| `4d877a0` | **LLM client 单例 + Tavily 配置**（`app/services/llm.py`） |
| `c4bae5c` | **工具层：`tavily_search` + `dedup`**（`app/services/tools.py`） |
| `7b6784b` | **agent 主循环 + 事件契约 + 打字机切片**（`agent.py` / `stream.py`） |
| `90756fc` | **SSE 端点 `POST /api/v1/research/ask`**（`gateway/research.py`） |

前端 3 个 commit（`d584dbe` / `a260805` / `2b4027c` 等）把 explore 页接到上面
这个端点上，已实跑验证。


### 质量门（全绿）

```
ruff    ✅ All checks passed
mypy    ✅ no issues found in 24 source files（strict）
pytest  ✅ 157 passed
```

## ⚠️ 接续开发必读：本次会话的实测结论

这些是**跑真实模型测出来的**，不是从文档推断的。重写相关代码前先看这段。

### 1. LLM 服务商是「llmapi.pro 中转站」，不是 Anthropic 官方

`ANTHROPIC_BASE_URL=https://llmapi.pro`。它的行为和官方 API 有两处**实测差异**，照官方文档写会踩：

| 现象 | 官方 API | 中转站实测 |
|---|---|---|
| 文本流式粒度 | 逐 token | **整段缓冲**，243 字符只给 1 个 `text_delta` |
| `model_dump()` 带 null 字段 | 严格模式会拒 | **接受**（`citations: null` 照发不误） |

所以后端的打字机效果是**自己切的**（`TextSlicer`，见下），不是依赖上游分块。

`exclude_none=True` 仍然保留——理由从「不这样会 400」改成「直连官方 API 更保守，当前零成本」。

### 2. Sonnet 5 会返回 `thinking` block，且必须原样回传

实测返回结构：`['thinking', 'text', 'tool_use']`。

- **必须回传**：thinking 里带 `signature`，改动会被上游拒
- **绝不能发给用户**：前端只要研究结论，原始 CoT 不该出站

代码里 `messages.append({"role": "assistant", "content": result.content})` 就是干这个的，`agent.py` 顶部 docstring 写了完整理由。**这条约束由 `tests/test_turn_request.py` 守护**（12 个测试专门测 `_run_turn` 的请求构造与响应解析）。

### 3. `_run_turn` 是最脆的一环，别改它不测

它是 agent 与 SDK 之间**唯一**的接缝（`agent.py:292` 附近）。行覆盖率看不出来——大部分测试用 `monkeypatch` 把它替换掉了，coverage 会把「import 期执行过」算成已覆盖。

代码审查时用**变异测试**发现的：把 signature 字段删掉，125 个测试照样全绿。

### 4. `_is_word_char` 必须限定 ASCII

修「`100,000` 被劈成两半」时用了 `isalnum()`——但**中文的 `isalnum()` 也是 `True`**，导致所有中文标点的切分全被跳过，退化成硬切，连 `QPS` 都劈成 `Q` + `PS`。

现在有 `isascii()` 守卫，且 `LONG_TEXT` 测试数据里同时含中文和千分位。

**教训**：修 bug 的测试必须覆盖**受影响的主路径**（中文），不能只覆盖触发场景（数字）。

## 本次新增的代码约定

| 位置 | 约定 |
|---|---|
| `services/llm.py` | client 单例用 `@lru_cache`，配 `clear_client_cache()` 供测试重置。缺 key 抛 `LLMNotConfiguredError`，不返回 `None` |
| `services/tools.py` | 工具执行失败**不抛异常**，返回 `ok=False`。`except Exception` 分两类：网络类给「外部服务不可用」，其余给「工具内部出错，请勿重试」——代码 bug 不能报成用户参数问题 |
| `services/stream.py` | 事件用 JSON envelope（`{"type": "...", "v": {...}}`）而非 SSE 原生 `event:` 行，消费端一条 `split("\n\n")` + `JSON.parse` 就能统一分发 |
| `gateway/research.py` | 并发上限 4（信号量），超了直接 503 不开流。`X-Accel-Buffering: no` 防 Nginx 缓冲 |
| `services/stream.py::TextSlicer` | 标点贪心切片，窗口放宽到 `chunk_size * 1.5`，搜索范围是窗口内**最靠后**的标点。粒度 24 字 |

## 未完成 / 待办

1. **`tool_call` 事件驱动 InspectorDrawer 的 Input/Output/Prompt/Tabs** —— 现在 Tools 标签页有数据了，另外三个标签仍共用同一份 `jsonText`
2. **`ToolCall` 类型与后端 `ToolCallEvent` 的映射**已做，但 citation 溯源（`Citation`）还没接 SSE
3. **`apps/api/scripts/dev_login.py`** —— 调试脚本（生成 JWT），未提交也未 gitignore
4. **7 个 commit 未推送** —— 代理（APNetwork）需用户手动启动
5. **Day 5-7**：W1 Demo + 前端剩余接线

## 下一步（当时的，已完成）：W1 Day 5-7 或 W2

- **W1 收尾**：citation 溯源接 SSE、`DAG_STATS` 静态 import 清理、W1 Demo
- **W2（重头）**：RAG 管线（PyMuPDF / Trafilatura / chunking / embedding）+ 多 agent 编排

### W2 换 LangGraph 的判断依据（已与用户确认）

现在手写的是「单循环」，`agent.py` 里 `_run_turn` 那 44 行胶水是唯一能被框架替代的部分。`tools.py`（365 行）和 `stream.py`（221 行）LangGraph 完全用不上——前端要的事件格式不是 LangGraph 的回调格式。

**W2 换的理由**：状态在节点间传递、条件边、断点续跑、并行调度。这些手写就是几百行状态机。`prd/multi-agent-design.md` 已定义好 `ResearchState`。

**换的时候保留**：`tools.py` 整个、`stream.py` 整个、`llm.py` 的 client 单例可复用。只重写 `agent.py` 的循环部分。

⚠️ **W2 的一个已知冲突**：现在 `NodeTracker` 强制「任一时刻只有一个节点 active」（前端 `AgentDAG` 用 `findIndex` 算高亮轨道位置）。LangGraph 并行调度会天然产生多个 active，**这个约束要先解决**。

## 目录结构现状

```
apps/api/app/
├── __init__.py
├── config.py           Settings（pydantic-settings + SecretStr + lru_cache）
├── db.py               engine + SessionLocal + get_session + check_db_health
├── main.py             仅装配：建 app、lifespan、CORS、include_router
├── gateway/            HTTP 边界
│   ├── health.py       /api/v1/healthz + /api/v1/readyz
│   ├── auth.py         /api/v1/auth/github/{login,callback} + /logout
│   ├── users.py        /api/v1/me
│   └── deps.py         get_current_user（cookie→JWT→User），CurrentUser 别名
├── models/             SQLAlchemy ORM
│   ├── base.py         Base(DeclarativeBase)
│   └── user.py         User + Account + Provider(StrEnum)
├── schemas/            Pydantic 响应模型
│   ├── health.py       HealthResponse
│   └── user.py         MeResponse
└── services/           业务编排
    ├── auth.py         OAuthProfile / LoginResult / get_or_create_user
    └── token.py        JWT 签发与校验

apps/api/alembic/       已接好，target_metadata = Base.metadata
apps/api/tests/         49 个测试，内存 SQLite 隔离
```

## 关键技术决策（勿推翻）

1. **API 前缀统一 `/api/v1`**——各router 自己声明 prefix，不在main.py 里统一加
2. **两层身份模型**（Auth.js 事实标准）：`users` 管「是谁」，`accounts` 管「从哪登录」。复合主键 `(provider, provider_account_id)`
3. **邮箱 unique + 自动关联**——OAuth provider 信任主邮箱（GitHub/Google 强制验证）。**若将来接入允许未验证邮箱的 provider，必须关掉 `get_or_create_user` 的第2 段查找**，否则账号劫持
4. **不建 repository 层**——2026 业界轻量化趋势，查询以 `@classmethod` 挂在模型上
5. **JWT payload 只放 user_id**，资料实时读库
6. **JWT 密钥与 OAuth secret 独立**——泄露后果不同
7. **state / PKCE verifier 存itsdangerous 签名 cookie**，不用 Redis（无状态 + 多worker 安全）
8. **不用 Authlib 的 `authorize_access_token`**——它依赖 `request.session`，与 argus 自己的 JWT cookie 方案打架。只用底层 `OAuth2Client` 生成授权 URL，token 交换用 httpx 直调 GitHub
9. **测试不用 respx**——TestClient 走 ASGI transport，respx 会拦掉 TestClient 自己的请求导致假 404。改用 `monkeypatch` 替换发 HTTP 的函数 + `dependency_overrides` 换DB session
10. **测试绝不用 `SessionLocal`**——用 conftest.py 的 `db_session` fixture（内存 SQLite），否则污染 dev 库
11. **鉴权失败只有一种 401 文案**——缺 cookie / 票据坏 / 用户已删全返回同一句。前端处理动作完全一样，区分开只会多写无用分支；顺带不向攻击者泄露失败原因
12. **登出只删 cookie，不撤销票据**——JWT 无状态，服务端不存 session。已抄走的 cookie 在 7 天内仍能调通接口。补救要加撤销名单（表或 Redis），当前不做：等真要「踢人下线」时再上

## 环境相关的坑

- **PyPI 网络不稳**：报 `Failed to connect` / `peer closed connection`。改用阿里云镜像：
  ```bash
  uv sync --extra dev --index-url https://mirrors.aliyun.com/pypi/simple/
  ```
- **`uv remove` 会连带卸载整个 dev extra**。改 pyproject 后用 `sed` 编辑 + `uv sync --extra dev`，不要用 `uv remove`
- **VS Code 报红（无法解析导入 sqlalchemy/itsdangerous）**：IDE 解释器没指对，代码本身没问题。命令行 `uv run pytest` 走 `.venv` 所以全绿，但 Pylance 用你指定的解释器找包，两套机制独立。
  - 已修（2026-10-09）：项目根 `.vscode/settings.json` 设了 `python.defaultInterpreterPath = "apps/api/.venv/bin/python3"` + `python.analysis.extraPaths = ["apps/api"]`。改完要 `Cmd+Shift+P` → `Developer: Reload Window`，Pylance 不会自动重载
  - **venv 唯一实体在 `apps/api/.venv`**（uv 在 apps/api 下建的）。排查时别在仓库根跑 `find . -name .venv` 再把结果当根目录的——那样 `find` 的 `.` 是 cwd，会误报成 `./.venv`。先 `pwd` 确认再解读
  - **局限**：`defaultInterpreterPath` 对「已存在的 venv」生效。删掉 `.venv` 重装后 VS Code 会忽略这项，仍需手动选一次解释器
  - `.vscode/` 被根 `.gitignore:8` 忽略（解释器路径机器相关，入库添乱），换机器要照 WORKLOG 重建
- **ruff 读 `.ruff.toml` 而非 `pyproject.toml` 的 `[tool.ruff]`**——两处配置要同步
- **已装依赖**：`sqlalchemy[asyncio]`、`aiosqlite`（dev extra）、`itsdangerous`、`types-authlib`（dev extra）。已移除 `types-pyjwt`（过时 stub，会把 `jwt.encode` 误标为返回 bytes）

## 凭据状态（.env 18 个 key 全部已填，不要在对话里贴值）

2026-10-09 复核：全部齐了，Day 3 无前置阻塞。

| 变量 | 状态 |
|---|---|
| `GITHUB_OAUTH_CLIENT_ID` / `GITHUB_OAUTH_CLIENT_SECRET` | ✅ 已填 |
| `GITHUB_OAUTH_CALLBACK_URL` | ✅ `http://localhost:8000/api/v1/auth/github/callback`（GitHub 后台 Redirect URI 已同步） |
| `JWT_SECRET_KEY` | ✅ 已填（64 字符） |
| `ANTHROPIC_API_KEY` | ✅ 已填（Day 3 用） |
| `ANTHROPIC_BASE_URL` | ✅ `https://llmapi.pro`（中转站） |
| 7 个 `ANTHROPIC_*_MODEL` | ✅ 已填（complex 走 `claude-sonnet-5`，default 走 `claude-haiku-4-5`） |

**坑**：`.env` 第 1 行 `GITHUB_OAUTH_CLIENT_ID = "xxx"` 的等号两边有空格。
pydantic-settings 走 python-dotenv 能容忍，功能正常；但 `grep '^\([A-Z_]*\)='` 这类
脚本会漏掉它。排查 env 时用宽松正则 `^\s*[A-Za-z_][A-Za-z0-9_]*\s*=`。

## 登录闭环（已完成 2026-10-09，未提交）

| 文件 | 内容 |
|---|---|
| `app/gateway/deps.py` | `get_current_user` + `CurrentUser` 别名 |
| `app/gateway/users.py` | `GET /api/v1/me` |
| `app/gateway/auth.py` | `POST /api/v1/auth/logout`（204，不校验登录态，幂等） |
| `app/schemas/user.py` | `MeResponse` |
| `tests/conftest.py` | 提上来共用：`api_db` / `client` / `github_state` |
| `tests/test_session_routes.py` | 11 个测试 |

真实 HTTP 已验证（uvicorn + curl）：无 cookie 401、坏 cookie 401、真票据 200、
登出后 `set-cookie` 带 `Max-Age=0; Path=/`。dev 库未被污染。

## 测试要求

新增功能必须配测试，沿用现有模式：
- DB 用 `db_session` fixture（内存 SQLite）
- 路由用 `api_db` fixture 做 `dependency_overrides`
- 外部 HTTP 用 `monkeypatch` 替换，不用 respx
- OAuth 相关请求要加 `follow_redirects=False`

## 本次会话的实测结论（重新开发前必读）

### 1. 中转站 llmapi.pro 的真实行为

不是照文档猜的，是实测的（`AsyncAnthropic(base_url=...)`）：

| 事实 | 影响 |
|---|---|
| **支持 tool calling**，`stop_reason: tool_use` | 可用 |
| **支持流式**，但会把 243 字符缓冲成 1 个 `text_delta` | 打字机效果必须后端自己补，已由 `TextSlicer` 承担 |
| 流式能收到 `input_json_delta`（工具入参增量） | 可用 |
| **模型返回 `thinking` block**（Sonnet 5 扩展思考） | 必须原样回传，见下条 |
| `model_dump()` 漏 `exclude_none` **不会 400**（中转站接受 `citations: null`） | 但仍保留 `exclude_none=True`：直连官方 API 更保守 |

**thinking + signature 是硬约束**：`signature` 是上游的防篡改签名，改一个字节下一轮就拒。
必须 `final.model_dump(exclude_none=True)` 原样回传进 messages；但**不能**转发给用户
（Anthropic 不建议向非受信端暴露原始 CoT）。这就是「不转发但必须存」的原因。

### 2. `tavily-python` 0.8.5

- `AsyncTavilyClient` 是真协程（`inspect.iscoroutinefunction` 为 True），不用自己包线程池
- 支持注入 `httpx.AsyncClient` 复用连接池
- 无 `py.typed`，已在 `pyproject.toml` 加 mypy override

### 3. 前端硬约束：任一时刻最多一个节点 `active`

前端 `AgentDAG` 用 `findIndex(n => n.lifecycle === 'active')` 算高亮轨道位置，
两个 active 会直接算错。`NodeTracker.activate` 里的 `assert` 是强制这个约束的，
不是装饰代码。

**W2 接 LangGraph 时会冲突**——并行调度天然产生多个 active，必须先解决。

### 4. 节点 id 会重复出现

实测模型「先说话再调工具」时，事件序列是：
`researcher → researcher → writer → researcher → writer...`
（同一个 `researcher` 出现 3 次）。

前端契约必须写死：**按到达顺序追加，不得按 id 去重**。

### 5. SSE 协议

单行 JSON envelope，不用 SSE 原生的多路 `event:`：

```
data: {"type": "delta", "v": {"node_id": "writer", "text": "..."}}

data: {"type": "done", "v": {"session_id": "...", "elapsed_ms": 5432}}
```

五类事件：`node` / `delta` / `tool_call` / `error` / `done`。

**开流后 HTTP 状态码改不了**——鉴权、参数校验都必须在开流前完成；
开流后的失败只能走 `error` 事件。

必须加 `X-Accel-Buffering: no`，否则 Nginx 会缓冲，SSE 攒成一坨最后吐出来。

### 6. 未解决 / 待办

| 事项 | 状态 |
|---|---|
| ~~`TAVILY_API_KEY` 未申请~~ | ✅ 已配（见顶部章节） |
| `stop_reason == "max_tokens"` 且同时有 tool_calls 时，`truncated` 标记走不到 | 已知 bug，未修（`agent.py`） |
| service 层引入了 logger | 与既有约定「logging 归 gateway」冲突，**待用户定夺** |
| 「打字机」无节奏控制 | `_slice_for_display` 是同步函数，片段同 tick 吐完 |
| `tool_call` 事件驱动 InspectorDrawer | 已做（前端 `bd4e232`） |
| W2 换 LangGraph | 保留 `tools.py`(365 行) / `stream.py`(221 行) / `llm.py` client 单例，只重写循环 |

### 7. 代码审查发现并已修的 bug（别再犯）

1. **`_is_word_char` 用 `isalnum()`，中文也算** → 所有中文标点切分失效，退化成硬切，连 `QPS` 都劈成 `Q` + `PS`。
   必须限定 `isascii()`。
2. **模块级 `_tool_results` 全局变量** → SSE 并发时两个用户的搜索结果互相污染。已改局部变量。
3. **`canonicalize_url` 遇畸形 URL 抛 ValueError** → 一条坏 URL 让整批 dedup 结果消失。
4. **截断计数 off-by-one**，且把「requested 裁掉的」和「字符预算裁掉的」混算 → 模型被告知错误数字。
5. **`RunState` 死代码**：加了 `'error'` 但从不赋值，已删。
6. **heredoc 在本环境会被 shell 截断**（含中文/长字符串时）→ 批量替换多次写坏代码。
   长文本改用 Edit/Write 工具。

### 8. 环境

- 后端 venv 在 `apps/api/.venv`，**不在仓库根**
- uvicorn 启动：`cd apps/api && uv run uvicorn app.main:app --port 8000`
- 调 GitHub API 需要代理 `HTTP_PROXY=http://127.0.0.1:62531`（APNetwork 未运行时不要设）
- `/tmp/jwt.txt` 等临时文件：`rm` 被 `dangerous-cmd-block` hook 拦，需手动删
