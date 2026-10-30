# 规格：修复 `llm_content_filtered` 误报 + 检索相关性下限

> 2026-10-23 立。writer 与 tester-spec 都只读这份规格，**不要看对方的产物**。

## 背景（已实测的事实，不要重新怀疑）

argus 报 `llm_content_filtered`（「请求被上游内容安全策略拦截，请调整问题措辞后重试」）。
**上游没有误伤。** 用完全虚构的等价负载复刻那次失败请求，连发 10 次全部通过；换真实标题、
换 50 条高密度个人字段、换多轮结构、换饱和引用表形态——全部通过。失败率 0/10。

真实成因是**检索侧没有相关性下限**。用户问「研究 iphone duo 对比国产折叠屏手机的质量」，
但该用户资料库里只有一份《北京市医疗保障信息平台公共服务子系统接口需求大全》。
`retriever.retrieve` 走向量 top50 + BM25 top50 经 RRF 融合后**直接取前 N 条，不管相关不相关**：

| 查询 | BM25 命中 | 向量 top1 distance | 召回 12 条去重后 |
|---|---|---|---|
| `iPhone 折叠屏` | 0 | 1.1437（cos 0.34） | **1 种内容**（全是「接口功能说明」） |
| `国产折叠屏 手机 质量 耐用性` | 23 | 1.1304（cos 0.37） | 4 种（全是「参保人手机 \| tel」） |
| `医保结算清单 接口` | 20 | 0.6521（cos 0.79） | 8 种，有真实内容 |

模型于是拿着「个人编号 / 参保人手机 / 身份证」当证据去回答手机质量对比，
拼出一个「个人资料字段表 + 手机对比」的畸形上下文，上游对这个上下文报了内容安全。

**上游返回的内容是结果，不是原因。** 报成「内容安全拦截」是误诊。

## 三项改动

### 第 1 项：检索相关性下限（`vectorstore.py` + `retriever.py`）

**距离上限**。（以下是最初的设想，最终值见 §1.1 与「第二轮」——阈值从
L2 0.89 改成了余弦距离 0.45。）

- 相关查询 top1 distance **≤ 0.6682**（cos ≥ 0.777）
- 不相关查询 top1 distance **≥ 1.1166**（cos ≤ 0.377）

实现要点：

- 阈值常量放在 `app/services/vectorstore.py`，命名 `MAX_RELEVANT_DISTANCE`。
  docstring 必须写明用的**哪个度量**、换 pgvector 要重新标定、标定依据。
- **过滤发生在 `knn_search` 内部**（返回前过滤超阈值的行），
  还是 `retriever._vector_recall` 里？——**放在 `knn_search` 内部**。
  理由：`knn_search` 是「向量库接入层」，语义上它就该只返回「够近的」。
  调用方 `retriever._vector_recall` 是唯一调用者（测试除外），所以对外行为只变这一处。
- **BM25 路也必须过同一个下限**（2026-10-23 修正：原规格写「BM25 路不设阈值」是错的）。

  实测反证：

  ```
  query='手机 质量 参数'
    向量召回 50 → 阈值后剩 0
    BM25 命中 50   ← 没设阈值
    融合后仍返回 50 条，无关切片照样进证据块

  query='编号 手机 结算'
    向量召回 50 → 阈值后剩 6
    BM25 命中 50   ← 没设阈值
    融合后仍返回 50 条，无关切片照样进证据块
  ```

  原因：BM25 的 MATCH 用 jieba 分词后的 token 做 **OR** 匹配
  （`bm25.py` 的 `match_expr = " OR ".join(...)`）。查询词里只要有**一个** token
  命中，切片就进候选。「手机」「参数」「结算」都能命中医保接口文档里的字段行。

  **只给向量路设下限，bug 没修好**——`retrieve` 仍返回 12 条无关切片，
  证据块照样被无关的「个人编号 / 参保人手机」填满。

  BM25 路拿不到「距离」，但 sqlite-vec 支持**带 `chunk_id IN (...)` 约束的 KNN 查询**，
  能返回任意指定 id 集合的真实距离。实测可行且距离值与无约束查询**逐位一致**：

  ```
  k=100: 请求 100 个 id → 返回 100 行, 命中 100/100
  约束查 id=779: [(779, 1.130409836769104)] | 无限制查: 1.130409836769104
  ```

  实现路径由实现者定，但必须满足：
  1. BM25 路也过同一个 `MAX_RELEVANT_DISTANCE` 下限
  2. 融合后不再出现「与问题完全无关的切片」
  3. 相关查询（如 `'医保结算清单 接口'`，向量 top1=0.6521、BM25 命中 20）不被误杀
  4. 说明清楚每次 `local_search` 增加几次 SQL 查询、是否涉及嵌入服务调用

  **注意**：sqlite-vec 的 KNN 查询**不能同时给 `k = ?` 和 `LIMIT`**
  （实测 `Only LIMIT or 'k =?' can be provided, not both`）。
  现有代码用 `k = :k` + `ORDER BY v.distance`、没有 LIMIT，是对的——别加 LIMIT。
  KNN 的 `k` 上限是 4096（实测 `k value in knn query too large, provided 5000 and the limit is 4096`）。

