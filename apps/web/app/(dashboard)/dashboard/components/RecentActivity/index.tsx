/**
 * RecentActivity — 1:1 with argus_dashboard/code.html activity feed.
 *
 * First row (newest) is highlighted with violet background + 1px inset
 * border. Remaining rows render as bare list rows inside a divide-y
 * container; their only interactive state is hover (low-contrast surface).
 */

import * as React from 'react'
import { IconSpan } from '@/components/common/IconSpan'
import { cn } from '@/lib/utils'
import type { ActivityItem } from '../../view'
import styles from './index.module.css'

export interface RecentActivityProps {
  items: ActivityItem[]
}

export function RecentActivity({ items }: RecentActivityProps) {
  return (
    <section className={styles.root}>
      <header className={styles.head}>
        <div className={styles.headTitle}>
          <IconSpan name="pulse_alert" size={20} className={styles.headIcon} />
          <h2 className={`${styles.title} font-headline-sm font-semibold`}>最近活动动态</h2>
          <span className={`${styles.streamChip} font-code`}>实时流</span>
        </div>
        <a href="#" className={`${styles.viewAll} font-body-sm`}>
          <span>查看全部日志</span>
          <IconSpan name="chevron_right" size={16} />
        </a>
      </header>

      <div className={styles.listDivide}>
        {items.map((a, i) => (
          <div
            key={a.id}
            className={cn(
              styles.row,
              i === 0 || a.highlight ? styles.rowHighlight : styles.rowDefault,
            )}
          >
            <div className={styles.left}>
              <div
                className={cn(
                  styles.iconBox,
                  i === 0 || a.highlight
                    ? styles.iconBoxHighlight
                    : a.iconBox === 'accent'
                      ? styles.iconBoxAccent
                      : styles.iconBoxDefault,
                )}
              >
                <IconSpan name={a.icon} size={16} />
              </div>
              <div className={styles.body}>
                <span className={`${styles.itemTitle} font-body-sm font-medium`}>{a.title}</span>
                <span className={`${styles.itemMeta} font-code`}>{a.meta}</span>
              </div>
            </div>

            <div className={styles.right}>
              <span
                className={cn(
                  styles.badge,
                  a.badgeTone === 'highlight' && styles.badgeHighlight,
                  a.badgeTone === 'muted' && styles.badgeMuted,
                  a.badgeTone === 'plain' && styles.badgePlain,
                  a.badgeTone === 'warning' && styles.badgeWarning,
                )}
              >
                {a.badgeText}
              </span>
              <span className={`${styles.timestamp} font-code`}>{a.timestamp}</span>
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}
