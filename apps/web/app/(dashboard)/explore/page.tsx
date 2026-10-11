'use client'

/**
 * /explore — Argus 多智能体深度研究控制台。
 *
 * 设计稿是 argus_2/code.html 的还原。本页刻意与项目 Material 3 token 体系不同：
 * argus_2 自带一套深色面板调色（#0a0a0a 背景 + #4f7cff 品牌色 + #7039f9 强调色），
 * UI 主字体用 Inter。通过 next/font/google 按页面加载，不影响其他路由（其他路由用 Geist）。
 *
 * 布局（1440px 容器，sticky 56px TopBar）：
 *   ┌──────────────────────────────────────────────┐
 *   │ TopBar (brand, search, live, toggle, avatar) │
 *   ├─────────────────────────────────┬────────────┤
 *   │ Center column (920px)           │ Inspector  │
 *   │  ├ AgentDAG (5 nodes)           │ (380px)    │
 *   │  ├ StreamingReport (H1 + prose) │ collapsible│
 *   │  │  └ cite-sup + metrics card   │            │
 *   └─────────────────────────────────┴────────────┘
 *           ┌──────────────────────────┐
 *           │ PromptInput (48px fixed) │
 *           └──────────────────────────┘
 */

import * as React from 'react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Inter } from 'next/font/google'

import { TopBar } from './components/TopBar'
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
import {
  AGENT_NODES,
  type AgentNode,
  type NodeLifecycle,
  type SlashCommand,
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

interface DoneEventV {
  session_id: string
  elapsed_ms: number
  turns: number
  input_tokens: number
  output_tokens: number
  truncated: boolean
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

type NodeEventV = { node_id: string; lifecycle: string; detail: string; elapsed_ms: number | null }

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

  // 中断用的 AbortController：用户重问或卸载页面时取消上一次请求。
  const abortRef = useRef<AbortController | null>(null)

  const handleSelectNode = useCallback((node: Parameters<typeof buildNodePayload>[0]) => {
    setInspectorOpen(true)
    setInspectorPayload(buildNodePayload(node))
  }, [])

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
          // tool_call 事件暂不驱动 UI——InspectorDrawer 的 payload 结构
          // 还是设计稿的 4 字段形状，接真实数据要一起改，留到下一步。
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
      <TopBar onToggleInspector={handleToggleInspector} inspectorOpen={inspectorOpen} />

      <div className={styles.main}>
        {/* Center column: DAG + Streaming Report */}
        <main className={styles.center}>
          <AgentDAG onSelectNode={handleSelectNode} nodes={nodes} />
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

