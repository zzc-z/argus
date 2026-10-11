'use client'

import * as React from 'react'
import { IconSpan } from '@/components/common/IconSpan'
import { DAG_STATS, type AgentNode } from '../../mock'
import styles from './index.module.css'

export interface AgentDAGProps {
  onSelectNode: (node: AgentNode) => void
  nodes: AgentNode[]
  /** 第几步（1-based）。缺省时用 mock 的静态值，保持组件可独立预览。 */
  currentStep?: number
  /** 已耗时（格式化好的文案）。缺省时用 mock 的静态值。 */
  elapsed?: string
  /** token 用量（格式化好的文案）。缺省时用 mock 的静态值。 */
  tokens?: string
}

/**
 * 紧凑型竖向 DAG 时间线（最多 5 节点）。背景 rail 贯穿全部高度；
 * active 高亮 rail 停在当前 active 节点。active 节点带 `cobaltPulse` 脉冲。
 * pending 节点显示空心圆。
 */
export function AgentDAG({
  onSelectNode,
  nodes,
  elapsed,
  tokens,
}: AgentDAGProps) {
  // 高亮轨道停在 active 节点上。高度实测得出而不是写死：行高由 CSS
  // padding + 字体决定，改样式时这个数字会跟着失配（之前写死 44，
  // 实际行高是 30，轨道伸到列表外面）。
  const activeIndex = nodes.findIndex((n) => n.lifecycle === 'active')
  const listRef = React.useRef<HTMLDivElement>(null)
  const [rowHeight, setRowHeight] = React.useState(0)
  // 用 useEffect 而不是 useLayoutEffect：后者在 SSR 阶段会告警
  // 「在服务端渲染时不能调用 useLayoutEffect」。也不能用 useMemo——
  // 渲染时 listRef.current 还是 null，算出来恒为 0。
  React.useEffect(() => {
    const first = listRef.current?.querySelector('.' + styles.row)
    setRowHeight(first ? first.getBoundingClientRect().height : 0)
  }, [nodes.length])
  // 轨道从 timeline 顶 +19px（第一个圆心，实测值）起，画到第 active 个圆心。
  const highlightHeight =
    activeIndex >= 0 && rowHeight > 0 ? `${activeIndex * rowHeight + 19}px` : '0px'

  return (
    <section className={styles.section}>
      {/* Header */}
      <div className={styles.head}>
        <div className={styles.headLeft}>
          <span className={styles.headDot} />
          <h2 className={styles.headTitle}>{DAG_STATS.title}</h2>
          <span className={styles.headSep}>|</span>
          <span className={styles.headPipeline}>{DAG_STATS.pipeline}</span>
        </div>
        <div className={styles.headStats}>
          <span className={styles.headStatEmphasis}>
            {DAG_STATS.totalSteps} 步中的第{' '}
            {nodes.filter((n) => n.lifecycle !== 'pending').length || DAG_STATS.currentStep} 步
          </span>
          <span className={styles.headStatSep}>·</span>
          <span>{elapsed ?? DAG_STATS.elapsed}</span>
          <span className={styles.headStatSep}>·</span>
          <span>{tokens ?? DAG_STATS.tokens}</span>
        </div>
      </div>

      {/* Timeline */}
      <div className={styles.timeline} ref={listRef}>
        {/* Background rail */}
        <div className={styles.rail} aria-hidden="true" />
        {/* Active highlight rail (covers nodes 1..active) */}
        <div className={styles.railActive} aria-hidden="true" style={{ height: highlightHeight }} />

        {nodes.map((node) => (
          <NodeRow key={node.id} node={node} onClick={() => onSelectNode(node)} />
        ))}
      </div>
    </section>
  )
}

interface NodeRowProps {
  node: AgentNode
  onClick: () => void
}

function NodeRow({ node, onClick }: NodeRowProps) {
  const isCompleted = node.lifecycle === 'completed'
  const isActive = node.lifecycle === 'active'
  const isPending = node.lifecycle === 'pending'

  const rowClass = [styles.row, isActive ? styles.rowActive : ''].filter(Boolean).join(' ')

  return (
    <div className={rowClass} onClick={onClick} role="button" tabIndex={0}>
      <div className={styles.rowLeft}>
        {/* Status circle */}
        {isCompleted && (
          <div className={styles.circleCompleted}>
            <IconSpan name="check" size={13} className={styles.circleIcon} />
          </div>
        )}
        {isActive && (
          <div className={styles.circleActive}>
            <span className={styles.circleActiveInner} />
          </div>
        )}
        {isPending && <div className={styles.circlePending} />}

        <div className={styles.rowText}>
          <span
            className={`${styles.rowName} ${
              isActive ? styles.rowNameActive : isPending ? styles.rowNamePending : ''
            }`}
          >
            {node.name}
          </span>
          <span className={`${styles.rowRole} ${isActive ? styles.rowRoleActive : ''}`}>
            {node.role}
          </span>
        </div>
      </div>

      <div className={styles.rowRight}>
        {isActive && (
          <>
            <span className={styles.rowActiveLatency}>
              <span className={styles.rowActivePing} />
              <span>{node.latency}</span>
            </span>
            <span className={styles.rowActiveDetail}>查看详情 ↗</span>
          </>
        )}
        {!isActive && (
          <>
            <span className={`${styles.rowLatency} ${isPending ? styles.rowLatencyMuted : ''}`}>
              {node.latency}
            </span>
            <span className={styles.rowDetail}>查看详情 ↗</span>
          </>
        )}
      </div>
    </div>
  )
}
