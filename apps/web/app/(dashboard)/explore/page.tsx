'use client'

/**
 * /explore — Argus 多智能体深度研究控制台。
 *
 * 配色全部走项目 Material 3 token（`--token-surface-*` / `--token-primary`），
 * 跟随全局主题切换。UI 主字体用 Inter，通过 next/font/google 按页面加载。
 *
 * 顶栏与侧边栏来自 `(dashboard)/layout.tsx`，本页不再自带一套。
 *
 * 布局（中心栏 + 可折叠检查器）：
 *   ┌─────────────────────────────────┬────────────┐
 *   │ 页面标题栏 + 检查器开关          │            │
 *   ├─────────────────────────────────┤ Inspector  │
 *   │ Center column (920px)           │ (380px)    │
 *   │  ├ AgentDAG (5 nodes)           │ collapsible│
 *   │  ├ 收尾统计 + FaithfulnessPanel │            │
 *   │  ├ StreamingReport (正文)       │            │
 *   └─────────────────────────────────┴────────────┘
 *           ┌──────────────────────────┐
 *           │ PromptInput (48px fixed) │
 *           └──────────────────────────┘
 *
 * 页面无任何演示数据：节点名册来自 `constants.ts`（后端 Stage 枚举的镜像），
 * 其余一切——正文、引用、工具轨迹、校验结论——都来自 `/research/ask` 的
 * SSE 流或 chunks 接口。
 */

import {
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type Dispatch,
  type SetStateAction,
} from 'react'
import Link from 'next/link'
import { useSearchParams } from 'next/navigation'

import { AgentDAG } from './components/AgentDAG'
import { StreamingReport } from './components/StreamingReport'
import {
  InspectorDrawer,
  buildNodePayload,
  buildCitationPayload,
  emptyInspectorPayload,
  type InspectorPayload,
  type SourceTextState,
} from './components/InspectorDrawer'
import {
  FaithfulnessPanel,
  FaithfulnessAbort,
  FaithfulnessPending,
} from './components/FaithfulnessPanel'
import { PromptInput } from './components/PromptInput'
import { ResumeRunCard } from './components/ResumeRunCard'
import { ApiError, type SseEvent } from '@/lib/api/client'
import { clearChunkCache, fetchChunks } from '@/lib/api/sources'
import { parseEvent } from '@/lib/api/sse'
import { useStickToBottom } from '@/lib/hooks/useStickToBottom'
import { IconSpan } from '@/components/common/IconSpan'
import type {
  DeltaEventV,
  DoneEventV,
  ErrorEventV,
  FaithfulnessEventV,
  NodeEventV,
  ReferenceEventV,
  RunEventV,
  ToolCallEventV,
} from '@/lib/api/sse'
import {
  HTTP_ERROR_CODES,
  HTTP_ERROR_FALLBACK,
  initialNodes,
  SLASH_COMMANDS,
  type AgentNode,
  type Citation,
  type NodeLifecycle,
  type SlashCommand,
  type ToolCall,
} from './constants'
import {
  getLastRunSnapshot,
  parseLastRun,
  subscribeLastRun,
  writeLastRun,
} from './lastRun'
import { writeActiveRunId } from './activeRun'
import { useRunSession } from './useRunSession'
import { formatElapsed } from './formatElapsed'
import styles from './page.module.css'

/**
 * 运行态。刻意不含 'error'——错误由 `errorInfo` 单独承担。
 * 塞进 runState 会让「跑完了但出错了」和「跑完了正常」变成同一个值，
 * 报告区就分不清该不该显示结果。
 */
type RunState = 'idle' | 'running' | 'completed'

/**
 * 一次错误的完整信息。
 *
 * 形状与后端的 `ErrorEventV` 完全一致——流内错误直接用它，开流前的
 * 失败（HTTP 层 / 网络层）由本地造一个同形状的。用类型别名而不是
 * 另立一个 interface：字段一旦漂移，两处就得分头改。
 *
 * `code` 是后端的机器可读错误码（如 `llm_stream_interrupted`），
 * 显示出来让用户能精确反馈问题，也让「连接中断」和「key 失效」在
 * 界面上可区分——两者的处置完全不同（等 vs 改配置）。
 */
type ErrorInfo = ErrorEventV

/**
 * 把一次工具调用的首帧转成 InspectorDrawer 要的展示态。
 *
 * 只有 start 帧带 `tool_input`——后端在开始时把参数带上，end 帧的空对象
 * 是「结束帧不带参数」而非「参数为空」。
 */
function toToolCall(v: ToolCallEventV): ToolCall {
  return {
    id: v.call_id,
    name: v.name,
    args: JSON.stringify(v.tool_input).slice(0, 120),
    duration: '执行中…',
    // start 帧还没有结果——ok 留 null 表示「还在跑」，不是「成功」。
    // 后端保证 start 先发，所以这里正常只会看到 start 帧；仍按帧里的
    // 值取，是为了让 end 帧先到时（理论情况）也不丢失败标记。
    ok: v.phase === 'end' ? v.ok : null,
    preview: v.phase === 'end' ? v.preview : '',
    // 特殊情况（资料被跳过）不是失败，但用户有权知道——只埋在 preview 里
    // 等于没说。
    errorCode: v.phase === 'end' ? (v.error_code ?? '') : '',
  }
}

