'use client'

import * as React from 'react'
import { IconSpan } from '@/components/common/IconSpan'
import { DAG_TITLE, type AgentNode } from '../../constants'
import { formatElapsed } from '../../formatElapsed'
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

  // **实时秒数**。
  //
  // active 节点显示「运行中 3.2s」这样增长的数字，而不是固定的
  // 「运行中」——用户盯着一个卡住不动的节点时，固定文案不给任何信息，
  // 跳动的数字才知道它还在动（还是真的卡死了）。
  //
  // ## 为什么 tick 放在这里而不是 page.tsx
  //
  // tick 会每秒 setState 一次。若放 page.tsx，每秒重建整个 nodes 数组
  // → 整个 explore 页重渲染 → 正文区（可能有几千字的 DOM）跟着重渲染。
  // 放这里只重渲染这个 DAG 组件。
  //
  // ## 为什么存「当前时刻」而不是「跳了几次」
  //
  // 渲染期不能调 ``Date.now()``——React Compiler 的 ``react-hooks/purity``
  // 规则会报错（渲染必须是纯函数， impure 调用会让结果不可复现）。
  // 所以计时器在 **effect 里**取时刻、存进 state，渲染期只读 state。
  //
  // ## 为什么用 setTimeout 链而不是 setInterval
  //
  // 两个原因：
  //
  // 1. **第一次立刻触发**。setInterval 的第一次触发在 1 秒后，而页面
  //    可能开着很久了（`now` 是挂载时的值），那 1 秒里显示的秒数会
  //    明显偏大。setTimeout 链第一次立刻触发，之后每秒一次。
  // 2. **``react-hooks/set-state-in-effect`` 规则**：在 effect 函数体里
  //    同步 setState 会被判为级联渲染。setTimeout 的回调不是函数体，
  //    规则不管它。
  //
  // ## 为什么每秒才 tick 一次
  //
  // 100ms 一次看着更「实时」，但每秒重渲染 10 次对眼睛没有区别，对
  // 电池有区别。主流项目（Vercel、Cursor 的步骤条）也是秒级。
  const [now, setNow] = React.useState(() => Date.now())
  React.useEffect(() => {
    if (activeIndex < 0) return
    let id = 0
    const tick = () => {
      setNow(Date.now())
      id = window.setTimeout(tick, 1000)
    }
    tick()
    return () => window.clearTimeout(id)
  }, [activeIndex])
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
          <NodeRow key={node.id} node={node} now={now} onClick={() => onSelectNode(node)} />
        ))}
      </div>
    </section>
  )
}

interface NodeRowProps {
  node: AgentNode
  onClick: () => void
  /**
   * 计时器取的当前时刻。
   *
   * **不能自己在渲染期调 `Date.now()`** —— React Compiler 的
   * `react-hooks/purity` 规则会报错：渲染必须是纯函数，渲染期的
   * impure 调用会让输出不可复现（同一份 props 渲染两次得到不同结果）。
   *
   * 所以时刻由父组件的 effect 取得、存进 state、传下来。
   */
  now: number
}

function NodeRow({ node, onClick, now }: NodeRowProps) {
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

  // **运行中的实时秒数** = 本段开始前的累计 + 本段已经跑的时间。
  //
  // 两个值缺一不可：只有基线（累计）不知道这一段跑了多久；只有本段
  // 时长不知道之前累计了多少（researcher 分多段跑时会看到秒数归零）。
  const liveElapsed =
    isActive && node.segmentStartedAt != null
      ? formatElapsed(node.elapsedBaseMs + (now - node.segmentStartedAt))
      : null

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
            {/* 完成的节点显示产出摘要（「核对 12 条引用，10 条有据支撑」），
                进行中显示 detail（「正在校验引用」），pending 显示静态 role。 */}
            {node.note || node.detail || node.role}
          </span>
        </div>
      </div>

      <div className={styles.rowRight}>
        {isActive && (
          <>
            <span className={styles.rowActiveLatency}>
              <span className={styles.rowActivePing} />
              <span>{liveElapsed ?? node.latency}</span>
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
