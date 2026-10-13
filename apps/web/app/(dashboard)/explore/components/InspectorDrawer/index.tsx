'use client'

import * as React from 'react'
import { IconSpan } from '@/components/common/IconSpan'
import { ANALYST_RAW_STATE, type AgentNode, type Citation, type ToolCall } from '../../mock'
import styles from './index.module.css'

export type InspectorTab = 'Input' | 'Output' | 'Prompt' | 'Tools'

export interface InspectorPayload {
  title: string
  latency: string
  jsonText: string
  /** Drives status dot color (active / completed / default). */
  dotState: 'active' | 'completed' | 'default'
  /** 本节点关联的工具调用。空数组表示这次运行没调过工具。 */
  toolCalls: ToolCall[]
}

/**
 * 原文区的三种状态。刻意不用 `null` 表示「不显示」——那会和
 * 「正在加载」「拉取失败」混淆，而这三者要显示的东西完全不同。
 */
export type SourceTextState =
  | { kind: 'none' }
  | { kind: 'loading' }
  | { kind: 'ready'; title: string; body: string }
  /** 拉不到原文。显式报错而不是回退到 excerpt——用户分不清 120 字节选与全文。 */
  | { kind: 'error'; message: string }

export interface InspectorDrawerProps {
  open: boolean
  payload: InspectorPayload
  /** 必填——「不显示」由 `SourceTextState` 的 `{kind:'none'}` 表达，
   *  再叠一层 undefined 等于同一语义两种写法，且新调用方忘传就静默不显示。 */
  sourceText: SourceTextState
  onClose: () => void
}

/**
 * Right-side inspector — vertical 4-tab strip (Input/Output/Prompt/Tools) +
 * content area showing tool-call summary + monospace raw state JSON.
 *
 * The "Output" tab is the default active tab because it is the most-referenced
 * surface in the design.
 */
export function InspectorDrawer({ open, payload, sourceText, onClose }: InspectorDrawerProps) {
  const [tab, setTab] = React.useState<InspectorTab>('Output')

  const drawerClass = [styles.drawer, open ? styles.drawerOpen : styles.drawerClosed]
    .filter(Boolean)
    .join(' ')

  return (
    <aside className={drawerClass} aria-hidden={!open}>
      {/* Header */}
      <div className={styles.head}>
        <div className={styles.headLeft}>
          <span
            className={`${styles.headDot} ${
              payload.dotState === 'active'
                ? styles.headDotActive
                : payload.dotState === 'completed'
                  ? styles.headDotCompleted
                  : styles.headDotDefault
            }`}
          />
          <h3 className={styles.headTitle}>{payload.title}</h3>
        </div>
        <div className={styles.headRight}>
          <span className={styles.headLatency}>运行耗时 {payload.latency}</span>
          <button type="button" onClick={onClose} className={styles.closeBtn} title="关闭检查器">
            <IconSpan name="close" size={14} />
          </button>
        </div>
      </div>

      {/* Body: left tab strip + right content */}
      <div className={styles.body}>
        <TabStrip tab={tab} onTabChange={setTab} />
        <ContentArea
          tab={tab}
          jsonText={payload.jsonText}
          toolCalls={payload.toolCalls}
          sourceText={sourceText}
        />
      </div>
    </aside>
  )
}

/* ───────── Tab strip ───────── */

interface TabStripProps {
  tab: InspectorTab
  onTabChange: (tab: InspectorTab) => void
}

const TAB_LABELS: Record<InspectorTab, string> = {
  Input: '输入载荷 (INPUT PAYLOAD)',
  Output: '输出状态 (JSON)',
  Prompt: '系统提示词 (SYSTEM PROMPT)',
  Tools: '工具调用记录 (TOOL TRACE)',
}

function TabStrip({ tab, onTabChange }: TabStripProps) {
  const tabs: InspectorTab[] = ['Input', 'Output', 'Prompt', 'Tools']
  return (
    <div className={styles.tabStrip} role="tablist">
      {tabs.map((t) => (
        <button
          key={t}
          type="button"
          role="tab"
          aria-selected={tab === t}
          className={`${styles.tabBtn} ${tab === t ? styles.tabBtnActive : ''}`}
          onClick={() => onTabChange(t)}
          title={TAB_LABELS[t]}
        >
          <TabIcon tab={t} active={tab === t} />
        </button>
      ))}
    </div>
  )
}

function TabIcon({ tab, active }: { tab: InspectorTab; active: boolean }) {
  const iconClass = active ? styles.tabIconActive : styles.tabIcon
  const size = 16
  switch (tab) {
    case 'Input':
      return <IconSpan name="chevron_left" size={size} className={iconClass} />
    case 'Output':
      return <IconSpan name="chevron_right" size={size} className={iconClass} />
    case 'Prompt':
      return <IconSpan name="description" size={size} className={iconClass} />
    case 'Tools':
      return <IconSpan name="build_circle" size={size} className={iconClass} />
  }
}

/* ───────── Content area ───────── */

interface ContentAreaProps {
  tab: InspectorTab
  jsonText: string
  toolCalls: ToolCall[]
  sourceText: SourceTextState
}