#### 1.1 阈值用**余弦距离**，不是 L2（2026-10-24 实测后修订）

实测真实嵌入的模长 **恰好 1.0**，所以「L2 = sqrt(2-2cos)」在生产里成立。
但 **L2 对模长敏感**，用它判相关性等于让「这个切片的模长恰好多大」决定它相不相关：

- dev 库里 7398 个向量有 **9 个模长是 19.596**（早期测试留下的 `[0.5]*1536` 脏数据），
  其余全是 1.0；
- `tests/test_local_search.py` 的 fixture 用 `[0.5]*1536` vs `[0.1]*1536`，
  两者**方向完全相同**（cos = 1.0）但 L2 = **15.68** → 用 L2 阈值会把它们全杀。

**实测排除的两条路**：

| 方案 | 结果 |
|---|---|
| 入库时归一化 | 破坏既有距离语义（`_vec(1.0)` vs `_vec(0.8)` 归一化后距离变 0，无法区分）→ 多挂 9 条既有测试 |
| 只归一化查询侧 | 同上，且存量侧模长不一时距离仍偏大 |

**采用余弦距离**（`1 - cos`，只看方向、对模长免疫）。实测：
同一向量放大 2 倍，余弦距离仍是 0.0（完全同向）；反向是 2.0（完全反向）。

sqlite-vec 支持 `vec_distance_cosine(v.embedding, :vec)`，且 **KNN 查询可以在
同一次查询里同时 select `v.distance` 与余弦距离**（实测可行）——所以：

- `knn_search` 的**返回值仍是 L2**（项目既有契约，`test_distance_is_l2_not_cosine`
  明确锁定「vec0 返回 L2 不是余弦」，为将来换 pgvector）；
- **相关性判定用余弦距离**，过滤在 `knn_search` 内部做；
- `chunk_distances`（给 BM25 路用）返回余弦距离，两条路用同一个度量同一个阈值。

**阈值标定（2026-10-26 在生产库重新标定，7 组相关 + 7 组不相关查询，top-20）**：

| 查询 | top1 L2 | top1 余弦距离 | top-20 最大余弦距离 |
|---|---|---|---|
| 相关：医保结算清单 接口 | 0.6521 | **0.2126** | 0.3055 |
| 相关：个人医疗消费费用清单 | 0.6092 | 0.1855 | **0.4006** ← 旧阈值 0.40 会误杀 |
| 相关：跨省异地就医结算 | 0.5070 | 0.1285 | 0.3911 |
| 不相关：iPhone 折叠屏 质量 | 1.1496 | **0.6608** | 0.6834 |
| 不相关：国产折叠屏 手机 耐用性 | 1.1166 | 0.6234 | 0.6502 |
| 不相关：量子计算 行业报告 | 1.1208 | 0.6281 | 0.6737 |

**`MAX_RELEVANT_DISTANCE = 0.45`（余弦距离）**，取在相关侧 0.4006 与
不相关侧 0.6234 之间。（最初定的是 0.40，实测发现它会误杀「第二实体」的
证据——见第二轮的重新标定。）

等价关系（单位向量下）：`L2 = sqrt(2 - 2cos)`，所以余弦距离 0.45 对应
L2 ≈ 0.95。

**docstring 必须写清**：用的是余弦距离（不是 L2）、换 pgvector 要重新标定、
标定值（相关 ≤0.4006 / 不相关 ≥0.6234）、以及与 L2 的换算关系。

#### 1.2 `retrieve` 的返回类型不能变

既有多处调用与测试断言 `await retriever.retrieve(...) == []`（返回 list）。
`retrieve` 必须继续返回 `list[Retrieved]`。

