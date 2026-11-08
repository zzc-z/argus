/**
 * /explore 的前端静态常量。
 *
 * 全部内容都是**后端契约的前端镜像**，不是演示数据：
 * 节点 id 逐个对应后端 `app/services/agent.py` 的 `Stage` 枚举，
 * 改成别的值 DAG 就永远推不动。
 *
 * 后端只发 node_id，不发展示名——名字与角色说明由本表提供，
 * 运行时进度由 node 事件的 `detail` 覆盖。
 */

import type { NodeLifecycle, ReferenceV } from '@/lib/api/sse'

/** 引用条目。直接用后端契约，不另立一套展示形状。 */
export type Citation = ReferenceV

/** 节点生命周期。后端只发 active / completed，pending 是前端初始态。 */
export type { NodeLifecycle }

export interface AgentNode {
  /** 对应后端 `Stage` 枚举值。React key + 事件匹配都用它。 */
  id: string
  /** 展示名（中文 + 英文缩写）。 */
  name: string
  /** 静态角色说明，来自 STAGES。不被运行时事件覆盖。 */
  role: string
  /**
   * 运行时状态说明，来自 node 事件的 `detail`（"正在检索与取证"）。
   *
   * 与 `role` 分开存而不是互相覆盖：detail 是**进行时**的描述，节点跑完后
   * 后端发 completed 且 detail 为空串（`stream.py:30` 的默认值），此时该
   * 显示静态 role——「正在检索与取证」配着完成勾是错的。
   */
  detail: string
  /**
   * 这个节点的产出摘要，来自 node 事件的 `note`。
   *
   * 「做完了什么」：「核对 12 条引用，10 条有据支撑」。与 detail 相反的
   * 生命周期——detail 在 active 时有值、完成后清空；note 在 active 时为空、
   * 完成后才有值。
   */
  note: string
  lifecycle: NodeLifecycle
  /** 格式化好的耗时文案（"1.2s" / "排队中"）。 */
  latency: string
  /**
   * 本段开始前的**累计**耗时（毫秒）。active 时有效。
   *
   * 前端用它当实时秒数的基线：researcher 分多段跑时，用户看到的应该是
   * 「11.0s → 12.0s → 16.2s」这样连续增长的数字，而不是每段都从 0
   * 开始跳（0 → 10 → 0 → 1 → 0 → 5）。
   *
   * 值来自后端 active 帧的 `elapsed_ms`——只有后端知道这个节点之前
   * 累计跑了多久。
   */
  elapsedBaseMs: number
  /**
   * **本段**开始的时刻（毫秒时间戳）。active 时有效。
   *
   * 与 `elapsedBaseMs` 配对使用：实时秒数 = 基线 + (现在 - 本段开始)。
   * 只记基线不行——不知道这一段是什么时候开始的，就算不出它跑了多久。
   */
  segmentStartedAt: number | null
}

export interface ToolCall {
  id: string
  name: string
  /** 截断过的入参预览。 */
  args: string
  duration: string
  /**
   * 这次调用是否成功。null = 还在执行（只有 start 帧）。
   *
   * 失败必须显出来：一次失败的 local_search 与一次成功的，
   * 在轨迹表里长得一模一样（只有耗时不同）——用户会以为资料真的
   * 查过了，而其实那一路整个断掉了。
   */
  ok: boolean | null
  /**
   * 结果概要 / 失败原因。失败时是具体原因（如「嵌入服务欠费」），
   * 成功时是命中条数一类的短摘要。
   */
  preview: string
  /**
   * 特殊情况的错误码（空串 = 没有）。
   *
   * `ok=true` 但这里非空，说明工具正常跑完了，只是结果落在某一档特殊情况
   * 里——最典型的是 `retrieval_no_match`：私有资料与问题不相关，用户的
   * 资料**被跳过了**。这是用户有权知道的事，不能只埋在 preview 里。
   */
  errorCode?: string
}

