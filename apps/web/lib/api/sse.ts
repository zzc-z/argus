/**
 * SSE 事件的前端类型镜像。
 *
 * 唯一事实源是后端 `apps/api/app/services/stream.py` 的 dataclass——改那边
 * 必须同步改这里。字段全 snake_case：`encode_frame` 直接 `asdict()` 输出，
 * 没做 camelCase 转换。
 *
 * 为什么要单独一份：消费端散落在各页面时，后端加一个字段要挨个找；
 * 之前 `explore/page.tsx` 就手写了三份 DTO 且漏了 `preview`。
 */

/** 智能体节点生命周期。后端只发 active / completed，pending 是前端初始态。 */
export type NodeLifecycle = 'pending' | 'active' | 'completed'

/** `type: "node"` —— 节点生命周期变化。任一时刻只允许一个 active。 */
export interface NodeEventV {
  node_id: string
  lifecycle: string
  detail: string
  elapsed_ms: number | null
}

/** `type: "delta"` —— 正文增量。前端 `streamedText += text`。 */
export interface DeltaEventV {
  node_id: string
  text: string
}

/**
 * `type: "tool_call"` —— 一次工具调用的 start / end 两段。
 *
 * ⚠️ end 帧的 `tool_input` 是空对象，参数只在 start 帧里。要展示入参必须
 * 按 call_id 拿 start 帧那份，不能只读 end。
 */
export interface ToolCallEventV {
  call_id: string
  phase: string
  name: string
  tool_input: Record<string, unknown>
  ok: boolean
  elapsed_ms: number
  /** 结果概要，仅 end 帧有值。 */
  preview: string
}

/**
 * 单条引用。形状对应后端 `app/services/citation.py` 的 `Reference`。
 *
 * `n` 从 1 起（0 被刻意排除，避免与「未标注」混淆），与正文里的 `[n]` 一一对应。
 */
export interface ReferenceV {
  n: number
  chunk_id: number
  source_id: number
  /** 0-based，展示时是「第 n+1 段」。 */
  chunk_index: number
  /** PDF 页码；null = 非 PDF（网页 / 纯文本）。 */
  page: number | null
  title: string
  /** 原文前缀，后端截到 120 字，给角标 tooltip 用。 */
  excerpt: string
  /** 召回来源：'向量+BM25' | '向量' | 'BM25'。 */
  recall: string
}

/**
 * `type: "reference"` —— 引用表下发。
 *
 * ⚠️ 是**累积全量**，不是增量：后端 `ReferenceTable.all` 按编号升序返回
 * 已编号的全部引用。所以要整体替换 setState，不能 append。
 *
 * 单独一个事件而不是塞进 done，是因为引用要在正文之前就到，否则用户读到
 * `[3]` 时还没法点击。
 */
export interface ReferenceEventV {
  references: ReferenceV[]
}

/** `type: "done"` —— 正常收尾。 */
export interface DoneEventV {
  session_id: string
  elapsed_ms: number
  turns: number
  input_tokens: number
  output_tokens: number
  /** 三种触发：max_tokens、轮次耗尽强收、agent 循环崩溃。 */
  truncated: boolean
  /**
   * 刚落盘的报告 id。没有 db 或落盘失败时为 null。
   *
   * explore 页读它渲染「查看完整报告」链接，跳 `/report/${report_id}`
   * （注意是单数 `report`，`/reports` 是列表页、没有 `[id]`），因为报告
   * 只在落盘后才在 `/api/v1/reports` 里存在，session_id 不是列表的查询键。
   *
   * ⚠️ 目标页 `app/(dashboard)/report/[id]/page.tsx` 当前**仍是 mock 数据**。
   * 链接会跳过去，但显示的是编造的基准与 TCO 数字。改那一页之前，
   * 这个链接是有害的。
   */
  report_id: number | null
}

/** 一条未被原文支撑的引用。 */
export interface UnsupportedV {
  /** 角标编号，对应正文里的 `[n]`。 */
  footnote: number
  /** 带角标的原句。 */
  sentence: string
  /** 模型给的中文理由，一句话。 */
  reason: string
}

/**
 * `type: "faithfulness"` —— Critic 对引用忠实度的校验结论。
 *
 * 刻意**不阻断**：模型已跑完多轮检索，剔除内容等于让它白跑；把结论
 * 标注出来让用户自己判断，成本为零。
 *
 * `skipped` 为真时只带 `reason`——没有原文可比（无检索上下文）、模型
 * 客户端未配置、或 LLM 调用失败时都走这条路。
 */
export interface FaithfulnessEventV {
  checked: number
  supported: number
  unsupported: UnsupportedV[]
  /** 正文引用了但引用表里没有的编号——标注层面的错，不是忠实度问题。 */
  missing: number[]
  skipped: boolean
  reason: string
}

/** `type: "error"` —— 开流之后的错误。SSE 的 HTTP 头早已发出，只能靠事件。 */
export interface ErrorEventV {
  code: string
  message: string
  retryable: boolean
}

/**
 * 按事件类别取 `v` 字段。
 *
 * `SseEvent.v` 是 `Record<string, unknown>`（信封形状与具体类型无关），
 * 这里做一次窄化，避免每个调用点各写一遍 double-cast。
 *
 * ⚠️ **这是编译期断言，不是运行时校验**——`event.v as T` 不检查任何字段。
 * 后端改字段名不会在前端报错，只会得到 undefined。所以它替代的是
 * `as unknown as T` 这种双重断言（那种写法连类型都不关联），**不是**
 * 运行时契约校验。真要防后端漂移得写 schema 校验，那是另一件事。
 */
export function parseEvent<T>(event: { type: string; v: Record<string, unknown> }): T {
  return event.v as T
}