/**
 * 把后端 node 事件合并到前端 AgentNode 上。
 *
 * `detail` 存进行时的描述，节点跑完后后端发 completed 且 detail 为空串，
 * 此时回落到静态 `role`——「正在检索与取证」配着完成勾是错的。
 *
 * `note` 存节点的产出摘要，只在完成帧里有值。
 */
function applyNode(node: AgentNode, nv: NodeEventV, receivedAt: number): AgentNode {
  const isActive = nv.lifecycle === 'active'
  return {
    ...node,
    detail: nv.detail,
    note: nv.note ?? node.note,
    lifecycle: nv.lifecycle as NodeLifecycle,
    // **耗时只在完成时用后端的权威值**。运行中显示固定的「运行中」——
    // 实时秒数由 AgentDAG 自己按 elapsedBaseMs 算，不走这里（避免每秒
    // setState 整个 nodes 数组）。
    latency: isActive
      ? '运行中'
      : nv.elapsed_ms != null
        ? formatElapsed(nv.elapsed_ms)
        : node.latency,
    // **本段开始前的累计耗时**。实时秒数的基线——researcher 分多段跑时，
    // 用户看到的秒数要连续增长，而不是每段从 0 开始跳。
    elapsedBaseMs: isActive ? (nv.elapsed_ms ?? 0) : node.elapsedBaseMs,
    // 本段的起点。收到 active 帧的时刻 ≈ 后端激活该节点的时刻
    // （差一个网络往返，对秒级显示无影响）。
    segmentStartedAt: isActive ? receivedAt : node.segmentStartedAt,
  }
}

/**
 * 引用校验的四态。
 *
 * 单独定义而不是在 `RunHandlers` 与 `useState` 各写一遍：`Dispatch<A>`
 * 赋给 `Dispatch<B>` 要求 B 可赋给 A，**只往其中一份加成员时 tsc 不报错**
 * （约束方向是单向的），契约会悄悄变窄。
 */
type FaithfulnessState =
  | { kind: 'idle' }
  | { kind: 'pending' }
  | { kind: 'done'; report: FaithfulnessEventV }
  | { kind: 'abort' }

/** 一轮研究的状态写入器。由 `applyEvent` / `resetForRun` / `settleFaithfulness` 调用。 */
type RunHandlers = {
  setNodes: Dispatch<SetStateAction<AgentNode[]>>
  setStreamedText: Dispatch<SetStateAction<string>>
  setErrorInfo: Dispatch<SetStateAction<ErrorInfo | null>>
  setSummary: Dispatch<SetStateAction<DoneEventV | null>>
  setRunState: Dispatch<SetStateAction<RunState>>
  setFaithfulness: Dispatch<SetStateAction<FaithfulnessState>>
  setToolCalls: Dispatch<SetStateAction<ToolCall[]>>
  setCitations: Dispatch<SetStateAction<Citation[]>>
  setQuestion: Dispatch<SetStateAction<string>>
  setInspectorPayload: Dispatch<SetStateAction<InspectorPayload>>
  /** 作废在飞的原文请求并清空原文区。每轮开跑时调用。 */
  invalidateSourceText: () => void
  /**
   * 本轮的问题原文。
   *
   * 是**函数**而不是字符串：``done`` 事件到达时要把它写进「上次研究」的
   * 本地记录，而重连时问题原文要等**第一帧**（run 帧）才到——那时
   * 直接读捕获的快照会是空串。函数让读取发生在真正需要的那一刻。
   */
  currentQuestion: () => string
  /**
   * 记下本轮的问题（state + ref）。
   *
   * 拆成两个 setter 是因为「写 state」与「写 ref」的时机不同：ref 必须
   * 同步更新（``done`` 事件紧接着就要读它），state 的更新是异步的。
   */
  setCurrentQuestion: (question: string) => void
}

/**
 * 把一次工具调用的两帧合并成一条展示记录。
 *
 * 后端把一次调用拆成 start / end 两段发，start 先占位显示「执行中…」，
 * end 到达时用真实耗时覆盖同一 call_id。start 一定先于 end（后端先发 start
 * 再执行工具），所以找不到已有记录就一定是首帧。
 *
 * **参数只能取自 start 帧**：end 帧的 `tool_input` 是空对象（后端只在
 * 开始时带参数）。end 帧到达时若整条覆盖过去，入参就变成 `{}`——参数
 * 恰好是工具轨迹最该展示的东西，丢了它这一栏就只剩一个函数名。
 */
function mergeToolCall(prev: ToolCall[], tv: ToolCallEventV): ToolCall[] {
  const i = prev.findIndex((c) => c.id === tv.call_id)
  if (i < 0) return [...prev, toToolCall(tv)]
  const existing = prev[i]
  if (existing === undefined) return prev
  const next = [...prev]
  next[i] = {
    ...existing,
    name: tv.name,
    duration:
      tv.phase === 'end' ? formatElapsed(tv.elapsed_ms) : existing.duration,
    // ok / preview 只在 end 帧有值。失败必须显出来——一次失败的
    // local_search 与一次成功的，在轨迹表里长得一模一样（只有耗时不同），
    // 用户会以为资料真的查过了，而其实那一路整个断掉了。
    ok: tv.phase === 'end' ? tv.ok : existing.ok,
    preview: tv.phase === 'end' ? tv.preview : existing.preview,
  }
  return next
}