/**
 * DAG 的 5 个节点，顺序即展示顺序。
 *
 * `id` 必须与后端 `Stage` 一字不差——`applyNode` 按 id 匹配事件，
 * 对不上时该节点会永远停在 pending。
 */
const STAGES: ReadonlyArray<{ id: string; name: string; role: string }> = [
  { id: 'supervisor', name: '主管智能体 (Supervisor)', role: '拆解问题意图' },
  { id: 'researcher', name: '调研智能体 (Researcher)', role: '检索私有资料与公开来源' },
  { id: 'analyst', name: '分析智能体 (Analyst)', role: '交叉核对证据' },
  { id: 'writer', name: '撰写智能体 (Writer)', role: '撰写研究报告' },
  { id: 'critic', name: '审阅智能体 (Critic)', role: '校验引用忠实度' },
]

/** 每次提问的初始 DAG：全部 pending，耗时显示为排队中。 */
export function initialNodes(): AgentNode[] {
  return STAGES.map((s) => ({
    id: s.id,
    name: s.name,
    role: s.role,
    detail: '',
    note: '',
    lifecycle: 'pending' as NodeLifecycle,
    latency: '排队中',
    elapsedBaseMs: 0,
    segmentStartedAt: null,
  }))
}

/** DAG 头部标题。后端没有 pipeline 名这个概念（不是 LangGraph 编排），故固定。 */
export const DAG_TITLE = '智能体执行有向无环图 (DAG)'

export interface SlashCommand {
  cmd: string
  description: string
  /**
   * 展开后的提问前缀。选中后直接填进输入框，用户在其后接着打主题。
   *
   * 后端不认斜杠指令（`AskRequest` 只校验非空字符串），原样发过去就是
   * 一个以 `/` 开头的问题。所以这里做的是「模板展开」而非「指令透传」。
   */
  template: string
}

export const SLASH_COMMANDS: SlashCommand[] = [
  {
    cmd: '/research',
    description: '深度检索，列出关键事实与来源',
    template: '请围绕以下主题做深度检索，列出关键事实与各自的来源：',
  },
  {
    cmd: '/compare',
    description: '以对照矩阵比较关键参数',
    template: '请以对照矩阵的形式比较以下主题的关键参数，逐项给出差异：',
  },
  {
    cmd: '/summarize',
    description: '压缩为核心结论摘要',
    template: '请把以下主题压缩成核心结论摘要，不超过 5 条：',
  },
]

/**
 * 开流**之前**的 HTTP 失败 → 错误码与是否值得重试。
 *
 * ## 为什么要一张显式表
 *
 * 开流之前后端还没发过 error 帧，前端拿不到后端的 code。但错误码不能
 * 凭空造——`http_503` 这种码在后端监控里永远查不到。
 *
 * 所以按 HTTP 状态码映射到**后端用的同一套 code**：后端
 * `app/gateway/research.py` 里「并发已满」是 503、「模型未配置」是 400
 * （配置问题重试无用，不能跟「稍后重试」的 503 混同）。
 *
 * 落在后端 code 命名空间之外的两个（`network_error`、`http_error`）
 * 是真的没有后端对应物——连接在到达服务端前就断了。
 */
export const HTTP_ERROR_CODES: Readonly<Record<number, { code: string; retryable: boolean }>> = {
  400: { code: 'llm_not_configured', retryable: false },
  401: { code: 'unauthorized', retryable: false },
  403: { code: 'forbidden', retryable: false },
  413: { code: 'payload_too_large', retryable: false },
  415: { code: 'unsupported_media_type', retryable: false },
  422: { code: 'validation_error', retryable: false },
  429: { code: 'rate_limited', retryable: true },
  500: { code: 'server_error', retryable: true },
  502: { code: 'bad_gateway', retryable: true },
  503: { code: 'llm_unavailable', retryable: true },
  504: { code: 'gateway_timeout', retryable: true },
}

/** 状态码不在表里时的兜底。 */
export const HTTP_ERROR_FALLBACK = { code: 'http_error', retryable: true } as const
