'use client'

/**
 * Decision view — `/report/[id]` (viewKey: 'decision')
 *
 * Action checklist with priority chip, owner, confidence bar, impact + rollback
 * meta. Below the list sits a TcoCards strip to anchor the "cost basis" of
 * each decision against the TCO narrative.
 */

import * as React from 'react'

import { IconSpan } from '@/components/common/IconSpan'
import { TcoCards } from '../TcoCards'
import { cn } from '@/lib/utils'
import type { DecisionItem, DecisionPriority, DecisionStatus, TcoCard } from '../../mock'

import styles from './index.module.css'

const PRIORITY_LABEL: Record<DecisionPriority, string> = {
  critical: 'P0 关键',
  high: 'P1 高优',
  medium: 'P2 中等',
  low: 'P3 观察',
}

const PRIORITY_TONE: Record<DecisionPriority, string | undefined> = {
  critical: styles.priorityCritical,
  high: styles.priorityHigh,
  medium: styles.priorityMedium,
  low: styles.priorityLow,
}

const STATUS_LABEL: Record<DecisionStatus, string> = {
  pending: '待启动',
  in_progress: '进行中',
  shipped: '已落地',
  blocked: '阻塞中',
}

const STATUS_ICON: Record<DecisionStatus, string> = {
  pending: 'schedule',
  in_progress: 'autorenew',
  shipped: 'check_circle',
  blocked: 'block',
}

export interface DecisionListProps {
  items: ReadonlyArray<DecisionItem>
  tcoCards: ReadonlyArray<TcoCard>
}

export function DecisionList({ items, tcoCards }: DecisionListProps) {
  return (
    <section className={styles.wrap}>
      <header className={styles.header}>
        <div className={styles.headerLeft}>
          <span className={cn(styles.badge, 'font-code')}>VIEW · DECISION</span>
          <h2 className={cn(styles.title, 'font-headline-lg')}>
            决策行动清单 (Decision List)
          </h2>
        </div>
        <span className={cn(styles.meta, 'font-label-sm')}>
          {items.length} 项动作 · 按优先级排序
        </span>
      </header>

      <ol className={styles.list}>
        {items.map((it) => (
          <li key={it.id} className={styles.item}>
            <div className={styles.itemLeft}>
              <span className={cn(styles.priority, PRIORITY_TONE[it.priority] ?? '', 'font-code')}>
                {PRIORITY_LABEL[it.priority]}
              </span>
            </div>
            <div className={styles.itemBody}>
              <div className={styles.itemHead}>
                <h3 className={cn(styles.itemAction, 'font-headline-sm')}>{it.action}</h3>
                <span className={cn(styles.statusChip, styles[`status_${it.status}`])}>
                  <IconSpan name={STATUS_ICON[it.status]} size={14} />
                  <span>{STATUS_LABEL[it.status]}</span>
                </span>
              </div>
              <div className={styles.metaRow}>
                <span className={cn(styles.ownerChip, 'font-label-sm')}>
                  <IconSpan name="person" size={14} />
                  <span>{it.owner}</span>
                </span>
                <span className={cn(styles.confidence, 'font-label-sm')}>
                  置信度
                  <strong>{it.confidencePct}%</strong>
                  <span
                    className={styles.confBar}
                    aria-hidden="true"
                  >
                    <span
                      className={styles.confBarFill}
                      style={{ width: `${it.confidencePct}%` }}
                    />
                  </span>
                </span>
              </div>
              <p className={cn(styles.impact, 'font-body-sm')}>
                <span className={styles.impactLabel}>影响</span>
                <span>{it.impact}</span>
              </p>
              <p className={cn(styles.rollback, 'font-body-sm')}>
                <span className={styles.rollbackLabel}>回滚成本</span>
                <span>{it.rollbackCost}</span>
              </p>
            </div>
          </li>
        ))}
      </ol>

      {/* Cost basis — anchors the decisions against the TCO narrative. */}
      <div className={styles.tcoAnchor}>
        <h3 className={cn(styles.tcoTitle, 'font-headline-md')}>成本依据 (TCO Basis)</h3>
        <TcoCards cards={[...tcoCards]} />
      </div>
    </section>
  )
}