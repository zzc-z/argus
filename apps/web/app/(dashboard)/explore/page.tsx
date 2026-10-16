'use client'

/**
 * /explore — Argus 多智能体深度研究控制台。
 *
 * 设计稿是 argus_2/code.html 的还原，但配色已全部改走项目 Material 3
 * token（`--token-surface-*` / `--token-primary` 等），跟随全局主题切换。
 * UI 主字体用 Inter，通过 next/font/google 按页面加载，不影响其他路由。
 *
 * 顶栏与侧边栏来自 `(dashboard)/layout.tsx`，本页不再自带一套——早期版本
 * 有一根 56px 的深色 TopBar，与 layout 的全局 topbar 叠成两层头部，
 * 内容被顶到视口外。现在只留页面级标题栏（标题 + 检查器开关）。
 *
 * 布局（中心栏 + 可折叠检查器）：
 *   ┌─────────────────────────────────┬────────────┐
 *   │ 页面标题栏 + 检查器开关          │            │
 *   ├─────────────────────────────────┤ Inspector  │
 *   │ Center column (920px)           │ (380px)    │
 *   │  ├ AgentDAG (5 nodes)           │ collapsible│
 *   │  ├ 收尾统计 + FaithfulnessPanel │            │
 *   │  ├ StreamingReport (H1 + prose) │            │
 *   └─────────────────────────────────┴────────────┘
 *           ┌──────────────────────────┐
 *           │ PromptInput (48px fixed) │
 *           └──────────────────────────┘
 */

import { useCallback, useEffect, useRef, useState, type Dispatch, type SetStateAction } from 'react'
import { Inter } from 'next/font/google'

import { AgentDAG } from './components/AgentDAG'
import { StreamingReport } from './components/StreamingReport'
import {
  InspectorDrawer,
  getDefaultInspectorPayload,
  buildNodePayload,
  buildCitationPayload,
  type InspectorPayload,
  type SourceTextState,
} from './components/InspectorDrawer'
import {
  FaithfulnessPanel,
  FaithfulnessAbort,
  FaithfulnessPending,
} from './components/FaithfulnessPanel'
import { PromptInput } from './components/PromptInput'
import { apiStream, type SseEvent } from '@/lib/api/client'
import { clearChunkCache, fetchChunks } from '@/lib/api/sources'
import type {
  DoneEventV,
  FaithfulnessEventV,
  NodeEventV,
  ReferenceEventV,
  ToolCallEventV,
} from '@/lib/api/sse'
import {
  AGENT_NODES,
  CITATIONS,
  type AgentNode,
  type Citation,
  type NodeLifecycle,
  type SlashCommand,
  type ToolCall,
} from './mock'
import styles from './page.module.css'

const inter = Inter({
  subsets: ['latin'],
  display: 'swap',
  weight: ['400', '500', '600'],
})

/** 把所有 agent 节点重置为 pending —— 每次提问都从 0 重新跑。 */
const INITIAL_NODES: AgentNode[] = AGENT_NODES.map((n) => ({ ...n, lifecycle: 'pending' }))

/**
 * 运行态。刻意不含 'error'——错误由 `errorText` 单独承担。
 * 塞进 runState 会让「跑完了但出错了」和「跑完了正常」变成同一个值，
 * 报告区就分不清该不该显示结果。
 */
type RunState = 'idle' | 'running' | 'completed'

/**
 * 把一次工具调用转成 InspectorDrawer 要的展示态。
 *
 * 后端把一次调用拆成两段发（开始时立刻显示「正在搜索」，结束后补耗时），
 * 前端按 call_id 配对：start 建的记录，end 时补齐耗时与成败。
 *
 * `end` 是同一 call_id 的 end 事件；没有就说明还在跑，duration 显示
 * 「执行中…」。start 事件一定存在——后端先发 start 再执行工具。
 */
