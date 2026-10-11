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

export interface InspectorDrawerProps {
  open: boolean
  payload: InspectorPayload
  onClose: () => void
}

/**
 * Right-side inspector — vertical 4-tab strip (Input/Output/Prompt/Tools) +
 * content area showing tool-call summary + monospace raw state JSON.
 *
 * The "Output" tab is the default active tab because it is the most-referenced
 * surface in the design.
 */
export function InspectorDrawer({ open, payload, onClose }: InspectorDrawerProps) {
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
        <ContentArea tab={tab} jsonText={payload.jsonText} toolCalls={payload.toolCalls} />
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
}

function ContentArea({ tab, jsonText, toolCalls: calls }: ContentAreaProps) {
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
    title: `数据源引用 [${citation.id}] 溯源核验`,
    latency: '14ms',
    dotState: 'active',
    jsonText: JSON.stringify(
      {
        citation_id: citation.id,
        source_title: citation.sourceTitle,
        canonical_url: citation.url,
        publication_date: citation.date,
        ingested_via: 'Argus Search API v2',
        relevance_score: 0.984,
        grounding_anchor: 'NVIDIA H100 SXM 对比 B200 NVLink 5 域',
        extracted_facts: [
          'B200 单卡 FP4 张量计算峰值达 9 PFLOPS',
          'HBM3e 显存位宽提升至 8.0 TB/s',
          '针对 10 万 QPS 级推理集群模型测算 TCO 节能 75%',
        ],
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
