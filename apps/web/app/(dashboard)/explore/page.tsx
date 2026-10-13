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
 *   │  ├ StreamingReport (H1 + prose) │            │
 *   └─────────────────────────────────┴────────────┘
 *           ┌──────────────────────────┐
 *           │ PromptInput (48px fixed) │
 *           └──────────────────────────┘
 */

import * as React from 'react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Inter } from 'next/font/google'

import { AgentDAG } from './components/AgentDAG'
import { StreamingReport } from './components/StreamingReport'
import {
  InspectorDrawer,
  getDefaultInspectorPayload,
  buildNodePayload,
  buildCitationPayload,
  type InspectorPayload,
} from './components/InspectorDrawer'
import { PromptInput } from './components/PromptInput'
import { apiStream } from '@/lib/api/client'
import type {
  DoneEventV,
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
    latency:
      nv.elapsed_ms != null ? `${(nv.elapsed_ms / 1000).toFixed(1)}s` : node.latency,
  }
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
  // 当前提问。标题要从它取——后端返回的正文不含标题。
  const [question, setQuestion] = useState('')
  // 工具调用轨迹：InspectorDrawer 的「已执行工具调用」区读它。
  const [toolCalls, setToolCalls] = useState<ToolCall[]>([])
  // 引用表：后端 reference 事件下发。初始给 mock 的 CITATIONS，让未提问
  // 时的静态段落仍有可点角标；一旦流开始就会被真实数据整体替换。
  const [citations, setCitations] = useState<Citation[]>(CITATIONS)

  // 中断用的 AbortController：用户重问或卸载页面时取消上一次请求。
  const abortRef = useRef<AbortController | null>(null)

  const handleSelectNode = useCallback((node: Parameters<typeof buildNodePayload>[0]) => {
    setInspectorOpen(true)
    setInspectorPayload({ ...buildNodePayload(node), toolCalls })
  }, [toolCalls])

  const handleSelectCitation = useCallback(
    (citation: Parameters<typeof buildCitationPayload>[0]) => {
      setInspectorOpen(true)
      setInspectorPayload(buildCitationPayload(citation))
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

    setNodes(INITIAL_NODES)
    setStreamedText('')
    setErrorText(null)
    setSummary(null)
    setQuestion(question)
    setRunState('running')
    // 引用表和工具轨迹一样属于单次运行的产物，重问时必须清空——否则上一轮
    // 的编号会跟这一轮的正文对不上。
    setCitations(CITATIONS)
    setToolCalls([])

    try {
      await apiStream('/api/v1/research/ask', { question }, (event) => {
        const v = event.v as Record<string, unknown>
        switch (event.type) {
          case 'node': {
            const nv = v as unknown as NodeEventV
            setNodes((prev) => prev.map((n) => (n.id === nv.node_id ? applyNode(n, nv) : n)))
            break
          }
          case 'delta': {
            const dv = v as unknown as { text: string }
            setStreamedText((prev) => prev + dv.text)
            break
          }
          case 'error': {
            const ev = v as unknown as { message: string }
            setErrorText(ev.message)
            break
          }
          case 'done':
            setSummary(v as unknown as DoneEventV)
            setRunState('completed')
            break
          case 'tool_call': {
            const tv = v as unknown as ToolCallEventV
            setToolCalls((prev) => {
              // 按 call_id 合并 start / end 两段：start 先占位并显示
              // 「执行中…」，end 到达时用真实耗时覆盖同一 id。
              const i = prev.findIndex((c) => c.id === tv.call_id)
              const merged = toToolCall(tv, tv.phase === 'end' ? tv : undefined)
              if (i < 0) return [...prev, merged]
              const next = [...prev]
              next[i] = merged
              return next
            })
            break
          }
          case 'reference': {
            const rv = v as unknown as ReferenceEventV
            // 整体替换而非 append：后端 ReferenceTable.all 每次下发的是
            // 已编号的全表，append 会让编号重复。
            setCitations(rv.references)
            break
          }
          default:
            break
        }
      }, controller.signal)
      setRunState((prev) => (prev === 'running' ? 'completed' : prev))
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return
      setErrorText(err instanceof Error ? err.message : '连接失败')
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
  useEffect(() => () => abortRef.current?.abort(), [])

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
            <p className={styles.runSummary}>
              会话 {summary.session_id.slice(0, 8)} · {summary.turns} 轮 ·{' '}
              {(summary.elapsed_ms / 1000).toFixed(1)} 秒 · 输入 {summary.input_tokens} / 输出{' '}
              {summary.output_tokens} tokens{summary.truncated && ' · 已截断'}
            </p>
          )}
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