function toToolCall(v: ToolCallEventV, end?: ToolCallEventV): ToolCall {
  const source = end ?? v
  return {
    id: source.call_id,
    name: source.name,
    args: JSON.stringify(source.tool_input).slice(0, 120),
    duration: end ? `${(source.elapsed_ms / 1000).toFixed(1)}s` : '执行中…',
  }
}

/** 把后端 node 事件合并到前端 AgentNode 上。 */
function applyNode(node: AgentNode, nv: NodeEventV): AgentNode {
  return {
    ...node,
    role: nv.detail || node.role,
    lifecycle: nv.lifecycle as NodeLifecycle,
    latency: nv.elapsed_ms != null ? `${(nv.elapsed_ms / 1000).toFixed(1)}s` : node.latency,
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
  setErrorText: Dispatch<SetStateAction<string | null>>
  setSummary: Dispatch<SetStateAction<DoneEventV | null>>
  setRunState: Dispatch<SetStateAction<RunState>>
  setFaithfulness: Dispatch<SetStateAction<FaithfulnessState>>
  setToolCalls: Dispatch<SetStateAction<ToolCall[]>>
  setCitations: Dispatch<SetStateAction<Citation[]>>
  setCitationsLive: Dispatch<SetStateAction<boolean>>
  setQuestion: Dispatch<SetStateAction<string>>
  /** 作废在飞的原文请求并清空原文区。每轮开跑与收到新 reference 帧时都要调。 */
  invalidateSourceText: () => void
}

/**
 * 把一次工具调用的两帧合并成一条展示记录。
 *
 * 后端把一次调用拆成 start / end 两段发，start 先占位显示「执行中…」，
 * end 到达时用真实耗时覆盖同一 call_id。start 一定先于 end（后端先发 start
 * 再执行工具），所以找不到已有记录就一定是首帧。
 */
function mergeToolCall(prev: ToolCall[], tv: ToolCallEventV): ToolCall[] {
  const merged = toToolCall(tv, tv.phase === 'end' ? tv : undefined)
  const i = prev.findIndex((c) => c.id === tv.call_id)
  if (i < 0) return [...prev, merged]
  const next = [...prev]
  next[i] = merged
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
  const v = event.v
  switch (event.type) {
    case 'node': {
      const nv = v as unknown as NodeEventV
      h.setNodes((prev) => prev.map((n) => (n.id === nv.node_id ? applyNode(n, nv) : n)))
      break
    }
    case 'delta': {
      const dv = v as unknown as { text: string }
      h.setStreamedText((prev) => prev + dv.text)
      break
    }
    case 'error': {
      const ev = v as unknown as { message: string }
      h.setErrorText(ev.message)
      break
    }
    case 'done':
      h.setSummary(v as unknown as DoneEventV)
      h.setRunState('completed')
      // done 先于校验帧发出（见 FaithfulnessPanel 的模块注释），所以
      // 这里把校验切到 pending 而不是等 faithfulness 到了才显示。
      h.setFaithfulness({ kind: 'pending' })
      break
    case 'faithfulness':
      h.setFaithfulness({ kind: 'done', report: v as unknown as FaithfulnessEventV })
      break
    case 'tool_call': {
      h.setToolCalls((prev) => mergeToolCall(prev, v as unknown as ToolCallEventV))
      break
    }
    case 'reference': {
      const rv = v as unknown as ReferenceEventV
      // 整体替换而非 append：后端 ReferenceTable.all 每次下发的是
      // 已编号的全表，append 会让编号重复。
      h.setCitations(rv.references)
      h.setCitationsLive(true)
      // 编号含义变了，在飞的原文请求必须作废。reference 帧一次流里
      // 会发多次（每次工具调用命中就发一帧），重新编号后角标 [1]
      // 指的是另一个 chunk——不失效的话抽屉会给出旧编号的全文，
      // 而正文角标已指向新切片，恰好是这个功能要防的事。
      h.invalidateSourceText()
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
 *     （`llm.py` 的 MODEL_TIMEOUT_SECONDS=120 × 3 次尝试——SDK 的
 *     `range(max_retries + 1)`，实测 `max_retries=2` 是 3 次而非 2 次）。
 *     窗口内**不发任何字节**，中间层的空闲超时（代理 / 网关）会掐断连接。
 *     `[未核实]` 本仓没有部署配置，具体阈值取决于部署形态。
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
  h.setNodes(INITIAL_NODES)
  h.setStreamedText('')
  h.setErrorText(null)
  h.setSummary(null)
  h.setFaithfulness({ kind: 'idle' })
  h.setQuestion(question)
  h.setRunState('running')
  // 引用表和工具轨迹一样属于单次运行的产物，重问时必须清空——否则上一轮
  // 的编号会跟这一轮的正文对不上。
  h.setCitations(CITATIONS)
  h.setCitationsLive(false)
  h.setToolCalls([])
  // 令牌自增作废旧请求：上一轮点开的原文属于上一轮的 chunk_id，
  // 而 chunk_id 是自增主键，新一轮很可能命中不同的 id。令牌拦的是
  // 「写进 state」，abort 拦的是「继续下载」——长文档的 payload 有十几 MB，
  // 光靠令牌它会一路跑到完。
  clearChunkCache()
  h.invalidateSourceText()
}

export default function ExplorePage() {
  const [inspectorOpen, setInspectorOpen] = useState(true)
  const [inspectorPayload, setInspectorPayload] = useState<InspectorPayload>(() =>
    getDefaultInspectorPayload(),
  )

  const [promptValue, setPromptValue] = useState('')
  // Popover 仅在输入恰好是单个 '/' 时显示（设计稿要求）；输入更多字符即隐藏。
  const slashVisible = promptValue === '/'

  // 运行态：驱动 DAG 节点推进 + StreamingReport 尾段打字机。
  const [runState, setRunState] = useState<RunState>('idle')
  const [nodes, setNodes] = useState<AgentNode[]>(INITIAL_NODES)
  const [streamedText, setStreamedText] = useState('')
  const [errorText, setErrorText] = useState<string | null>(null)
  // 收尾统计：done 事件带的 session_id / 耗时 / token 数。
  const [summary, setSummary] = useState<DoneEventV | null>(null)
  // Critic 的引用校验。四态见 `FaithfulnessState`。判别联合而非多个 boolean：
  // 两个 boolean 下 `pending=true && report!==null`（同时声称「进行中」和
  // 「已有结论」）这类自相矛盾的组合是可表示的，画出来必然出错。
  const [faithfulness, setFaithfulness] = useState<FaithfulnessState>({ kind: 'idle' })
  // 当前提问。标题要从它取——后端返回的正文不含标题。
  const [question, setQuestion] = useState('')
  // 工具调用轨迹：InspectorDrawer 的「已执行工具调用」区读它。
  const [toolCalls, setToolCalls] = useState<ToolCall[]>([])
  // 引用表：后端 reference 事件下发。初始给 mock 的 CITATIONS，让未提问
  // 时的静态段落仍有可点角标；一旦流开始就会被真实数据整体替换。
  const [citations, setCitations] = useState<Citation[]>(CITATIONS)
  // 引用表是否已来自真实 reference 事件。mock 的 source_id / chunk_id 全是
  // 假值（17 / 4211），真去拉只会得到 404——于是演示态和真出错在界面上
  // 一模一样，评审时无法区分「这是 mock」和「这是 bug」。
  const [citationsLive, setCitationsLive] = useState(false)

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

  const handleSelectNode = useCallback(
    (node: Parameters<typeof buildNodePayload>[0]) => {
      setInspectorOpen(true)
      setInspectorPayload({ ...buildNodePayload(node), toolCalls })
      // 令牌要自增 + 请求要 abort，两件事缺一不可：
      // 令牌拦住「响应写进 state」，abort 拦住「继续下载」。少了后者，
      // 「点角标 → 点 DAG 节点」之后那个请求仍会跑完全量 payload。
      sourceAbortRef.current?.abort()
      sourceTextToken.current += 1
      setSourceText({ kind: 'none' })
    },
    [toolCalls],
  )

  const handleSelectCitation = useCallback(
    async (citation: Parameters<typeof buildCitationPayload>[0]) => {
      setInspectorOpen(true)
      setInspectorPayload(buildCitationPayload(citation))

      // mock 引用的 source_id 是编出来的，真去拉必然 404。不拦的话，
      // 未提问时的静态段落点角标会显示「原文拉取失败：资料不存在」——
      // 与真出错一模一样，评审时没法分辨。
      if (!citationsLive) {
        sourceTextToken.current += 1
        setSourceText({ kind: 'none' })
        return
      }

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
    [citationsLive],
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

    // setXxx 都是稳定引用（React 保证），所以 `handlers` 每次调用 run 时
    // 新建也不会读到过期值——它捕获的全是 React 的稳定引用与 useRef 对象。
    const handlers: RunHandlers = {
      setNodes,
      setStreamedText,
      setErrorText,
      setSummary,
      setRunState,
      setFaithfulness,
      setToolCalls,
      setCitations,
      setCitationsLive,
      setQuestion,
      invalidateSourceText: () => {
        sourceAbortRef.current?.abort()
        sourceTextToken.current += 1
        setSourceText({ kind: 'none' })
      },
    }

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
      setErrorText(err instanceof Error ? err.message : '连接失败')
      // 守卫与 resolve 分支对称：结论已经收到时不能因为连接随后出错就清空。
      settleFaithfulness(handlers)
      setRunState('completed')
    }
  }, [])

  const handleSlashSelect = useCallback((cmd: SlashCommand) => {
    setPromptValue(`${cmd.cmd} `)
  }, [])

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

  // 卸载时中断挂起的请求，否则组件没了 fetch 还在跑。
  useEffect(
    () => () => {
      abortRef.current?.abort()
      sourceAbortRef.current?.abort()
    },
    [],
  )

  return (
    <div className={`${styles.shell} ${inter.className}`}>
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
        <main className={styles.center}>
          <AgentDAG
            onSelectNode={handleSelectNode}
            nodes={nodes}
            elapsed={summary ? `${(summary.elapsed_ms / 1000).toFixed(1)}秒` : undefined}
            tokens={summary ? `${summary.output_tokens} 标记` : undefined}
          />
          {errorText && (
            <p role="alert" className={styles.errorBanner}>
              {errorText}
            </p>
          )}
          {summary && (
            <p className={styles.summary}>
              会话 {summary.session_id.slice(0, 8)} · {summary.turns} 轮 ·{' '}
              {(summary.elapsed_ms / 1000).toFixed(1)} 秒 · 输入 {summary.input_tokens} / 输出{' '}
              {summary.output_tokens} tokens{summary.truncated && ' · 已截断'}
            </p>
          )}
          {faithfulness.kind === 'pending' && <FaithfulnessPending />}
          {/* 本轮压根失败时不显示「校验未完成」——那一轮没有报告、没有引用，
              「重试可得到结论」指向一个不存在的问题，而红色横幅已经说清了原因。 */}
          {faithfulness.kind === 'abort' && !errorText && <FaithfulnessAbort />}
          {faithfulness.kind === 'done' && <FaithfulnessPanel report={faithfulness.report} />}
          <StreamingReport
            onSelectCitation={handleSelectCitation}
            citations={citations}
            streamedText={streamedText}
            query={question || undefined}
            title={question ? `${question} · 研究报告` : undefined}
          />
        </main>

        {/* Right inspector (collapsible) */}
        <InspectorDrawer
          open={inspectorOpen}
          payload={inspectorPayload}
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
            onSlashSelect={handleSlashSelect}
          />
        </div>
      </div>
    </div>
  )
}
