'use client'

import * as React from 'react'
import { IconSpan } from '@/components/common/IconSpan'
import type { AgentNode, Citation, ToolCall } from '../../constants'
import styles from './index.module.css'

export type InspectorTab = 'State' | 'Tools'

export interface InspectorPayload {
  title: string
  /**
   * 头部右侧的一行短标签。
   *
   * 刻意不叫 latency：节点载荷放的是耗时，引用载荷放的是召回方式
   * （"向量+BM25"）——两者语义不同，硬塞进一个 latency 字段会让引用
   * 抽屉把召回方式当耗时显示。
   */
  meta: string
  jsonText: string
  /** Drives status dot color (active / completed / default). */
  dotState: 'active' | 'completed' | 'failed' | 'default'
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
  /** 本轮已发出的工具调用。与 payload 分开传：节点快照与实时轨迹是两个源。 */
  toolCalls: ToolCall[]
  /** 必填——「不显示」由 `SourceTextState` 的 `{kind:'none'}` 表达，
   *  再叠一层 undefined 等于同一语义两种写法，且新调用方忘传就静默不显示。 */
  sourceText: SourceTextState
  onClose: () => void
}

/**
 * Right-side inspector — 节点 / 引用的实时状态 JSON + 工具调用轨迹。
 *
 * 只有两个 tab：设计稿里的 Input / Prompt 两栏没有任何数据源，后端不下发
 * 输入载荷与系统提示词，画出来只能靠编——故删除而非留空壳。
 */
export function InspectorDrawer({
  open,
  payload,
  toolCalls,
  sourceText,
  onClose,
}: InspectorDrawerProps) {
  const [tab, setTab] = React.useState<InspectorTab>('State')

  const drawerClass = [styles.drawer, open ? styles.drawerOpen : styles.drawerClosed]
    .filter(Boolean)
    .join(' ')

  return (
    // inert：关闭时把整块内容移出可交互树。
    //
    // 只用 aria-hidden 不够——它只影响读屏，键盘 Tab 仍能聚焦到抽屉里的
    // 按钮（关闭键与两个 tab），于是键盘用户会 Tab 到一个看不见的控件上，
    // 而读屏又因为 aria-hidden 跳过它（WCAG 2.4.3 焦点顺序 / 4.1.2 名称值）。
    // inert 一次性解决两者：不可聚焦、不可点击、不可被读屏访问。
    <aside className={drawerClass} aria-hidden={!open} inert={!open}>
      {/* Header */}
      <div className={styles.head}>
        <div className={styles.headLeft}>
          <span
            className={`${styles.headDot} ${
              payload.dotState === 'active'
                ? styles.headDotActive
                : payload.dotState === 'completed'
                  ? styles.headDotCompleted
                  : payload.dotState === 'failed'
                    ? styles.headDotFailed
                    : styles.headDotDefault
            }`}
          />
          <h3 className={styles.headTitle}>{payload.title}</h3>
        </div>
        <div className={styles.headRight}>
          <span className={styles.headLatency}>{payload.meta}</span>
          <button type="button" onClick={onClose} className={styles.closeBtn} title="关闭检查器">
            <IconSpan name="close" size={14} />
          </button>
        </div>
      </div>

      {/* Body: left tab strip + right content */}
      <div className={styles.body}>
        <TabStrip tab={tab} onTabChange={setTab} />
        <ContentArea tab={tab} payload={payload} toolCalls={toolCalls} sourceText={sourceText} />
      </div>
    </aside>
  )
}

/* ───────── Tab strip ───────── */

interface TabStripProps {
  tab: InspectorTab
  onTabChange: (tab: InspectorTab) => void
}

const TABS: Array<{ id: InspectorTab; label: string; icon: string }> = [
  { id: 'State', label: '状态 (JSON)', icon: 'description' },
  { id: 'Tools', label: '工具调用记录', icon: 'build_circle' },
]

function TabStrip({ tab, onTabChange }: TabStripProps) {
  return (
    <div className={styles.tabStrip} role="tablist">
      {TABS.map((t) => (
        <button
          key={t.id}
          type="button"
          role="tab"
          aria-selected={tab === t.id}
          aria-label={t.label}
          className={`${styles.tabBtn} ${tab === t.id ? styles.tabBtnActive : ''}`}
          onClick={() => onTabChange(t.id)}
          title={t.label}
        >
          <IconSpan
            name={t.icon}
            size={16}
            className={tab === t.id ? styles.tabIconActive : styles.tabIcon}
          />
        </button>
      ))}
    </div>
  )
}

/* ───────── Content area ───────── */

interface ContentAreaProps {
  tab: InspectorTab
  payload: InspectorPayload
  toolCalls: ToolCall[]
  sourceText: SourceTextState
}