若需要额外信息（「有没有候选但被过滤掉了」），用**配套函数**或**可选出参**提供，
不要改 `retrieve` 的返回类型。

**内容去重**。实测那次召回 12 条只有 4 种不同内容，「参保人手机 | tel | String | 50」重复 4 次，
把 10 个引用位占满。实测「医保结算清单 接口」召回 12 条有 8 种（其中 1 种重复 5 次）。

- 在 `retriever.retrieve` 融合之后、截取 `limit` 之前做去重。
- 去重键 = **切片正文 `chunk.content` 全文**（不是截断后的）。同一份资料里
  「个人编号 | psnNo | String | 是」在 7388 个切片里出现 82 次，正文完全一样。
- 保留**第一次出现**的（融合分数最高的那个），后面的丢弃。
- 去重后再取 `limit` 条——即去重要在 `fused[:limit]` **之前**，否则去重后数量可能不足 limit。

**这两条要能配合**：不相关时向量路返回空 → 融合结果空 → `retrieve` 返回空列表 →
`tools._run_local_search` 走已有的「用户的资料库里没有检索到相关内容」分支。

### 第 2 项：`MAX_REFERENCES` 与 `LOCAL_SEARCH_TOP_K` 的错配

现状：`citation.MAX_REFERENCES = 10`，`tools.LOCAL_SEARCH_TOP_K = 12`。
引用表满 10 条后，**第二次 `local_search` 的证据块是空字符串**，只剩引用规则喂回模型——
模型看到「编号 [1] 到 [10]」却一条证据都没有。

实测确认（`ReferenceTable.register`）：
- 第一次 `register(12 条)` → 证据块 10 条，`dropped=2`
- 第二次 `register(12 条)` → 证据块 **0 条**，`dropped` 累计 14

**改法**：`LOCAL_SEARCH_TOP_K` 从 12 改成 **10**，与 `MAX_REFERENCES` 对齐。

- 为什么选 10 而不是反过来调大 `MAX_REFERENCES`？`MAX_REFERENCES` 的 docstring 给了理由：
  「模型会被告知『编号 [1] 到 [72]』，那个跨度它根本记不住，反而更容易编错号」。
  10 是有意选的，调大要重新论证。改 `LOCAL_SEARCH_TOP_K` 到 10 最小、且不动那个论证。
- 改完之后 `tools.py` 里 `LOCAL_SEARCH_TOP_K` 的注释必须同步更新——
  现在写的是「这里取 12 是为了给 RRF 融合后的一点重排留余量——超出 10 的会被引用表截掉，
  但模型仍能拿到排名靠前的那几条」。这句话描述的是一个**有 bug 的行为**
  （第二次调用时一条都拿不到），必须改掉，说明新值 10 与 `MAX_REFERENCES` 对齐的理由。
- `citation.py` 的 `MAX_REFERENCES = 10` **不动**。

**验收**：第二次 `local_search` 的证据块不再是空字符串。

### 第 3 项：错误分类与文案（**重点**）

现在的 `LLM_CONTENT_FILTERED` 文案是「请求被上游内容安全策略拦截，请调整问题措辞后重试」。
这个诊断**是错的**（上游没拦），而且**处置建议是错的**（改措辞没用——问题在资料库与问题的错配）。

`app/services/errors.py` 里现有相关代码：

```python
LLM_CONTENT_FILTERED = "llm_content_filtered"
"""上游内容安全拦截。换个问法才有用，重试无用。"""

_CONTENT_FILTER_MARKERS = ("内容安全", "敏感", "不合规", "合规系统", "safety")

def _is_content_filtered(detail: str) -> bool:
    lowered = detail.lower()
    return any(marker in lowered for marker in _CONTENT_FILTER_MARKERS)

def _bad_request_classified(exc: BaseException) -> Classified:
    detail = _error_message(exc)
    if _is_content_filtered(detail):
        return Classified(
            LLM_CONTENT_FILTERED,
            "请求被上游内容安全策略拦截，请调整问题措辞后重试",
            preview="内容被安全策略拦截",
            retryable=False,
        )
    ...
```

#### 3.1 上游内容安全拦截这一档，**要保留**

上游**确实**可能拦内容（Anthropic 官方就有这套机制）。我们没法区分
「上游拦了真内容」和「上游对畸形上下文报内容安全」——因为两种情况的响应体一样。

