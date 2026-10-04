'use client'

/**
 * /explore — Argus multi-agent deep research console.
 *
 * Restoration of argus_2/code.html. This page intentionally diverges from
 * the project's Material 3 token system: argus_2 has its own dark surface
 * palette (#0a0a0a bg + #4f7cff brand + #7039f9 accent) and Inter as the
 * primary UI font, which we load per-page via next/font/google so other
 * routes (Geist) are unaffected.
 *
 * Layout (1440px wrapper, sticky 56px TopBar):
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

/** Full target text for the trailing streaming paragraph. */
const STREAM_TARGET =
  '更为关键的是,总体拥有成本 (TCO) 为大规模智算中心运营方带来了革命性的结构优化。以支撑 100,000 QPS 推理负载的集群规模测算,Blackwell 较同等吞吐 吞吐量的 Hopper 集群将数据中心综合电力消耗锐减 75%。目前主要的落地摩擦点集中于机房 二次液冷系统改建,因为 GB200 机柜强制要求采用单机柜高达 120kW 换热 密度的芯片级直触液冷回路...'

/** Reset all agent nodes to "pending" — the run starts from zero. */
const INITIAL_NODES: AgentNode[] = AGENT_NODES.map((n) => ({ ...n, lifecycle: 'pending' }))

/** Promote one pending node to active and mark all earlier nodes completed. */
function advance(nodes: AgentNode[]): AgentNode[] {
  const next: NodeLifecycle[] = nodes.map((n) => n.lifecycle)
  const firstPending = next.findIndex((s) => s === 'pending')
  if (firstPending < 0) return nodes
  // Mark everything up to firstPending-1 as completed.
  for (let i = 0; i < firstPending; i++) next[i] = 'completed'
  next[firstPending] = 'active'
  return nodes.map((n, i) => ({ ...n, lifecycle: next[i] as NodeLifecycle }))
}

/** Final pass: mark the remaining active node as completed. */
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
  // Popover is visible when value starts with "/" (and is exactly "/", per
  // design — typing more characters hides it again).
  const slashVisible = promptValue === '/'

  // Run state — drives DAG animation + StreamingReport tail typewriter.
  const [runState, setRunState] = useState<RunState>('idle')
  const [nodes, setNodes] = useState<AgentNode[]>(INITIAL_NODES)
  const [streamedText, setStreamedText] = useState('')

  // Refs to keep cleanup centralized in the effect below.
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

  /** Effect that owns the run timers. Cleans up on unmount or when runState changes. */
  useEffect(() => {
    if (runState !== 'running') return

    // Node promotion: every 800ms advance one pending → active → completed.
    const nodeTimer = setInterval(() => {
      setNodes((prev) => {
        const stillPending = prev.some((n) => n.lifecycle === 'pending')
        if (!stillPending) {
          // All done: mark last active as completed and stop the node timer.
          return finalize(prev)
        }
        return advance(prev)
      })
    }, 800)
    nodeTimerRef.current = nodeTimer

    // Typewriter: every 30ms append the next character to streamedText.
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

  // Once the typewriter catches up AND every node is completed, mark the run done.
  useEffect(() => {
    if (runState !== 'running') return
    const allCompleted = nodes.every((n) => n.lifecycle === 'completed')
    if (allCompleted && streamedText.length >= STREAM_TARGET.length) {
      setRunState('completed')
    }
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
