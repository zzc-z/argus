'use client'

import * as React from 'react'
import { IconSpan } from '@/components/common/IconSpan'
import { cn } from '@/lib/utils'
import { type AgentStep, agentSummary } from '../../mock'
import styles from './index.module.css'

export interface AgentLogPanelProps {
  agents: AgentStep[]
}

/**
 * Right-drawer "Multi-Agent Synthesis Pipeline" module.
 * Shows 5 nodes (Supervisor / Researcher / Analyst / Writer / Critic) with
 * durations, plus a summary header.
 */
export function AgentLogPanel({ agents }: AgentLogPanelProps) {
  const summary = agentSummary
  return (
    <div className={styles.card}>
      <header className={styles.header}>
        <div className={styles.headerLeft}>
          <IconSpan name="hub" size={20} className="text-primary" />
          <span className={cn(styles.title, 'font-headline-sm')}>多智能体流水线 (Methodology)</span>
        </div>
        <span className={cn(styles.duration, 'font-code')}>耗时 {summary.totalDurationS}s</span>
      </header>

      <div className={cn(styles.summaryBar, 'font-label-sm')}>
        <span>
          协同状态：{summary.successfulNodes} / {summary.totalNodes} 节点执行成功
        </span>
        <span className={cn(styles.verify, 'font-code')}>校验率 {summary.verifyPct}%</span>
      </div>

      <div className={styles.list}>
        {agents.map((a) => (
          <div key={a.id} className={styles.item}>
            <div className={styles.itemLeft}>
              <div className={cn(styles.avatar, 'font-code')}>{a.initial}</div>
              <div className={styles.itemText}>
                <span className={cn(styles.name, 'font-body-sm')}>{a.name}</span>
                <span className={cn(styles.detail, 'font-label-sm')}>{a.detail}</span>
              </div>
            </div>
            <span className={cn(styles.duration, 'font-code')}>{a.durationS}s</span>
          </div>
        ))}
      </div>
    </div>
  )
}