/**
 * 把一帧 SSE 落到 state 上。
 *
 * 提出组件外是因为它自成一块——除 `invalidateSourceText` 外只碰传入的
 * setter，与 `run` 的其余逻辑无耦合。内联在 `run` 里会让那个函数超过
 * CONVENTIONS §3 的 50 行上限。
 */
function applyEvent(event: SseEvent, h: RunHandlers): void {
  try {
    applyEventInner(event, h)
  } catch (err) {
    // 畸形帧（缺字段、类型不对）不能让整页崩掉。抛出去会白屏，
    // 用户既看不到已生成的正文，也看不到任何错误信息——比丢一帧
    // 严重得多。降级成一条错误信息，已有的内容照样能看。
    h.setErrorInfo({
      code: 'malformed_event',
      message: `收到格式异常的事件帧（${event.type}），已忽略：${err instanceof Error ? err.message : String(err)}`,
      retryable: true,
    })
  }
}

/**
 * 真正落帧的逻辑。单独一层是为了让 `applyEvent` 能统一兜住畸形帧。
 */
function applyEventInner(event: SseEvent, h: RunHandlers): void {
  switch (event.type) {
    case 'run': {
      // 第一帧：这次研究的 run id + 问题原文。
      //
      // run id 的**权威在 URL**（`useRunSession` 负责写进去）。这里存一份
      // 到 localStorage 只是在「无 id 时找回这一轮」用（见 activeRun.ts）。
      const run = parseEvent<RunEventV>(event)
      writeActiveRunId(run.run_id)
      // **重置界面放在这里**，而不是在挂载 / 重连之前。
      //
      // 第一帧天然标记「新的一轮开始了」——之后的 delta、node、reference
      // 都是这一轮的产物。放在这里清一次，重连时收到的回放就会把界面
      // 重新填满（旧内容不会残留）。
      //
      // 为什么不放在 effect 里：effect 里同步 setState 会触发级联渲染
      // （`react-hooks/set-state-in-effect` 规则），而且那一刻还不知道
      // 要接的是哪一轮。
      //
      // 幂等：``run`` 回调里也调了一次 resetForRun（那里是为了立刻把
      // 运行态标成 running、禁掉输入框，防重复提交）。两次调用的效果
      // 相同 —— 第二次是「已经 running 的那一轮」被重置成同样的值。
      resetForRun(h, run.question)
      break
    }
    case 'node': {
      const nv = parseEvent<NodeEventV>(event)
      // 运行时校验（``parseEvent`` 只是编译期断言，见 sse.ts 的注释）。
      // 畸形帧要在这里变成一条错误提示，而不是让 React 在渲染阶段
      // 读 undefined 的字段——那会让整个页面白屏。
      if (!nv || typeof nv !== 'object' || typeof nv.node_id !== 'string') {
        throw new Error('node 帧缺少 node_id 字段')
      }
      // 先把字段取出来再进 state updater。updater 是 React 在**渲染
      // 阶段**执行的，跑在 applyEvent 的 try 之外——在里面读
      // ``nv.node_id`` 遇到畸形帧就是白屏，而不是一条错误提示。
      //
      // ``receivedAt`` 同理：``Date.now()`` 是 impure 调用，在渲染期
      // 调用会被 React Compiler 的 purity 规则判错。所以在这里
      // （事件处理期，不是渲染期）取好时刻再传进去。
      const nodeId = nv.node_id
      const receivedAt = Date.now()
      h.setNodes((prev) => prev.map((n) => (n.id === nodeId ? applyNode(n, nv, receivedAt) : n)))
      break
    }
    case 'delta': {
      const delta = parseEvent<DeltaEventV>(event)
      // reset：流被掐断后整轮重发，已收到的正文作废。
      // 不清零的话用户会看到同一段正文出现两遍（前半截是断流前的、
      // 后半截是重发后的）。
      if (delta.reset) {
        h.setStreamedText('')
        break
      }
      h.setStreamedText((prev) => prev + delta.text)
      break
    }
    case 'error': {
      const err = parseEvent<ErrorEventV>(event)
      h.setErrorInfo({
        code: err.code,
        message: err.message,
        retryable: err.retryable,
      })
      break
    }
    case 'done': {
      const done = parseEvent<DoneEventV>(event)
      h.setSummary(done)
      h.setRunState('completed')
      // done 先于校验帧发出（见 FaithfulnessPanel 的模块注释），所以
      // 这里把校验切到 pending 而不是等 faithfulness 到了才显示。
      h.setFaithfulness({ kind: 'pending' })
      // 记下「上次的研究」。只记 report_id 非 null 的——没有落盘就没有
      // 可恢复的东西，记一条指向不存在报告的记录只会让入口点进去 404。
      if (done.report_id != null) {
        writeLastRun({
          reportId: done.report_id,
          question: h.currentQuestion(),
          sessionId: done.session_id,
          savedAt: new Date().toISOString(),
        })
      }
      break
    }
    case 'faithfulness':
      h.setFaithfulness({ kind: 'done', report: parseEvent<FaithfulnessEventV>(event) })
      break
    case 'tool_call':
      h.setToolCalls((prev) => mergeToolCall(prev, parseEvent<ToolCallEventV>(event)))
      break
    case 'reference': {
      // 整体替换而非 append：后端 ReferenceTable.all 每次下发的是
      // 已编号的全表，append 会让编号重复。
      //
      // **不需要作废在飞的原文请求**：后端 ReferenceTable 按 chunk_id 记账
      // （`citation.py` 的 `_numbers`），编号只增不减、跨轮稳定，同一个
      // `[n]` 永远指向同一个 chunk。早期版本这里假设「重新编号」并清空原文区，
      // 那个前提是错的——真实后果是流式中途用户点开的角标被无端抹掉。
      h.setCitations(parseEvent<ReferenceEventV>(event).references)
      break
    }
    default:
      break
  }
}

