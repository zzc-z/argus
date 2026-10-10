'use client'

import * as React from 'react'
import Link from 'next/link'
import { IconSpan } from '@/components/common/IconSpan'
import type { Route } from 'next'
import type { Report } from '../../mock'
import styles from './index.module.css'

export interface ReportGridProps {
  reports: ReadonlyArray<Report>
}

/**
 * Card-grid view for the same report data.
 * Pure presentation; receives filtered list from page.tsx.
 */
export function ReportGrid({ reports }: ReportGridProps) {
  return (
    <div className={styles.root}>
      {reports.map((r) => {
        const isRunning = r.status === 'running'
        return (
          <Link key={r.id} href={`/report/${r.id}` as Route} className={styles.cardLink}>
            <article className={styles.card}>
            <div className={styles.cardHead}>
              <div className={styles.cardTopRow}>
                <span className={`${styles.topicBadge} ${styles[`topic-${r.topic.tone}`] ?? ''}`}>
                  {r.topic.label}
                </span>
                {isRunning ? (
                  <span className={styles.runningDot} aria-hidden="true" />
                ) : (
                  <IconSpan
                    name="star"
                    size={18}
                    className={`${styles.star} ${r.starred ? styles.starred : ''}`}
                  />
                )}
              </div>
              <h3 className={`${styles.cardTitle} ${isRunning ? styles.cardTitleRunning : ''}`}>
                {r.title}
              </h3>
              <p className={styles.cardSummary}>{r.summary}</p>
            </div>
            <div className={`${styles.cardFoot} ${isRunning ? styles.cardFootRunning : ''}`}>
              <span className={styles.cardMeta}>
                {r.sourcesCount} 权威源 · {r.viewsCount} 阅
              </span>
              {isRunning ? (
                <span className={styles.cardRunning}>⏳ 流式生成中 {r.runningProgress ?? 0}%</span>
              ) : (
                <span className={styles.cardVerified}>✓ 已验证</span>
              )}
            </div>
          </article>
          </Link>
        )
      })}
    </div>
  )
}
