import * as React from 'react'
import { LiveTerminal } from '../LiveTerminal'
import { StatusDot, type StatusDotColor } from '@/components/common/StatusDot'
import styles from './index.module.css'

type AgentCard = {
  index: string
  title: string
  desc: string
  meta: string
  state: 'idle' | 'running' | 'queued'
  highlight?: boolean
}

const AGENTS: AgentCard[] = [
  {
    index: '01.',
    title: '搜索探针',
    desc: 'ArXiv + SEC 深度检索',
    meta: '42 篇论文已解析',
    state: 'idle',
  },
  {
    index: '02.',
    title: '交叉验证',
    desc: '证据链一致性核对',
    meta: '置信度: 98.4%',
    state: 'running',
    highlight: true,
  },
  {
    index: '03.',
    title: '研报生成',
    desc: '结论与决策矩阵拟合',
    meta: '排队待汇总',
    state: 'queued',
  },
]

const METRICS = [
  { value: '10x', label: '文献提取提速', accent: false },
  { value: '0%', label: '外部数据外流', accent: true },
  { value: '40k+', label: '研究员已接入', accent: false },
] as const

/**
 * Centerpiece of the right panel: glass card with window chrome, three
 * agent-node cards, embedded live terminal, and a 3-up metric bar.
 */
export function DagCardGrid() {
  return (
    <div className={styles.shell}>
      <div className={styles.window}>
        <div className={styles.windowHeader}>
          <div className={styles.windowLeft}>
            <div className={styles.dots}>
              <span className={`${styles.dot} ${styles.dotRose}`} />
              <span className={`${styles.dot} ${styles.dotAmber}`} />
              <span className={`${styles.dot} ${styles.dotEmerald}`} />
            </div>
            <span className={`${styles.path} font-code font-medium`}>
              pipeline: deep-research-dag // active
            </span>
          </div>
          <div className={styles.windowRight}>
            <span className={`${styles.collaborators} font-code`}>5 智能体协作中</span>
            <span className={`${styles.latency} font-code`}>7ms 流式响应</span>
          </div>
        </div>

        <div className={styles.gridBody}>
          <div className={styles.cards}>
            {AGENTS.map((a) => (
              <AgentCardItem key={a.index} agent={a} />
            ))}
          </div>

          <LiveTerminal />
        </div>

        <div className={styles.metrics}>
          {METRICS.map((m, i) => (
            <div key={m.label} className={`${styles.metric} ${i === 1 ? styles.metricMiddle : ''}`}>
              <div
                className={`${styles.metricValue} font-code font-semibold ${
                  m.accent ? styles.metricValueAccent : ''
                }`}
              >
                {m.value}
              </div>
              <div className={`${styles.metricLabel} font-code`}>{m.label}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function AgentCardItem({ agent }: { agent: AgentCard }) {
  // 显式标注 StatusDotColor：三元推导出的类型本就是它的三个成员之一，
  // 但 TS 会推成 string 联合，加标注才能传给 StatusDot 的 color prop。
  const dotColor: StatusDotColor =
    agent.state === 'running' ? 'purple' : agent.state === 'idle' ? 'emerald' : 'amber'
  return (
    <div className={`${styles.card} ${agent.highlight ? styles.cardHighlight : ''}`}>
      {agent.state === 'running' && <span className={styles.runningBadge}>运行中</span>}
      <div className={styles.cardTop}>
        <span
          className={`${styles.cardIndex} font-code font-semibold ${
            agent.highlight ? styles.cardIndexActive : styles.cardIndexMuted
          }`}
        >
          {agent.index} {agent.title}
        </span>
        <StatusDot color={dotColor} ping={agent.state === 'running'} />
      </div>
      <p
        className={`${styles.cardDesc} font-medium ${agent.highlight ? styles.cardDescActive : ''}`}
      >
        {agent.desc}
      </p>
      <p className={`${styles.cardMeta} font-code ${agent.highlight ? styles.cardMetaActive : ''}`}>
        {agent.meta}
      </p>
    </div>
  )
}