/**
 * 流结束时收尾校验状态。
 *
 * 判据是**当前是不是 pending**：只要结论已经收到（kind === 'done'），
 * 正常路径下这里就是 no-op，两条终止路径共用以保证行为对称。
 *
 * 会停在 pending 的路径有两条：
 *  1. done 与 faithfulness 之间有最长约 6 分钟的零字节静默窗口
 *     （`llm.py` 的 MODEL_TIMEOUT_SECONDS=120 × 3 次尝试）。
 *     窗口内**不发任何字节**，中间层的空闲超时（代理 / 网关）会掐断连接。
 *     本仓没有部署配置，具体阈值取决于部署形态。[未核实]
 *  2. `llm_unavailable` / `empty_response` 两条错误路径（`agent.py`
 *     在 yield 完 done + ErrorEvent 后直接 return，从不进 `_settle`）。
 *
 * 两条都不涉及 judge 调用本身失败——那个被 `faithfulness.py` 的
 * try/except 吞成 skipped 报告，帧照发，走的是 `done` 分支。
 *
 * 收尾成 `abort` 而不是 `idle`（即「不渲染面板」）是刻意的：面板空白
 * 与「全部通过」在视觉上无法区分，而这里真实发生的是「没跑完」。
 */
function settleFaithfulness(h: RunHandlers): void {
  h.setFaithfulness((prev) => (prev.kind === 'pending' ? { kind: 'abort' } : prev))
}

/** 一次提问开始前把所有单次运行的产物清干净。 */
function resetForRun(h: RunHandlers, question: string): void {
  h.setNodes(initialNodes())
  h.setStreamedText('')
  h.setErrorInfo(null)
  h.setSummary(null)
  h.setFaithfulness({ kind: 'idle' })
  h.setCurrentQuestion(question)
  h.setRunState('running')
  // 引用表和工具轨迹一样属于单次运行的产物，重问时必须清空——否则上一轮
  // 的编号会跟这一轮的正文对不上。
  h.setCitations([])
  h.setToolCalls([])
  // 检查器载荷也是单次运行的产物：上一轮点开的节点/引用带着旧 latency 与
  // 旧 chunk_id，留着会让用户对着上一轮的数据看这一轮的正文。
  h.setInspectorPayload(emptyInspectorPayload())
  // 令牌自增作废旧请求：上一轮点开的原文属于上一轮的 chunk_id，
  // 而 chunk_id 是自增主键，新一轮很可能命中不同的 id。令牌拦的是
  // 「写进 state」，abort 拦的是「继续下载」——长文档的 payload 有十几 MB，
  // 光靠令牌它会一路跑到完。
  clearChunkCache()
  h.invalidateSourceText()
}

