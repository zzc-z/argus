'use client'

import * as React from 'react'
import { IconSpan } from '@/components/common/IconSpan'
import { cn } from '@/lib/utils'
import { type RelatedReport } from '../../mock'
import styles from './index.module.css'

export interface RelatedReportsProps {
  reports: RelatedReport[]
  onViewAll?: () => void
}

/**
 * Right-drawer "Related Reports" module — a compact list of cross-references
 * with category / recency / match-percent / agent+citation meta.
 */
export function RelatedReports({ reports, onViewAll }: RelatedReportsProps) {
  return (
    <div className={styles.card}>
      <header className={styles.header}>
        <div className={styles.headerLeft}>
          <IconSpan name="dataset" size={20} className="text-primary" />
          <span className={cn(styles.title, 'font-headline-sm')}>关联研报 (Related)</span>
        </div>
        <a
          href="/reports"
          className={cn(styles.viewAll, 'font-label-sm')}
          onClick={(e) => {
            e.preventDefault()
            onViewAll?.()
          }}
        >
          查看全部
        </a>
      </header>

      <div className={styles.list}>
        {reports.map((r) => (
          <a key={r.id} href={`/report/${r.id}`} className={styles.item}>
            <div className={cn(styles.itemTop, 'font-label-sm')}>
              <span>
                {r.category} · {r.recency}
              </span>
              <span className={cn(styles.matchPct, 'font-code')}>{r.matchPct}% 相关</span>
            </div>
            <span className={cn(styles.itemTitle, 'font-body-md')}>{r.title}</span>
            <span className={cn(styles.itemMeta, 'font-label-sm')}>{r.meta}</span>
          </a>
        ))}
      </div>
    </div>
  )
}