function ContentArea({ tab, payload, toolCalls, sourceText }: ContentAreaProps) {
  const label = TABS.find((t) => t.id === tab)?.label ?? ''

  return (
    <div className={styles.content}>
      <div className={styles.contentHead}>
        <span>{label}</span>
        {tab === 'State' && (
          <span className={styles.contentSize}>utf-8 · {payload.jsonText.length} 字符</span>
        )}
      </div>

      {/* 原文区。只在点开角标后出现——它是引用溯源的一部分，不是常驻控件。 */}
      {sourceText.kind !== 'none' && <SourceTextBlock state={sourceText} />}

      {tab === 'Tools' ? (
        <div className={styles.toolsBlock}>
          <div className={styles.toolsHead}>
            <span>已执行工具调用 ({toolCalls.length})</span>
          </div>
          {toolCalls.length === 0 && <p className={styles.sourceHint}>本轮尚未调用任何工具</p>}
          {toolCalls.map((tc) => (
            <div key={tc.id} className={styles.toolRow}>
              <div className={styles.toolRowHead}>
                <div className={styles.toolRowName}>
                  <IconSpan name="deployed_code" size={13} className={styles.toolRowIcon} />
                  <span>{tc.name}</span>
                  {tc.ok === false && <span className={styles.toolRowFailed}>失败</span>}
                  {tc.ok !== false && tc.errorCode && (
                    <span className={styles.toolRowSkipped}>资料被跳过</span>
                  )}
                </div>
                <span className={styles.toolRowDuration}>{tc.duration}</span>
              </div>
              <div className={styles.toolRowArgs}>参数: {tc.args}</div>
              {tc.ok === false && tc.preview && (
                <div className={styles.toolRowError}>{tc.preview}</div>
              )}
              {tc.ok !== false && tc.errorCode && (
                <div className={styles.toolRowSkippedNote}>
                  {tc.errorCode === 'retrieval_no_match'
                    ? '你的私有资料与本次问题不相关，已被跳过，未作为证据使用。'
                    : tc.errorCode === 'retrieval_not_evaluated'
                      ? '本次未能评估私有资料的相关性（索引未就绪或语义检索未启用），未使用私有资料。'
                      : `本次未使用私有资料（${tc.errorCode}）。`}
                </div>
              )}
            </div>
          ))}
        </div>
      ) : (
        <div className={styles.jsonBlock}>
          <pre className={styles.jsonPre}>{payload.jsonText}</pre>
        </div>
      )}
    </div>
  )
}

/* ───────── Source text (citation drill-down) ───────── */

/**
 * 角标点开后显示的原文切片。
 *
 * 位置放在 JSON 之上：它回答的是「这条引用到底引了什么」，比 JSON 溯源更靠前
 * ——用户点角标的第一反应是看原文，不是看字段。
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

      {state.kind === 'loading' && <p className={styles.sourceHint}>正在拉取原文…</p>}
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

/** 尚未点开任何东西时的空载荷。没有默认节点快照——那只能编。 */
export function emptyInspectorPayload(): InspectorPayload {
  return {
    title: '检查器',
    meta: '',
    jsonText: JSON.stringify({ hint: '点击左侧 DAG 节点或正文角标查看详情' }, null, 2),
    dotState: 'default',
  }
}

/** 从点开的 DAG 节点构造载荷。 */
export function buildNodePayload(node: AgentNode): InspectorPayload {
  const dotState: InspectorPayload['dotState'] =
    node.lifecycle === 'active'
      ? 'active'
      : node.lifecycle === 'completed'
        ? 'completed'
        : node.lifecycle === 'failed'
          ? 'failed'
          : 'default'
  return {
    title: `${node.name} 检查器`,
    meta: node.latency ? `运行耗时 ${node.latency}` : '',
    jsonText: JSON.stringify(
      {
        node_id: node.id,
        lifecycle_state: node.lifecycle,
        role_description: node.detail || node.role,
        // 产出摘要。空字符串也列出——让看 JSON 的人知道「这个节点
        // 有产出摘要这个字段，只是这次没有」。
        production_note: node.note,
        latency: node.latency,
      },
      null,
      2,
    ),
    dotState,
  }
}

/** 从点开的引用角标构造载荷。 */
export function buildCitationPayload(citation: Citation): InspectorPayload {
  return {
    title: `数据源引用 [${citation.n}] 溯源核验`,
    meta: citation.url ? `召回方式 ${citation.recall} · 公开来源` : `召回方式 ${citation.recall}`,
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
        // 公开来源（联网搜索）的 URL——用户要知道「这个数字是哪来的」。
        // 用户上传的资料没有 URL，空串。
        source_url: citation.url ?? '',
        excerpt: citation.excerpt,
      },
      null,
      2,
    ),
  }
}
