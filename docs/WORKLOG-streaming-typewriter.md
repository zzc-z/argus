# 进展记录：流式打字机 + 滚动跟随 + 错误分类修正

> **2026-11-01。** 这一轮改了 21 个文件（+1582 / -225），**全部未提交**。
> 新会话接手先读这份，再读 `docs/SPEC-streaming-typewriter.md`（技术细节与实测数据）。

## 起点：用户报的三个问题

1. 「explore 页内容出现也不是打字机效果呀，目前是一下全部出现了的」
2. 「不能算是流式了 一次性蹦出太多字符了 两次就生成完全文 一次生成的字符一定要少」
3. 「文字出现后应该一直滚动到最底端 跟随文字走，你参考主流项目再改」

## 根因与修法

### ① 后端攒完才发（打字机完全失效）

`agent._run_turn` 原本是 `await stream.get_final_message()` —— 把整轮流攒完
才返回，主循环随后一次性发出。实测：**60 个 delta 帧在 0.0 ms 内全部出栈**，
浏览器一个 TCP 块收齐，React 一次渲染完。

`TextSlicer` 的 docstring 早就写明了「中转站把整个 text 块缓冲成一次
text_delta……这个类在后端补上那一层」——它补的是「切」，没补「什么时候送」。

**修法**：`_run_turn` 改成异步生成器，消费上游 `content_block_delta`
边收边发；新增 `stream.py` 的 `Typewriter`（切片 + 控速两层）。

### ② 节奏参数（用户第二次反馈）

第一版（24 字/片 + 35ms 间隔）实测**仍然太快**：800 字正文在 **0.8 秒内**
全部送出 —— 用户等了 25 秒上游，然后全文在 1 秒内涌出来。

最终参数：

| 常量 | 值 | 依据 |
|---|---|---|
| `CHUNK_SIZE` | 8 字/片 | 用户要「一次生成的字符一定要少」 |
| `TARGET_CHARS_PER_SECOND` | 80 字/秒 | 中文阅读 5-8 字/秒；800 字 → 10 秒 |
| `MIN_PIECE_INTERVAL_SECONDS` | 16ms | 只是兜底，防「一个字一个字蹦」 |

**控速用令牌桶（按累计字数算），不是「每片固定等 N 毫秒」**：固定间隔会
把上游真流式拖慢 4 倍（720 字上游 5 秒吐完 → 19.2 秒），按字数算则
上游缓冲时慢放、真流式时跟随上游。

端到端实测（8000 端口真实提问）：838 字 → 99 帧，每帧 5-10 字，
帧间隔中位 101.7ms，0% 帧同时到达。

### ③ 前端滚动跟随（全站原本没有任何滚动逻辑）

新增 `apps/web/lib/hooks/useStickToBottom.ts`，按主流项目（ChatGPT / Claude /
Perplexity）的四条规则：内容增长自动跟底 / 用户上滚则暂停 / 回底恢复 /
暂停期间给「回到底部」浮标。

**滚动宿主是 `.center`**（`page.module.css` 里 `overflow-y: auto`），
不是 `window` —— `.shell` 是 `overflow: hidden` + 固定高度，整页不滚。

### ④ 顺带修的：切片劈开词

`CHUNK_SIZE` 24 → 8 暴露的 bug：搜索窗口缩到 12 字，**看不见下一个字符**，
判断不了千分位还是真逗号 → `100,000` 被劈成 `100,`+`000`、
`Blackwell` 被劈成 `Blackwel`+`l`。

三处修法：`_splits_a_token` 改看完整缓冲区；切点后必须至少还有一个字符；
硬切也避开词中间。

### ⑤ 顺带修的：流内错误分类

`llm_unavailable`「模型服务暂时不可用」是**误报**。真实原因是上游返回
**HTTP 200 + SSE 流内 error 事件**：

```json
{"type":"error","error":{"type":"api_error",
 "code":"subscription_identity_review_unavailable",
 "message":"The protected subscription response could not be approved. Please retry."}}
```

流式请求的错误不走状态码 —— 分类器只按状态码查表，200 必然落空 → 兜底。
上游 message 明写 "Please retry"，却被报成「服务挂了」。

**修法**：`errors.py` 新增 `_in_stream_error_classified()`，按 `error.type`
分档，**与非流式同类型落到同一档**（Anthropic 官方要求「按与非流式相同的
分支逻辑处理」）。未知类型 → 新错误码 `llm_upstream_error`（可重试）。

### ⑥ 顺带修的：前端 500（既存问题）

前端所有页面 500：`next/font/google` 的字体 loader 解析失败
（`Can't resolve '@vercel/turbopack-next/internal/font/google/font'`）。