function ContentArea({ tab, jsonText, toolCalls: calls, sourceText }: ContentAreaProps) {
  const tabStatusLabel = TAB_LABELS[tab]

  return (
    <div className={styles.content}>
      <div className={styles.contentHead}>
        <span>{tabStatusLabel}</span>
        <span className={styles.contentSize}>utf-8 · 1.4KB</span>
      </div>

      {/* Tool calls summary (always visible) */}
      <div className={styles.toolsBlock}>
        <div className={styles.toolsHead}>
          <span>已执行工具调用 ({calls.length})</span>
          {calls[0] && <span className={styles.toolsTrace}>{calls[0].id}</span>}
        </div>
        {calls.map((tc) => (
          <div key={tc.id} className={styles.toolRow}>
            <div className={styles.toolRowHead}>
              <div className={styles.toolRowName}>
                <IconSpan name="deployed_code" size={13} className={styles.toolRowIcon} />
                <span>{tc.name}</span>
              </div>
              <span className={styles.toolRowDuration}>{tc.duration}</span>
            </div>
            <div className={styles.toolRowArgs}>参数: {tc.args}</div>
          </div>
        ))}
      </div>

      {/* 原文区。只在点开角标后出现——它是引用溯源的一部分，不是常驻控件。 */}
      {sourceText.kind !== 'none' && <SourceTextBlock state={sourceText} />}

      {/* JSON viewer (Output tab primary, others also show for brevity) */}
      <div className={styles.jsonBlock}>
        <pre className={styles.jsonPre}>{jsonText}</pre>
      </div>

      {/* Footer */}
      <div className={styles.footer}>
        <a className={styles.phoenixLink} href="#phoenix-trace">
          <span>在 Phoenix 中查看</span>
          <IconSpan name="open_in_new" size={13} className={styles.phoenixIcon} />
        </a>
        <span className={styles.spanId}>跨度 ID: a82f71b9</span>
      </div>
    </div>
  )
}

/* ───────── Source text (citation drill-down) ───────── */

/**
 * 角标点开后显示的原文切片。
 *
 * 位置放在工具列表与 JSON 之间：它回答的是「这条引用到底引了什么」，
 * 比 JSON 溯源更靠前——用户点角标的第一反应是看原文，不是看字段。
 */
function SourceTextBlock({ state }: { state: SourceTextState }) {
  return (
    <div className={styles.sourceBlock}>
      <div className={styles.sourceHead}>
        <span className={styles.sourceTitle}>
          <IconSpan name="description" size={13} className={styles.sourceIcon} />
          <span>引用原文</span>
        </span>
        {state.kind === 'ready' && <span className={styles.sourceMeta}>{state.title}</span>}
      </div>

      {state.kind === 'loading' && (
        <p className={styles.sourceHint}>正在拉取原文…</p>
      )}
      {state.kind === 'error' && (
        <p className={styles.sourceError} role="alert">
          原文拉取失败：{state.message}
        </p>
      )}
      {state.kind === 'ready' && <p className={styles.sourceBody}>{state.body}</p>}
    </div>
  )
}

/* ───────── Builders exposed to page ───────── */
const DEFAULT_PAYLOAD: InspectorPayload = {
  toolCalls: [],
  title: '分析节点检查器 (Analyst Node Inspector)',
  latency: '运行耗时 4.4秒',
  jsonText: JSON.stringify(ANALYST_RAW_STATE, null, 2),
  dotState: 'active',
}

/** Build a payload from a clicked DAG node. */
export function buildNodePayload(node: AgentNode): InspectorPayload {
  const dotState: InspectorPayload['dotState'] =
    node.lifecycle === 'active'
      ? 'active'
      : node.lifecycle === 'completed'
        ? 'completed'
        : 'default'
  return {
    toolCalls: [],
    title: `${node.name} 检查器`,
    latency: node.latency,
    jsonText: JSON.stringify(
      {
        node_name: node.name,
        lifecycle_state: node.lifecycle,
        role_description: node.role,
        runtime_stats: {
          latency: node.latency,
          tokens: node.tokens,
          cached: node.lifecycle === 'completed',
        },
      },
      null,
      2,
    ),
    dotState,
  }
}

/** Build a payload from a clicked citation. */
export function buildCitationPayload(citation: Citation): InspectorPayload {
  return {
    toolCalls: [],
    title: `数据源引用 [${citation.n}] 溯源核验`,
    latency: citation.recall,
    dotState: 'active',
    jsonText: JSON.stringify(
      {
        citation_no: citation.n,
        source_id: citation.source_id,
        chunk_id: citation.chunk_id,
        // 后端下发的 chunk_index 是 0-based，展示时人读的是「第 n+1 块」。
        chunk_label: `第 ${citation.chunk_index + 1} 块`,
        // 纯文本按 \f 分页时 page 也有值，所以它不是「PDF 专属」——
        // 原文区优先用 page，这里保留原值供排查时对照。
        page: citation.page,
        source_title: citation.title,
        recall: citation.recall,
        excerpt: citation.excerpt,
      },
      null,
      2,
    ),
  }
}

/** Default payload (used on first mount before any user click). */
export function getDefaultInspectorPayload(): InspectorPayload {
  return DEFAULT_PAYLOAD
}