所以 `LLM_CONTENT_FILTERED` 这一档**不能删**，但**文案必须改**：
不能再让用户去「调整问题措辞」（对两种情况都没用）。

#### 3.2 新增一档：`retrieval_no_match`（本地检索无相关性）

这是**本项目自己的**错误，不是上游的。它发生在 `local_search` 返回空的时候——
但现在那条路径是 `ok=True` 的正常分支，模型会看到「用户的资料库里没有检索到相关内容」
然后**继续用联网搜索作答**，用户完全不知道自己的私有资料被跳过了。

**改法**：`tools._run_local_search` 在「检索到 0 条」时，除了现有的 `ok=True` 文案，
还要让调用方知道「这次检索因为资料不相关而空」。

设计要求（不要照抄，实现方式由你定，但必须满足）：

1. `tools.py` 需要一个**能区分两种「0 条」**的机制：
   - 「资料库里压根没有相关内容」→ 现有文案，模型如实说明即可
   - 「有资料但与问题无关，被相关性下限过滤掉了」→ 新文案，要明确告诉模型
     **这些资料与问题无关，不要拿它们当证据**
2. 新的错误 code（建议 `retrieval_no_match`，但你可以选更好的名字）要：
   - 遵循现有命名约定：见 `app/services/errors_base.py` 的 `TOOL_*` 错误码段，
     以及 `errors.py` 的 `LLM_*` / `EMBEDDING_*` 段。命名规则是「小写下划线，语义前缀 + 具体含义」。
   - 在 `errors.py` 的 `__all__` 里导出
   - 有对应的 `Classified`（code / message / preview / retryable）
   - `retryable` 的取值要合理：重新检索一次大概率还是同样结果 → **False**
     （除非你能论证某些情况下换 query 就能命中）
3. `tools.py` 的 `_classify_tool_failure` 要能产生这一档。

#### 3.2.1 关键设计约束：这一档**不是致命错误**

**「本地资料与问题无关」不该让整次研究失败。** 模型还有联网搜索，
用户问手机对比、资料库里只有医保文档，正确行为是**继续用联网搜索作答**，
并在正文里说明「你的资料库里没有与这个问题相关的内容」。

所以：

- `local_search` 返回「0 条命中」时 **`ok` 仍然是 `True`**，不是失败
- **不要**为它单独发一个 `ErrorEvent` 中止流程
- 新 code 挂在 `ToolOutcome` 上（加一个字段，或写进 `preview`——前端工具轨迹表
  会显示 `preview`），这样它能出现在前端的工具轨迹里
- `ToolOutcome` 的 `content`（喂回模型的文本）要明确告诉模型「这些资料与问题无关，
  不要拿它们当证据」
- 分类器要能把这一档造出来（有一个对应的异常类），这样它冒泡到错误路径时
  也能被正确分类

**前端不需要改**：`apps/web/app/(dashboard)/explore/page.tsx` 的错误横幅直接渲染
后端下发的 `error` 帧；工具轨迹表显示 `ToolCallEvent.preview`。
`apps/web/app/(dashboard)/explore/constants.ts` 的 `HTTP_ERROR_CODES` 把 HTTP 400
映射成 `llm_not_configured`——这条映射本身没错，新 code 不走 HTTP 状态码路径，
两者不冲突。

#### 3.2.2 `retrieve` 的返回类型不能变

既有多处调用与测试断言 `await retriever.retrieve(...) == []`（返回 list）。
`retrieve` 必须继续返回 `list[Retrieved]`。

若需要额外信息（「有没有候选但被过滤掉了」），用**配套函数**或**可选出参**提供，
不要改 `retrieve` 的返回类型。

#### 3.3 `LLM_CONTENT_FILTERED` 的文案改法

**要点：不能再让用户改措辞。** 用户看到这句会以为是自己写错了问题，反复改措辞重试，
而真正的原因是资料库和问题的错配。

改成能同时覆盖两种情况的说法，措辞由你定，但必须满足：

- 不暗示「换个问法就能过」
- 明确指出**大概率是资料内容与问题不匹配**（这是最常见的原因）
- `retryable` 的取值要重新考虑：这一档现在的 `retryable=False`。
  改成 `False` 合理吗？——现状是 False（上游拦了，重试无用）。
  但按 3.2 的分析，**最常见的成因是检索错配，改一下问题或资料就可能好**。
  你要基于实测结论做判断，并在注释里写清理由。

