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

/** 尾段打字机要追到的完整目标文本。 */
const STREAM_TARGET =
  '更为关键的是,总体拥有成本 (TCO) 为大规模智算中心运营方带来了革命性的结构优化。以支撑 100,000 QPS 推理负载的集群规模测算,Blackwell 较同等吞吐 吞吐量的 Hopper 集群将数据中心综合电力消耗锐减 75%。目前主要的落地摩擦点集中于机房 二次液冷系统改建,因为 GB200 机柜强制要求采用单机柜高达 120kW 换热 密度的芯片级直触液冷回路...'

/** 把所有 agent 节点重置为 pending —— 每次提问都从 0 重新跑。 */
const INITIAL_NODES: AgentNode[] = AGENT_NODES.map((n) => ({ ...n, lifecycle: 'pending' }))

/** 把下一个 pending 节点提为 active，并把之前的节点标为 completed。 */
function advance(nodes: AgentNode[]): AgentNode[] {
  const next: NodeLifecycle[] = nodes.map((n) => n.lifecycle)
  const firstPending = next.findIndex((s) => s === 'pending')
  if (firstPending < 0) return nodes
  // 把 firstPending 之前的全部标为 completed。
  for (let i = 0; i < firstPending; i++) next[i] = 'completed'
  next[firstPending] = 'active'
  return nodes.map((n, i) => ({ ...n, lifecycle: next[i] as NodeLifecycle }))
}

/** 最后一步：把剩下的 active 节点也标为 completed。 */
function finalize(nodes: AgentNode[]): AgentNode[] {
  return nodes.map((n) =>
    n.lifecycle === 'active' ? { ...n, lifecycle: 'completed' as NodeLifecycle } : n,
  )
}

type RunState = 'idle' | 'running' | 'completed'

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

  // 用 ref 保存 timer，cleanup 集中在下面的 effect 里统一清。
  const nodeTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const typeTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)

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

  const handlePromptSubmit = useCallback((value: string) => {
    const trimmed = value.trim()
    if (!trimmed) return
    if (runState === 'running') return
    setPromptValue('')
    setNodes(INITIAL_NODES)
    setStreamedText('')
    setRunState('running')
  }, [runState])

  const handleSlashSelect = useCallback((cmd: SlashCommand) => {
    setPromptValue(`${cmd.cmd} `)
  }, [])

  /** 持有运行期 timer 的 effect：unmount 或 runState 变化时统一 cleanup。 */
  useEffect(() => {
    if (runState !== 'running') return

    // 节点推进：每 800ms 把下一个 pending 提为 active。
    const nodeTimer = setInterval(() => {
      setNodes((prev) => {
        const stillPending = prev.some((n) => n.lifecycle === 'pending')
        if (!stillPending) {
          // 全部跑完：把最后 active 标 completed，等下个 tick 退出循环。
          return finalize(prev)
        }
        return advance(prev)
      })
    }, 800)
    nodeTimerRef.current = nodeTimer

    // 打字机：每 30ms 追加 streamedText 的下一个字符。
    const typeTimer = setInterval(() => {
      setStreamedText((prev) => {
        if (prev.length >= STREAM_TARGET.length) return prev
        return STREAM_TARGET.slice(0, prev.length + 1)
      })
    }, 30)
    typeTimerRef.current = typeTimer

    return () => {
      clearInterval(nodeTimer)
      clearInterval(typeTimer)
      nodeTimerRef.current = null
      typeTimerRef.current = null
    }
  }, [runState])

  // 当打字机追平 + 所有节点都 completed 时，把 runState 切到 completed。
  useEffect(() => {
    if (runState !== 'running') return
    const allCompleted = nodes.every((n) => n.lifecycle === 'completed')
    if (allCompleted && streamedText.length >= STREAM_TARGET.length) {
    // eslint-disable-next-line react-hooks/set-state-in-effect
      setRunState('completed')
    }
    // set-state-in-effect 指得对：runState 本可由 nodes/streamedText 派生
    // （useMemo 算 completed），不必存成 state 再在 effect 里同步。
    // 这里是 W1 mock 演示逻辑，Day 3 接真实 SSE 后 runState 会由流事件
    // 驱动、无法派生，这个 effect 自然消失。届时一并清理。
  }, [runState, nodes, streamedText])

  return (
    <div className={`${styles.shell} ${inter.className}`}>
      <TopBar onToggleInspector={handleToggleInspector} inspectorOpen={inspectorOpen} />

      <div className={styles.main}>
        {/* Center column: DAG + Streaming Report */}
        <main className={styles.center}>
          <AgentDAG onSelectNode={handleSelectNode} nodes={nodes} />
          <StreamingReport onSelectCitation={handleSelectCitation} streamedText={streamedText} />
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
