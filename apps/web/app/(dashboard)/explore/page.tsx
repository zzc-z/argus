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
import { ApiError, apiStream, apiStreamGet, type SseEvent } from '@/lib/api/client'
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
import {
  clearActiveRunId,
  readActiveRunId,
  writeActiveRunId,
} from './activeRun'
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
 */
function applyNode(node: AgentNode, nv: NodeEventV): AgentNode {
  return {
    ...node,
    detail: nv.detail,
    lifecycle: nv.lifecycle as NodeLifecycle,
    latency:
      nv.lifecycle === 'active'
        ? '运行中'
        : nv.elapsed_ms != null
          ? `${(nv.elapsed_ms / 1000).toFixed(1)}s`
          : node.latency,
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
      tv.phase === 'end' ? `${(tv.elapsed_ms / 1000).toFixed(1)}s` : existing.duration,
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
      // 存下 run id，刷新 / 切页之后靠它接回这一轮（服务端持有会话，
      // 生成不会因为连接断开而停）。
      const run = parseEvent<RunEventV>(event)
      writeActiveRunId(run.run_id)
      h.setCurrentQuestion(run.question)
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
      const nodeId = nv.node_id
      h.setNodes((prev) => prev.map((n) => (n.id === nodeId ? applyNode(n, nv) : n)))
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
  // 依赖传**正文长度**（单调递增），不传对象——对象每次渲染都是新引用，
  // 跟随逻辑会被反复触发。
  const stick = useStickToBottom(streamedText.length)
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

  // 中断用的 AbortController：用户重问或卸载页面时取消上一次请求。
  const abortRef = useRef<AbortController | null>(null)
  // 原文拉取单独一个 controller。不复用 abortRef——那个的命周期是「一轮
  // 研究」，原文拉取是「一次点击」，两者该在不同的时机取消。共用一个会让
  // 重问时把仍在飞的原文请求也 abort 掉（虽然令牌已经拦住了写 state，
  // 但带宽还在白跑，一个长文档的 payload 能有十几 MB）。
  const sourceAbortRef = useRef<AbortController | null>(null)
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

  const run = useCallback(async (question: string) => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    questionRef.current = question
    const handlers = buildHandlers()

    resetForRun(handlers, question)
    try {
      await apiStream(
        '/api/v1/research/ask',
        { question },
        (event) => applyEvent(event, handlers),
        controller.signal,
      )
      settleFaithfulness(handlers)
      setRunState((prev) => (prev === 'running' ? 'completed' : prev))
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return
      // 流中断的失败。**已有 errorInfo 时不覆盖**——后端可能已经下发了
      // error 帧（带具体 code 与 retryable），而流是在那之后才断的。
      // 覆盖掉会把「模型连接中断」换成笼统的「network_error」，正好丢掉
      // 我们要保留的信息。
      //
      // 用函数式更新读 prev：handlers 里捕获的是稳定 setter，读不到
      // 闭包外的最新 state。
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
      settleFaithfulness(handlers)
      setRunState('completed')
    }
  }, [buildHandlers])

  /**
   * 接回上一轮还在跑（或刚跑完）的研究。
   *
   * ## 为什么需要
   *
   * 以前生成绑在 HTTP 连接上——刷新、切页、关标签都会**终止生成**，
   * 用户回来只看到一片空白。现在服务端持有会话（后端的 run 注册表），
   * 连接只是订阅者，所以断开了可以接回来。
   *
   * ## 什么时候接
   *
   * 挂载时。本地记着 run id（`activeRun.ts`）就说明有一轮值得接。
   * 接不上（run 过期被清理了）就安静地回到空态——不是错误，只是那一轮
   * 已经不在了。
   */
  const reconnect = useCallback(async () => {
    const runId = readActiveRunId()
    if (!runId) return

    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    const handlers = buildHandlers()
    // 重连时问题原文还没到（它在第一帧里），先清空——第一帧会填上。
    resetForRun(handlers, '')

    try {
      await apiStreamGet(
        `/api/v1/research/runs/${encodeURIComponent(runId)}/stream`,
        (event) => applyEvent(event, handlers),
        controller.signal,
      )
      settleFaithfulness(handlers)
      setRunState((prev) => (prev === 'running' ? 'completed' : prev))
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return
      // 404 = 那一轮已经被 TTL 清理了（30 分钟没碰）。这不是错误——
      // 回到空态即可，用户看到「尚未提问」比看到一条红色横幅合理。
      if (err instanceof ApiError && err.status === 404) {
        clearActiveRunId()
        setRunState('idle')
        setNodes(initialNodes())
        return
      }
      setErrorInfo((prev) => {
        if (prev) return prev
        const status = err instanceof ApiError ? err.status : null
        const mapped = status != null ? HTTP_ERROR_CODES[status] : undefined
        return {
          code: mapped?.code ?? HTTP_ERROR_FALLBACK.code,
          message: err instanceof Error ? err.message : '连接失败',
          retryable: mapped?.retryable ?? HTTP_ERROR_FALLBACK.retryable,
        }
      })
      settleFaithfulness(handlers)
      setRunState('completed')
    }
  }, [buildHandlers])

  const handleSlashSelect = useCallback((cmd: SlashCommand) => {
    setPromptValue(`${cmd.template} `)
  }, [])

  const handlePromptSubmit = useCallback(
    (value: string) => {
      const trimmed = value.trim()
      if (!trimmed) return
      if (runState === 'running') return
      setPromptValue('')
      // 清掉旧的 run id。**必须清**：新 run 的第一帧要等一会儿才到
      // （要走一遍鉴权、建 run、起后台任务），这段时间里本地记的
      // 还是上一轮的 id——用户此时刷新，接回来的是**上一轮**的内容，
      // 看起来像「我刚问的问题没跑」。
      //
      // 后端也会取消上一轮（`cancel_latest_for_user`），两边一致。
      clearActiveRunId()
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

  // 卸载时中断挂起的请求，否则组件没了 fetch 还在跑。
  //
  // **只中断订阅，不终止生成**——生成在服务端跑着（后端的 run 注册表），
  // 断开只是不再收帧。用户切回来时靠 reconnect 接回去。
  useEffect(
    () => () => {
      abortRef.current?.abort()
      sourceAbortRef.current?.abort()
    },
    [],
  )

  // 挂载时接回上一轮。
  //
  // **只在挂载时跑一次**（依赖数组空）。依赖 `reconnect` 会让它在每次
  // 渲染后都重跑——那会不断重置界面、清掉正在显示的正文。
  //
  // ## 为什么不用 ref 守卫「只跑一次」
  //
  // StrictMode 下 effect 会 setup → cleanup → setup 跑两遍（开发模式的
  // 刻意行为，用来暴露副作用没清理干净的问题）。用 ref 守卫跳过第二次
  // 反而会**弄坏它**：第一次的 reconnect 在 cleanup 里被 abort 了，第二次
  // 又被守卫跳过——用户看到一片空白。
  //
  // `reconnect` 本身是幂等的：它先 abort 掉上一个订阅、再
  // `resetForRun` 清空界面，然后重新订阅。重跑一次的结果是「干净地
  // 重连一遍」，不会让正文重复（reset 之后服务端从头回放）。
  useEffect(() => {
    void reconnect()
    // reconnect 是 useCallback([]) 出来的稳定引用，放进依赖里不会让它
    // 反复触发。
  }, [reconnect])

  const reportId = summary?.report_id ?? null

  return (
    <div className={styles.shell}>
      <div className={styles.pageBar}>
        <span className={styles.pageTitle}>研究控制台 / Explore</span>
        <button
          type="button"
          onClick={handleToggleInspector}
          className={styles.inspectorToggle}
          aria-pressed={inspectorOpen}
        >
          {inspectorOpen ? '隐藏检查器' : '显示检查器'}
        </button>
      </div>

      <div className={styles.main}>
        {/* Center column: DAG + Streaming Report */}
        <main className={styles.center} ref={stick.ref}>
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