#### 3.4 分类器的判断顺序

`classify_llm_error` 里 `_bad_request_classified` 在 `status == 400` 分支被调用。
`LLM_CONTENT_FILTERED` 的判定靠 `_error_message(exc)` 里的关键词匹配。
这一层**不动**——上游返回什么就是什么，分类器只负责把它翻译成人话。

**但**：`errors.py` 的 `classify_llm_error` docstring 里有一段说明
「实测上游会返回『检测到内容包含敏感或不合规信息,已被内容安全合规系统拦截』」，
并解释「报成『请求被拒』用户会反复重试同一个问题；报成『内容被拦截』用户知道要改问法」。
**这段说明现在不准确了**——实测表明这招不奏效，因为真实成因常常不是用户措辞。
要更新这段注释，写清新的理解。

## 不在范围

- 不改 `MAX_REFERENCES` 的值（10 保持）
- 不改前端错误横幅的 UI 样式
- 不做向量的 rerank（PRD 里提过的 rerank 精排不在本次范围）
- 不改嵌入模型或维度
- 不处理 `MAX_TURNS` / 轮次上限

## 实现后的验证结果（2026-10-25）

### 离线端到端（生产库 argus.db，真实向量，不调外部服务）

原始事故场景（用户问 iPhone 折叠屏 vs 国产折叠屏，资料库里只有医保接口文档）：

```
查询词='苹果手机 折叠屏 质量 对比 华为'
  向量路召回 0 条
  BM25 路（过滤后）0 条
  BM25 路（过滤前）23 条 ← 阈值挡掉了 23 条
```

两路都归零——这正是修复前的问题（23 条无关切片被喂给模型）。

相关查询不被误杀：

```
查询词='医保结算清单 接口'  →  向量路召回 10 条，BM25 路 10 条
```

模长不影响判定：

```
查询向量模长×10 → 召回 10 条（与原始 10 条一致）
```

### 质量门

```
ruff check app/ tests/ alembic/   → All checks passed!
mypy app/                          → Success: no issues found in 47 source files
pytest tests/                      → 620 passed
pnpm --filter web exec tsc --noEmit → 通过
pnpm --filter web lint              → 通过
```

`ruff format --check` 在全库是红的（ruff 版本差异导致的既有状态，改动前就红），
本次改动的实现文件 format 干净；测试文件里剩下的 diff 全在既有代码上。

## CR 后的追加修复（2026-10-25）

reviewer-fresh 报了 10 条，其中 7 条已修。都是**实测确认过**的：

| # | 问题 | 修法 |
|---|---|---|
| 严重 1 | 零范数向量让 `vec_distance_cosine` 返回 NULL → `float(None)` TypeError → **整条本地检索挂掉** | 两处都判 None：零范数当「不相关」挡掉（`knn_search`）、不返回（`chunk_distances`）。加 2 条回归测试 |
| 重要 4 | 「相关性未评估过」（没配嵌入 key / 索引未建好）被误判成「资料与问题不相关」——模型会照着对用户说错话 | 新增 `retriever.NoResultReason` 三态 + `explain_no_result()`；新增错误码 `retrieval_not_evaluated` |
| 重要 6 | `ToolOutcome.error_code` 是死字段，生产代码没人读 → 错误码到不了用户眼前 | `ToolCallEvent` 加 `error_code` 字段 → SSE → 前端工具轨迹表显示「资料被跳过」标记 |
| 重要 7 | 内容安全文案仍指向「资料与问题不匹配」——**那正是本次修复消掉的成因** | 改成指向「资料本身相关但含敏感信息」 |
| 重要 9 | `LOCAL_SEARCH_TOP_K` 12→10 对「第二次证据块为空」**零效果**（表照样满） | 新增 `citation.render_saturated_notice()`：证据块为空且确实有丢弃时明说「引用表已满」，并指向已有编号。加回归测试（注入验证过） |
| 重要 3 | 没配嵌入 key 时相关性下限整路没跑 → 原始 bug 形态复现 | `retriever.semantic_filter_active()` + 在 tool_result 里告诉模型「只做了关键词匹配，没做语义相关性判断」 |
| 重要 10 | `knn_search` 的 docstring 描述的是**已放弃的归一化方案**（`normalize_vector` 根本不存在），且与同文件另一段直接矛盾 | 整段重写为「两个度量各司其职」 |

