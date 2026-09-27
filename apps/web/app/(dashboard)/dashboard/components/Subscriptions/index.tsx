/**
 * Subscriptions — 1:1 with argus_dashboard/code.html right-side panel.
 *
 * Each row: title + unread badge (one line) · updated + source (one line) ·
 * real checkbox-style toggle on the right. Paused row uses reduced opacity
 * + grey-out + unchecked toggle. Bottom: full-width "+ 订阅新研究课题" CTA.
 */

import * as React from 'react'
import { IconSpan } from '@/components/common/IconSpan'
import { cn } from '@/lib/utils'
import type { Subscription } from '../../mock'
import styles from './index.module.css'

export interface SubscriptionsProps {
  items: Subscription[]
}

export function Subscriptions({ items }: SubscriptionsProps) {
  const activeCount = items.filter((s) => !s.paused).length

  return (
    <section className={styles.root}>
      <header className={styles.head}>
        <div className={styles.headTitle}>
          <IconSpan name="rss_feed" size={20} className={styles.headIcon} />
          <h2 className={`${styles.title} font-headline-sm font-semibold`}>我的主题订阅</h2>
          <span className={`${styles.activeChip} font-code`}>{activeCount} 个运行中</span>
        </div>
        <a href="#" className={`${styles.manageLink} font-body-sm`}>
          <span>管理订阅</span>
          <IconSpan name="settings" size={16} />
        </a>
      </header>

      <div className={styles.list}>
        {items.map((s) => (
          <div
            key={s.id}
            className={cn(styles.subRow, s.paused ? styles.subRowPaused : styles.subRowActive)}
          >
            <div className={styles.subLeft}>
              <div className={styles.subTitleRow}>
                <span className={`${styles.subTitle} font-body-sm font-semibold`}>{s.title}</span>
                <span
                  className={cn(
                    styles.badge,
                    s.badgeTone === 'unread' && styles.badgeUnread,
                    s.badgeTone === 'none' && styles.badgeNone,
                    s.badgeTone === 'paused' && styles.badgePaused,
                  )}
                >
                  {s.badgeText}
                </span>
              </div>
              <div className={`${styles.subMeta} font-code`}>
                <span>{s.updatedAt}</span>
                <span aria-hidden="true">·</span>
                <span>{s.source}</span>
              </div>
            </div>

            <label className={styles.toggle}>
              <input
                type="checkbox"
                className="peer sr-only"
                defaultChecked={!s.paused}
                aria-label={s.paused ? '恢复订阅' : '暂停订阅'}
              />
              <span className={styles.toggleTrack}>
                <span className={styles.toggleThumb} />
              </span>
            </label>
          </div>
        ))}
      </div>

      <button type="button" className={`${styles.cta} font-body-sm font-medium`}>
        <IconSpan name="add_circle" size={18} className={styles.ctaIcon} />
        <span>+ 订阅新研究课题</span>
      </button>
    </section>
  )
}