**与本轮改动无关** —— `git stash` 到 HEAD 同样 500，是 Next 16.3.8 +
Turbopack 的既存缺陷。

两处修法：
- `pnpm dev` 固定带 `--webpack`（实测 200），另留 `dev:turbopack`
- `next/font/google` 全项目只能有**一个**导入入口 → Inter 挪进
  `app/layout.tsx`（`--font-inter` 变量），页面改用 `var(--font-inter)`

### ⑦ 顺带修的：重发退避改指数

断连的根因当时是**本机 VPN/代理**（`fadeptun` 网络扩展，切换出口节点时
重置连接）—— Tavily 与 Anthropic 两个不同服务在**同一秒**断开。

日志时间线：

```
17:10:53  POST /api/v1/research/ask 200
17:11:01  模型流被中断，第 1 次重发整轮请求
17:11:01  模型流被中断，第 2 次重发整轮请求
17:11:01  模型流被中断，第 3 次重发整轮请求
```

**固定的 1 秒间隔让 3 次重试全落在同一个坏窗口内**，白等。改成指数退避
（1s → 2s），最后一次重发推到 3 秒之后。

用户确认：**关掉 VPN 后恢复正常**。指数退避保留 —— 网络抖动时它仍有用。

## 变异测试（每个都真的被抓到）

| 变异 | 抓到它的测试 |
|---|---|
| 去掉控速（`min_interval` 恒 0） | `test_typewriter_paces_pieces` |
| `Typewriter` 改回「返回列表」 | `test_typewriter_paces_pieces` 等 4 条 |
| `_stream_turn_once` 攒完再 yield | `test_text_is_emitted_before_the_upstream_stream_ends` |
| 断流重发不发 reset | `test_retry_resets_already_sent_text` |
| 去掉「切点不能在缓冲区末尾」守卫 | `test_numbers_are_not_split_across_pieces` |
| 硬切不避词中间 | `test_english_words_are_not_split_across_pieces` |
| 去掉流内错误分类 | 3 条流内错误测试 |
| 流内判定用宽松的 `_error_body` | `test_http_200_without_error_body_is_not_in_stream_error` |

`_stream_turn_once` 那条是核心：靠「上游挂起」把「边收边发」和「攒完再发」
区分开 —— 两种实现最终发出的正文**完全一样**，只能靠时序区分。

## 门禁

- 后端：641 pytest / ruff / mypy 全绿
- 前端：tsc / eslint 全绿；prettier 对新增代码零差异

## 期间我自己犯的错（记录下来免得重犯）

1. **误删了 `el.scrollTop = el.scrollHeight`** —— Edit 时 old_string 含赋值语句、
   new_string 只留注释，effect 里只剩注释没有任何代码。表现是「滚动没跟随」，
   但我在后端绕了很多圈才定位到（用户还质疑「为啥要改后端代码」）。
   **教训**：改代码后如果行为没变，先看那段代码**实际在不在**。
2. **`_credit` 双重扣减** —— 令牌桶实现里扣了两次，credit 越欠越多 → 死等
   （测试超时 180s 才暴露）。**教训**：新写的状态机先在小样例上跑一遍。
3. **`Typewriter` 最初返回列表** —— 控速的等待发生在函数内部，等完所有片段
   仍同时交付。测试 `test_typewriter_paces_pieces` 直接抓到了。

## 未完成 / 待办

- **改动全部未提交**（21 个文件）。等用户指令。
- 指数退避的变异测试**没跑成**（分类器 `claude-opus-4-7[1M] is temporarily
  unavailable` 持续拦截 Bash 与 Monitor）。代码已确认恢复正确
  （`app/services/agent.py:988` 是 `* (2**attempt)`），测试已写好
  （`test_retry_backoff_is_exponential`），18/18 通过但**没做变异验证**。
  接手后要做：把它改成 `STREAM_INTERRUPT_BACKOFF_SECONDS`（去掉指数），
  确认那条测试变红，再改回来。
- `apps/web/next-env.d.ts` 是 next dev 自动改的（dev 模式的类型路径不同），
  AGENTS.md 说「连同改动一起提交能让工作树干净」。

## 当前运行状态

| 服务 | 地址 | PID | 备注 |
|---|---|---|---|
| 后端 | http://localhost:8000 | 53231 | 无 `--reload`，改后端要重启 |
| 前端 | http://localhost:3000 | 56775 | **webpack 模式**（Turbopack 会 500） |

## 关键链接

- [docs/SPEC-streaming-typewriter.md](SPEC-streaming-typewriter.md) — 完整技术规格与实测数据
- [docs/LOCAL-DEV.md](LOCAL-DEV.md) — 环境事实（新增：流式错误不走状态码、Turbopack 字体 500、滚动宿主是 `.center`）