## 第二轮：参考 PRD 与业界做法后补的三项（2026-10-26）

reviewer 剩下的 3 条按「参考目标项目 + 参考业界」处理完。

### 参照物

**项目自己的 PRD**（`prd/rag-pipeline.md` §7-8）：混合检索 top 50 → **rerank** → top 10。
PRD 明确规划了 rerank（Cohere Rerank v3）——当前实现缺这一环，这正是
「阈值只按 top-1 标定却作用在 top-50 上」缺口的来源。

**业界做法**（检索了多个来源）：
- 固定全局阈值被公认脆弱（"the embedding similarity score rarely gives you a good
  global cutoff"）→ 主流改用相对 top-1 的动态阈值 + 绝对下限（HiSem-RAG 等）
- 多租户向量检索的标准做法是 **pre-filter in the database, never post-filter in
  application code**——应用层过滤漏一次就是跨租户泄漏，且**不报错**
- rerank 与 filter 是两件事：filter 是布尔筛除，rerank 是给已通过者重新打分

### 1. 阈值重新标定（重要 5）

**在生产库实测标定**（7398 个真实切片，7 组相关 + 7 组不相关查询，top-20）：

- 相关查询全部 ≤ **0.4006**
- 不相关查询全部 ≥ **0.6234**

0.40 **卡在边界上**，实测会误杀 4 条「本接口用于查询医保个人账户的交易明细信息。」
（距离 0.4006）——那是「个人医疗消费」之外的**另一个实体**的证据，
reviewer 说的「多实体对比问题漏掉第二方证据」被实测证实。

→ 阈值放宽到 **0.45**（相关 ≤0.4006 与不相关 ≥0.6234 之间，两端都有余量）。

**没有引入相对阈值**：实测下来相对层在这批数据上**完全不起作用**——
它只在 `top-1 × ratio > 绝对阈值`（即 top-1 > 0.60）时更严，而那时
绝对阈值早就把候选挡住了。多一个没有实测依据的参数只会让人以为它在做什么。
所以保留单一绝对阈值 0.45，`is_relevant()` 是唯一的判定入口。

### 2. 租户收窄（重要 8）

`chunk_distances` 的签名加了**必填** `source_ids`，收窄在 SQL 里做
（JOIN 到 `document_chunks`，不是「调用方先过滤再传 id」）。

实现踩坑：sqlite-vec 限制一张 vec0 表里只能有**一个** `rowid in (..)`
运算符（实测报 `only 1 'rowid in (..)' operator is allowed in a single vec0
query`）——所以第二个 `IN (SELECT ...)` 改成 JOIN。

### 3. 崩溃路径的超时边界（严重 2）

落盘失败的**清理路径**（`db.rollback()` + `_recover_persisted_id` 的
`db.get()`）原来无上限。落盘超时的成因往往就是「DB 卡住」——同一个坏连接上
再 await 一次会**再等一次**，而 `yield done` / `yield error_event_for` 都在
`_persist_report` **之后** ⇒ 用户永远等不到失败横幅，SSE 流挂死。

→ 整个失败处理路径纳入同一个 `asyncio.timeout`。注入验证：移除后测试挂 **10.67 秒**
（正是挂死时长）而不是立刻失败。

## 完成定义（DoD）

1. `MAX_RELEVANT_DISTANCE` 常量存在于 `vectorstore.py`，带实测依据的 docstring
2. 不相关查询下 `local_search` 不再返回无关切片；相关查询下正常返回
3. 第二次 `local_search` 的证据块不再为空
4. 新的「检索无相关性」错误码存在、已导出、有测试
5. `LLM_CONTENT_FILTERED` 的文案不再让用户改措辞
6. 后端质量门全过：`ruff check` / `ruff format --check` / `mypy app/` / `pytest`
7. 前端类型检查过（若改了前端文件）

## 质量门命令

```bash
cd apps/api
uv run ruff check app/ tests/ alembic/
uv run ruff format --check app/ tests/ alembic/
uv run mypy app/
uv run pytest tests/ -q --no-header -p no:cacheprovider
```

```bash
pnpm --filter web lint
pnpm --filter web exec tsc --noEmit
```

注意：`pnpm --filter web tsc --noEmit` 是**空命令**（`apps/web/package.json` 没有 `tsc` script），
退出码 0 但什么都没跑。必须用 `exec tsc --noEmit`。