export default function ExplorePage() {
  const [inspectorOpen, setInspectorOpen] = useState(false)
  const [inspectorPayload, setInspectorPayload] = useState<InspectorPayload>(emptyInspectorPayload)

  const [promptValue, setPromptValue] = useState('')
  // Popover 仅在输入恰好是单个 '/' 时显示；输入更多字符即隐藏。
  const slashVisible = promptValue === '/'

  // 运行态：驱动 DAG 节点推进 + StreamingReport 尾段打字机。
  const [runState, setRunState] = useState<RunState>('idle')
  const [nodes, setNodes] = useState<AgentNode[]>(initialNodes)
  const [streamedText, setStreamedText] = useState('')
  // 正文增长时自动跟随到底部；用户手动上滚则暂停跟随。
  //
  // **ref 由这里建、传给 hook**（不是 hook 建了再返回）。原因见
  // `useStickToBottom` 的注释：hook 返回一个内嵌 ref 的对象时，
  // ESLint 的 `react-hooks/refs` 规则会把整个返回值当成「可能是个
  // ref」，渲染期读它的任何属性都报错。
  const scrollRef = useRef<HTMLElement | null>(null)
  // 依赖传**正文长度**（单调递增），不传对象——对象每次渲染都是新引用，
  // 跟随逻辑会被反复触发。
  const stick = useStickToBottom(scrollRef, streamedText.length)
  // 错误的完整信息：code + 文案 + 是否值得重试。
  //
  // 刻意不塞进一个字符串：banner 要同时显示「哪一类错误」（code）
  // 和「说了什么」（message），还要按 retryable 决定要不要标
  // 「不可重试」。合成一个字符串就丢了这些信息。
  const [errorInfo, setErrorInfo] = useState<ErrorInfo | null>(null)
  // 收尾统计：done 事件带的 session_id / 耗时 / token 数。
  const [summary, setSummary] = useState<DoneEventV | null>(null)
  // Critic 的引用校验。四态见 `FaithfulnessState`。判别联合而非多个 boolean：
  // 两个 boolean 下 `pending=true && report!==null`（同时声称「进行中」和
  // 「已有结论」）这类自相矛盾的组合是可表示的，画出来必然出错。
  const [faithfulness, setFaithfulness] = useState<FaithfulnessState>({ kind: 'idle' })
  // 当前提问。空态与收尾行都要读它。
  const [question, setQuestion] = useState('')
  // 工具调用轨迹：InspectorDrawer 的「已执行工具调用」区读它。
  const [toolCalls, setToolCalls] = useState<ToolCall[]>([])
  // 引用表：后端 reference 事件下发。未提问时为空，正文里也就没有角标。
  const [citations, setCitations] = useState<Citation[]>([])

  // 上次跑完的研究（存在 localStorage）。切页回来时用它给出「去看报告」
  // 的入口——运行态本身不持久化，但报告是落盘的。
  //
  // 用 `useSyncExternalStore`：localStorage 是**外部系统**，这个 hook 就是
  // 为它设计的。`useState` + `useEffect` 读它会触发 React 的
  // `react-hooks/set-state-in-effect` 规则（级联渲染），而且首帧会先渲染
  // 一遍「没有上次」再跳到「有上次」——闪一下。
  const lastRunSnapshot = useSyncExternalStore(subscribeLastRun, getLastRunSnapshot, () => null)
  const lastRun = useMemo(() => parseLastRun(lastRunSnapshot), [lastRunSnapshot])

  // 原文区：点角标后按 chunk_id 拉全文。三态而非 null——「不显示」与
  // 「加载中」「拉取失败」要显示的东西完全不同，合并成一个值就会把
  // 加载态画成空白、失败态画成「这段资料没有原文」。
  const [sourceText, setSourceText] = useState<SourceTextState>({ kind: 'none' })
  // 原文拉取的竞态令牌。每次点击自增，只有令牌等于当前值的那次响应才允许
  // 写 state——连点两个角标时，先发的请求完全可能后到，不拦住就会把
  // A 的原文画到 B 的编号下面。
  const sourceTextToken = useRef(0)

  // 原文拉取的 AbortController。点角标后拉全文，切换时要取消上一次。
  //
  // 研究流的连接由 `useRunSession` 自己管（它有独立的 controller）——
  // 那条命周期是「一轮研究」，原文拉取是「一次点击」，两者该在不同的
  // 时机取消。共用一个会让重问时把仍在飞的原文请求也 abort 掉（虽然
  // 令牌已经拦住了写 state，但带宽还在白跑，一个长文档的 payload 能有
  // 十几 MB）。
  const sourceAbortRef = useRef<AbortController | null>(null)
  // 输入框的 ref。「新建会话」后要把焦点送过去 —— 用户接着就能输入。
  const promptInputRef = useRef<HTMLInputElement | null>(null)
  // 当前这一轮的问题原文。**放 ref 而不是直接用 state**：``done`` 事件
  // 到达时要把它写进「上次研究」的本地记录，而那时 state 里的值可能
  // 还没更新（setState 是异步的）。ref 是同步的，读到的一定是最新值。
  const questionRef = useRef('')

  /**
   * 造一套事件写入器。
   *
   * 抽出来是因为「问一轮」和「接回一轮」要用**完全相同**的那套写入器——
   * 两处各写一遍的话，节点推进、正文累积、错误收尾迟早会漂移。
   *
   * setXxx 都是稳定引用（React 保证），所以每次新建也不会读到过期值
   * ——它捕获的全是 React 的稳定引用与 useRef 对象。
   */
  const buildHandlers = useCallback((): RunHandlers => {
    return {
      setNodes,
      setStreamedText,
      setErrorInfo,
      setSummary,
      setRunState,
      setFaithfulness,
      setToolCalls,
      setCitations,
      setInspectorPayload,
      setQuestion,
      invalidateSourceText: () => {
        sourceAbortRef.current?.abort()
        sourceTextToken.current += 1
        setSourceText({ kind: 'none' })
      },
      currentQuestion: () => questionRef.current,
      setCurrentQuestion: (question: string) => {
        // ref 同步更新——``done`` 事件紧接着就要读它，而 state 的更新
        // 是异步的，那时读 state 拿到的还是旧值。
        questionRef.current = question
        setQuestion(question)
      },
    }
  }, [])

  /**
   * 把「HTTP 层的失败」变成一条错误信息。
   *
   * **已有 errorInfo 时不覆盖**——后端可能已经下发了 error 帧（带具体 code
   * 与 retryable），而流是在那之后才断的。覆盖掉会把「模型连接中断」换成
   * 笼统的「network_error」，正好丢掉我们要保留的信息。
   *
   * 用函数式更新读 prev：捕获的 setter 读不到闭包外的最新 state。
   */
  const reportStreamError = useCallback((err: unknown) => {
    setErrorInfo((prev) => {
      if (prev) return prev
      // HTTP 层的错（后端 detail 已在 ApiError.message 里）或网络层的错。
      // 两者都没有后端的 error 帧——开流之前后端还没发过。
      const status = err instanceof ApiError ? err.status : null
      const mapped = status != null ? HTTP_ERROR_CODES[status] : undefined
      return {
        code: mapped?.code ?? HTTP_ERROR_FALLBACK.code,
        message: err instanceof Error ? err.message : '连接失败',
        retryable: mapped?.retryable ?? HTTP_ERROR_FALLBACK.retryable,
      }
    })
    // 守卫与 resolve 分支对称：结论已经收到时不能因为连接随后出错就清空。
    setFaithfulness((prev) => (prev.kind === 'pending' ? { kind: 'abort' } : prev))
    setRunState('completed')
  }, [])

  // 会话 hook 要用 buildHandlers，但 buildHandlers 定义在后面会形成
  // 循环依赖。用 ref 破环：hook 的回调读 ref.current（总是最新的）。
  //
  // **ref 只在 effect 里写** —— 渲染期间写 ref 是 React 明令禁止的
  // （`react-hooks/refs` 规则：渲染期间的 ref 值不可靠，React 可能
  // 丢弃那次渲染）。
  const handlersRef = useRef<RunHandlers | null>(null)
  useEffect(() => {
    handlersRef.current = buildHandlers()
  })

  const session = useRunSession({
    onEvent: useCallback((event: SseEvent) => {
      const h = handlersRef.current
      if (h) applyEvent(event, h)
    }, []),
    onError: reportStreamError,
  })

  const handleSelectNode = useCallback(
    (node: AgentNode) => {
      setInspectorOpen(true)
      setInspectorPayload(buildNodePayload(node))
      // 令牌要自增 + 请求要 abort，两件事缺一不可：
      // 令牌拦住「响应写进 state」，abort 拦住「继续下载」。少了后者，
      // 「点角标 → 点 DAG 节点」之后那个请求仍会跑完全量 payload。
      sourceAbortRef.current?.abort()
      sourceTextToken.current += 1
      setSourceText({ kind: 'none' })
    },
    [],
  )

  const handleSelectCitation = useCallback(
    async (citation: Citation) => {
      setInspectorOpen(true)
      setInspectorPayload(buildCitationPayload(citation))

      const token = (sourceTextToken.current += 1)
      sourceAbortRef.current?.abort()
      const controller = new AbortController()
      sourceAbortRef.current = controller
      setSourceText({ kind: 'loading' })
      try {
        const chunks = await fetchChunks(citation.source_id, controller.signal)
        if (sourceTextToken.current !== token) return
        const chunk = chunks.find((c) => c.id === citation.chunk_id)
        if (!chunk) {
          // 列表里有但 id 对不上：引用表与库已经不一致（多半是重传过资料）。
          // 说「已被重新摄取」而不是「不存在」——后者听起来像数据丢了。
          setSourceText({ kind: 'error', message: '该切片已不存在，资料可能已被重新摄取' })
          return
        }
        // 两个都显示，不做取舍。PDF 的 page 是真实页码（parser.py:77 取
        // index+1），而 PDF 是这个功能的主要场景——把它改叫「第 N 段」会让
        // 用户拿着报告去找「第 3 页」时找不到。纯文本的 page 来自 \f 分页
        // （parser.py:137），叫「页」同样准确；HTML 的 page 为 null，只显示块号。
        const label =
          chunk.page != null
            ? `第 ${chunk.page} 页 · 第 ${chunk.chunk_index + 1} 块`
            : `第 ${chunk.chunk_index + 1} 块`
        setSourceText({ kind: 'ready', title: label, body: chunk.content })
      } catch (err) {
        if (sourceTextToken.current !== token) return
        if (err instanceof DOMException && err.name === 'AbortError') return
        setSourceText({
          kind: 'error',
          message: err instanceof Error ? err.message : '未知错误',
        })
      }
    },
    [],
  )

  const handleToggleInspector = useCallback(() => {
    setInspectorOpen((v) => !v)
  }, [])

  const handleCloseInspector = useCallback(() => {
    setInspectorOpen(false)
  }, [])

  /**
   * 发起一轮研究。
   *
   * 连接与 run id 的管理都在 `useRunSession` 里（它负责把 run id 写进
   * URL）。这里只管「收到帧之后怎么落到 state 上」。
   */
  const run = useCallback(
    async (question: string) => {
      questionRef.current = question
      const handlers = buildHandlers()

      resetForRun(handlers, question)

      await session.start(question, (event) => {
        applyEvent(event, handlers)
        if (event.type === 'done') {
          settleFaithfulness(handlers)
          setRunState((prev) => (prev === 'running' ? 'completed' : prev))
        }
      })
    },
    [buildHandlers, session],
  )

  const handleSlashSelect = useCallback((cmd: SlashCommand) => {
    setPromptValue(`${cmd.template} `)
  }, [])

  /**
   * 「新建会话」：回到空白状态。
   *
   * ## 为什么需要
   *
   * 主流项目（ChatGPT / Claude）都有这个动作。没有它，用户想换个问题
   * 就只能「在当前这轮里重问」——旧那轮的正文还挂在页面上，而 URL 里
   * 的 run id 指向的也是旧那轮。
   *
   * ## 做了什么
   *
   * 1. 停掉当前这一轮（如果还在跑）—— 它会继续烧 token、占并发槽位
   * 2. URL 上的 run 参数去掉 → 当前页面变成一个「空白会话」
   * 3. 界面清空（正文、DAG、引用、统计、错误）
   * 4. 聚焦输入框 —— 用户接着就能输入下一个问题
   *
   * ## 已生成的半截报告会落盘
   *
   * 服务端行为：取消时把已生成的正文落盘（标 truncated）。用户能在
   * 历史报告里看到它 —— 与主流项目一致（ChatGPT 的停止按钮）。
   */
  const handleNewSession = useCallback(() => {
    void (async () => {
      await session.newSession()
      // 清界面。**不清的话旧那轮的正文还挂在页面上**，而 URL 已经
      // 指向一个空白会话 —— 两边不一致。
      const handlers = buildHandlers()
      resetForRun(handlers, '')
      setRunState('idle')
      setNodes(initialNodes())
      setQuestion('')
      setErrorInfo(null)
      setSummary(null)
      setFaithfulness({ kind: 'idle' })
      setCitations([])
      setToolCalls([])
      setInspectorPayload(emptyInspectorPayload())
      clearChunkCache()
      sourceAbortRef.current?.abort()
      sourceTextToken.current += 1
      setSourceText({ kind: 'none' })
      // 聚焦输入框 —— 用户接着就能输入下一个问题。
      promptInputRef.current?.focus()
    })()
  }, [buildHandlers, session])

  const handlePromptSubmit = useCallback(
    (value: string) => {
      const trimmed = value.trim()
      if (!trimmed) return
      if (runState === 'running') return
      setPromptValue('')
      void run(trimmed)
    },
    [runState, run],
  )

  // 报告页「继续推演」带 ?question= 跳过来时预填输入框。
  const handlePrefillQuestion = useCallback((value: string) => {
    setPromptValue(value)
  }, [])

  // 「重新提问」：把上次的问题填回输入框。
  //
  // **不自动提交**——理由同 QuestionPrefill：自动提交等于替用户花一次
  // 真金白银的模型调用，且不可撤销。
  const handleReask = useCallback((value: string) => {
    setPromptValue(value)
  }, [])

  // 卸载时中断挂起的原文请求，否则组件没了 fetch 还在跑。
  //
  // 研究流的连接由 `useRunSession` 自己清理（它有独立的 controller）。
  //
  // **中断订阅不等于终止生成**——生成在服务端跑着（后端的 run 注册表），
  // 断开只是不再收帧。用户切回来时靠 URL 上的 run id 接回去。
  useEffect(
    () => () => {
      sourceAbortRef.current?.abort()
    },
    [],
  )

  // 挂载时接回上一轮；URL 上的 run id 变了也重连。
  //
  // **依赖 `session.runId`**：run id 在 URL 上，用户换一个链接（分享来的、
  // 或者浏览器前进后退）就该接那一轮。依赖空数组的话只在挂载时接一次。
  //
  // ## 为什么不用 ref 守卫「只跑一次」
  //
  // StrictMode 下 effect 会 setup → cleanup → setup 跑两遍（开发模式的
  // 刻意行为，用来暴露副作用没清理干净的问题）。用 ref 守卫跳过第二次
  // 反而会**弄坏它**：第一次的连接在 cleanup 里被 abort 了，第二次又被
  // 守卫跳过——用户看到一片空白。
  //
  // `connect` 本身是幂等的：它先 abort 掉上一个订阅、再重新订阅。重跑
  // 一次的结果是「干净地重连一遍」，不会让正文重复（reset 之后服务端
  // 从头回放）。
  useEffect(() => {
    // 无 id 时 hook 会自己问后端「我最近一轮是什么」（用户从别的页面直接
    // 点进 /explore 的情况），有就把 URL 补上再接回。
    session.connect(session.runId)
    // 依赖里放**整个 session**（不是 runId）—— 但这**安全**，因为
    // `useRunSession` 把返回值 memo 了，身份只在内容真的变了时才变。
    //
    // 这里曾经是 bug 的根源：hook 还没 memo 时，session 每次渲染都是新
    // 对象 → effect 每次渲染都重跑 → 每次都重连 → 服务端把缓冲里的正文
    // **一次性回放** → 用户看到「一下全出」，连接被反复重建 → 页面卡。
    //
    // 所以真正的前提是「hook 的返回值必须 memo」——那条在 hook 里，
    // 注释也写在那儿。
  }, [session])

  const reportId = summary?.report_id ?? null

  return (
    <div className={styles.shell}>
      <div className={styles.pageBar}>
        <span className={styles.pageTitle}>研究控制台 / Explore</span>
        <div className={styles.pageBarActions}>
          {/* 「新建会话」：主流页面的基本动作（ChatGPT / Claude 都有）。
              没有它，用户想换个问题就只能在当前这轮里重问 —— 旧那轮的
              正文还挂在页面上，URL 里的 run id 也指向旧那轮。

              **只有这一轮存在时才显示** —— 空会话上没有「新会话」可建，
              摆个按钮在那儿是噪声。 */}
          {session.runId && (
            <button
              type="button"
              onClick={handleNewSession}
              className={styles.inspectorToggle}
              title="停掉当前这一轮，回到空白会话"
            >
              <IconSpan name="add" size={16} className={styles.newSessionIcon} />
              <span>新建会话</span>
            </button>
          )}
          <button
            type="button"
            onClick={handleToggleInspector}
            className={styles.inspectorToggle}
            aria-pressed={inspectorOpen}
          >
            {inspectorOpen ? '隐藏检查器' : '显示检查器'}
          </button>
        </div>
      </div>

      <div className={styles.main}>
        {/* Center column: DAG + Streaming Report */}
        <main className={styles.center} ref={scrollRef}>
          <AgentDAG
            onSelectNode={handleSelectNode}
            nodes={nodes}
            elapsed={summary ? `${(summary.elapsed_ms / 1000).toFixed(1)}秒` : undefined}
            tokens={summary ? `${summary.output_tokens} 标记` : undefined}
          />
          {errorInfo && (
            <div role="alert" className={styles.errorBanner}>
              <div className={styles.errorHead}>
                <span className={styles.errorCode}>{errorInfo.code}</span>
                {!errorInfo.retryable && <span className={styles.errorNoRetry}>不可重试</span>}
              </div>
              <p className={styles.errorMessage}>{errorInfo.message}</p>
            </div>
          )}
          {/* 恢复条只在**本轮还没跑**时出现。跑完的当次，summary 行里
              已经有「查看完整报告 ↗」了，两处入口重复。 */}
          {!summary && lastRun && (
            <ResumeRunCard run={lastRun} onReask={handleReask} />
          )}
          {summary && (
            <p className={styles.summary}>
              会话 {summary.session_id.slice(0, 8)} · {summary.turns} 轮 ·{' '}
              {(summary.elapsed_ms / 1000).toFixed(1)} 秒 · 输入 {summary.input_tokens} / 输出{' '}
              {summary.output_tokens} tokens{summary.truncated && ' · 已截断'}
              {reportId != null && (
                <>
                  {' · '}
                  <Link href={`/report/${reportId}`} className={styles.reportLink}>
                    查看完整报告 ↗
                  </Link>
                </>
              )}
            </p>
          )}
          {faithfulness.kind === 'pending' && <FaithfulnessPending />}
          {/* 本轮压根失败时不显示「校验未完成」——那一轮没有报告、没有引用，
              「重试可得到结论」指向一个不存在的问题，而红色横幅已经说清了原因。 */}
          {faithfulness.kind === 'abort' && !errorInfo && <FaithfulnessAbort />}
          {faithfulness.kind === 'done' && <FaithfulnessPanel report={faithfulness.report} />}
          <StreamingReport
            onSelectCitation={handleSelectCitation}
            citations={citations}
            streamedText={streamedText}
            streaming={runState === 'running'}
            query={question || undefined}
          />
          {/* 用户上滚后暂停跟随，给一个回到底部的入口——主流项目
              （ChatGPT / Claude）的标准交互。没有它的话，被推走的
              正文就没有回去的路。 */}
          {stick.paused && (
            <button
              type="button"
              className={styles.scrollToBottom}
              onClick={() => stick.scrollToBottom()}
              aria-label="回到底部"
              title="回到底部"
            >
              <IconSpan name="arrow_downward" size={18} />
            </button>
          )}
        </main>

        {/* Right inspector (collapsible) */}
        <InspectorDrawer
          open={inspectorOpen}
          payload={inspectorPayload}
          toolCalls={toolCalls}
          sourceText={sourceText}
          onClose={handleCloseInspector}
        />
      </div>

      {/* Fixed bottom prompt input */}
      <div className={styles.bottomBar}>
        <div className={styles.bottomInner}>
          <PromptInput
            value={promptValue}
            onChange={setPromptValue}
            onSubmit={handlePromptSubmit}
            slashVisible={slashVisible}
            slashCommands={SLASH_COMMANDS}
            disabled={runState === 'running'}
            onSlashSelect={handleSlashSelect}
            inputRef={promptInputRef}
          />
        </div>
      </div>

      {/* 预填：报告页的「继续推演」带 ?question= 跳过来。
          Suspense 边界包住读 URL 的部分——Next 16 要求 read-URL 的
          Client Component 在边界内，否则整条路由无法静态预渲染。 */}
      <Suspense fallback={null}>
        <QuestionPrefill onFill={handlePrefillQuestion} />
      </Suspense>
    </div>
  )
}

/**
 * 从 URL 的 `?question=` 预填输入框。
 *
 * ## 为什么单独拆一个组件
 *
 * `useSearchParams` 要求组件在 `<Suspense>` 边界内——Next 16 里读 URL 的
 * Client Component 会让整条路由失去静态预渲染能力，`next build` 直接以
 * missing-suspense-with-csr-bailout 失败。把读 URL 的部分隔离到叶子
 * 组件里，边界就只需要包住它一个。
 *
 * ## 为什么**不自动提交**
 *
 * 预填只是把问题放进输入框。用户可能想改、想删、想先看看上下文。
 * 自动提交等于替他花掉一次真金白银的模型调用（一次完整的多轮检索几十秒
 * + 真实 token 花费），且不可撤销。
 */
function QuestionPrefill({ onFill }: { onFill: (value: string) => void }) {
  const params = useSearchParams()
  const question = params.get('question')

  useEffect(() => {
    if (question) onFill(question)
  }, [question, onFill])

  return null
}
