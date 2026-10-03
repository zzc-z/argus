'use client'

/**
 * Timeline view — `/report/[id]` (viewKey: 'timeline')
 *
 * Vertical year-stamped timeline of architecture / process / interconnect /
 * ecosystem / regulatory milestones. Each event is a card with category chip,
 * title, summary, and inline citation marks.
 */

import * as React from 'react'

import { IconSpan } from '@/components/common/IconSpan'
import { CitationMark } from '../CitationMark'
import { cn } from '@/lib/utils'
import type { TimelineEvent } from '../../mock'

import styles from './index.module.css'

const CATEGORY_LABEL: Record<TimelineEvent['category'], string> = {
  architecture: '架构',
  process: '制程',
  interconnect: '互联',
  ecosystem: '生态',
  regulatory: '政策',
}

const CATEGORY_ICON: Record<TimelineEvent['category'], string> = {
  architecture: 'memory',
  process: 'precision_manufacturing',
  interconnect: 'hub',
  ecosystem: 'science',
  regulatory: 'gavel',
}

export interface TimelineTrackProps {
  events: ReadonlyArray<TimelineEvent>
}

export function TimelineTrack({ events }: TimelineTrackProps) {
  // Sort events chronologically (already sorted in mock but defensive).
  const sorted = React.useMemo(
    () => [...events].sort((a, b) => a.date.localeCompare(b.date)),
    [events],
  )

  return (
    <section className={styles.wrap}>
      <header className={styles.header}>
        <div className={styles.headerLeft}>
          <span className={cn(styles.badge, 'font-code')}>VIEW · TIMELINE</span>
          <h2 className={cn(styles.title, 'font-headline-lg')}>
            技术演进时间线 (Timeline)
          </h2>
        </div>
        <span className={cn(styles.meta, 'font-label-sm')}>
          {sorted.length} 个里程碑 · Hopper → Blackwell → Rubin
        </span>
      </header>

      <ol className={styles.track}>
        {sorted.map((ev, i) => (
          <li key={ev.id} className={styles.row}>
            <div className={styles.dateCol}>
              <span className={cn(styles.dateText, 'font-code')}>{ev.date}</span>
              {i < sorted.length - 1 && <span className={styles.connector} aria-hidden="true" />}
            </div>
            <div className={styles.dotCol}>
              <span className={styles.dot} aria-hidden="true" />
            </div>
            <article className={styles.card}>
              <header className={styles.cardHead}>
                <span
                  className={cn(styles.catChip, styles[`cat_${ev.category}`])}
                  title={CATEGORY_LABEL[ev.category]}
                >
                  <IconSpan name={CATEGORY_ICON[ev.category]} size={14} />
                  <span>{CATEGORY_LABEL[ev.category]}</span>
                </span>
                <h3 className={cn(styles.cardTitle, 'font-headline-sm')}>{ev.title}</h3>
              </header>
              <p className={cn(styles.summary, 'font-body-md')}>
                {ev.summary}
                {ev.citationIds.map((cid) => (
                  <CitationMark
                    key={cid}
                    surface={cid}
                    className={styles.citationMark}
                  />
                ))}
              </p>
            </article>
          </li>
        ))}
      </ol>
    </section>
  )
}