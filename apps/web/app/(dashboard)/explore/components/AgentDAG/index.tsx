'use client'

import * as React from 'react'
import { IconSpan } from '@/components/common/IconSpan'
import { DAG_TITLE, type AgentNode } from '../../constants'
import styles from './index.module.css'

export interface AgentDAGProps {
  onSelectNode: (node: AgentNode) => void
  nodes: AgentNode[]
  /** 已耗时（格式化好的文案）。未收到 done 前不显示——不编数字。 */
  elapsed?: string
  /** token 用量（格式化好的文案）。未收到 done 前不显示。 */
  tokens?: string
}

/**
 * 紧凑型竖向 DAG 时间线（最多 5 节点）。背景 rail 贯穿全部高度；
 * active 高亮 rail 停在当前 active 节点。active 节点带 `cobaltPulse` 脉冲。
 * pending 节点显示空心圆。
 */
export function AgentDAG({ onSelectNode, nodes, elapsed, tokens }: AgentDAGProps) {
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

  // 已推进步数 = 生命周期离开 pending 的节点数。后端 Stage 是固定 5 个
  // 串行节点，节点表长即总步数。
  const done = nodes.filter((n) => n.lifecycle !== 'pending').length
  // 进度统计在**流式过程中**就要显示——那时最有信息量。收尾统计（耗时/token）
  // 要等 done 事件才有真值，没到就不显示，不填占位数字。
  const stats: string[] = []
  if (done > 0) stats.push(`${nodes.length} 步中的第 ${done} 步`)
  if (elapsed) stats.push(elapsed)
  if (tokens) stats.push(tokens)

  return (
    <section className={styles.section}>
      {/* Header */}
      <div className={styles.head}>
        <div className={styles.headLeft}>
          <span className={styles.headDot} />
          <h2 className={styles.headTitle}>{DAG_TITLE}</h2>
        </div>
        {stats.length > 0 && (
          <div className={styles.headStats}>
            {stats.map((s, i) => (
              <React.Fragment key={s}>
                {i > 0 && <span className={styles.headStatSep}>·</span>}
                <span className={i === 0 ? styles.headStatEmphasis : undefined}>{s}</span>
              </React.Fragment>
            ))}
          </div>
        )}
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
  const isFailed = node.lifecycle === 'failed'

  const rowClass = [
    styles.row,
    isActive ? styles.rowActive : '',
    isFailed ? styles.rowFailed : '',
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <div className={rowClass} onClick={onClick} role="button" tabIndex={0}>
      <div className={styles.rowLeft}>
        {/* Status circle */}
        {isCompleted && (
          <div className={styles.circleCompleted}>
            <IconSpan name="check" size={13} className={styles.circleIcon} />
          </div>
        )}
        {isFailed && (
          <div className={styles.circleFailed}>
            <IconSpan name="close" size={13} className={styles.circleIcon} />
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
            } ${isFailed ? styles.rowNameFailed : ''}`}
          >
            {node.name}
          </span>
          <span className={`${styles.rowRole} ${isActive ? styles.rowRoleActive : ''}`}>
            {node.detail || node.role}
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
