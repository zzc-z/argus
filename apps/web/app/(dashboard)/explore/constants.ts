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
  lifecycle: NodeLifecycle
  /** 格式化好的耗时文案（"1.2s" / "排队中"）。 */
  latency: string
}

export interface ToolCall {
  id: string
  name: string
  /** 截断过的入参预览。 */
  args: string
  duration: string
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
    lifecycle: 'pending' as NodeLifecycle,
    latency: '排队中',
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
