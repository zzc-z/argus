'use client'

import * as React from 'react'
import { IconSpan } from '@/components/common/IconSpan'
import type { NotificationWithMeta, NotificationCategory } from '../../mock'
import styles from './index.module.css'

export interface NotificationItemProps {
  item: NotificationWithMeta
  selected: boolean
  onToggle: () => void
  onMarkRead: () => void
}

/**
 * Single notification card — 4 visual variants (unread / read / warning / compact)
 * and per-category bottom action rows. 1:1 extracted from
 * argus_notifications/code.html lines 121-365.
 */
export function NotificationItem({ item, selected, onToggle, onMarkRead }: NotificationItemProps) {
  const compact = isCompact(item)
  const containerClass = compact
    ? styles.compactContainer
    : item.unread
      ? `${styles.container} ${styles.unread}`
      : `${styles.container} ${styles.read}`

  return (
    <article className={containerClass}>
      <div className={styles.checkboxWrap}>
        <input type="checkbox" className={styles.checkbox} checked={selected} onChange={onToggle} />
      </div>

      {!compact && (
        <NotificationBadge icon={item.icon} severity={item.severity} unread={item.unread} />
      )}

      <div className={styles.body}>
        <div className={styles.headRow}>
          <div className={styles.titleWrap}>
            <span className={`${styles.tag} ${item.unread ? styles.tagUnread : ''}`}>
              {item.tag}
            </span>
            <span
              className={`${styles.title} font-headline-sm ${item.unread ? 'font-semibold' : 'font-medium'} truncate`}
            >
              {item.title}
            </span>
          </div>
          <span className={`${styles.time} font-code font-label-sm`}>
            {item.time}
            {item.timeDetail && <span className={styles.timeDetail}> · {item.timeDetail}</span>}
          </span>
        </div>

        {!compact && item.body && <p className={`${styles.bodyText} font-body-sm`}>{item.body}</p>}

        {!compact && item.chips && (
          <ChipsRow
            topic={item.chips.topic}
            source={item.chips.source}
            sentiment={item.chips.sentiment}
            sparkline={item.sparkline}
          />
        )}

        {!compact && item.confidence && (
          <ConfidenceRow
            score={item.confidence.score}
            summary={item.confidence.summary}
            badge={item.badge}
          />
        )}

        {!compact && (
          <BottomActions
            category={item.category}
            errorCode={item.errorCode}
            memoryWeight={item.memoryWeight}
            tailTag={item.tailTag}
            onMarkRead={onMarkRead}
          />
        )}
      </div>
    </article>
  )
}

function isCompact(item: NotificationWithMeta): boolean {
  return (
    !item.body &&
    !item.chips &&
    !item.confidence &&
    !item.errorCode &&
    !item.memoryWeight &&
    !item.tailTag
  )
}

function NotificationBadge({
  icon,
  severity,
  unread,
}: {
  icon: string
  severity: NotificationWithMeta['severity']
  unread: boolean
}) {
  let badgeClass = styles.badgeDefault
  let iconClass = styles.badgeIconDefault
  let dot: React.ReactNode = null

  if (severity === 'warning') {
    badgeClass = styles.badgeWarn
    iconClass = styles.badgeIconWarn
  } else if (unread) {
    badgeClass = styles.badgeUnread
    iconClass = styles.badgeIconUnread
    if (severity === 'info') {
      dot = <span className={`${styles.badgeDot} ${styles.badgeDotInfo}`} />
    } else if (severity === 'success') {
      dot = <span className={`${styles.badgeDot} ${styles.badgeDotSuccess}`} />
    } else if (severity === 'memory') {
      dot = <span className={`${styles.badgeDot} ${styles.badgeDotMemory}`} />
    }
  }

  return (
    <div className={`${styles.badge} ${badgeClass}`}>
      <IconSpan name={icon} size={20} className={iconClass} />
      {dot}
    </div>
  )
}

function ChipsRow({
  topic,
  source,
  sentiment,
  sparkline,
}: {
  topic: string
  source: string
  sentiment: string
  sparkline?: string
}) {
  return (
    <div className={styles.chipsRow}>
      <div className={styles.chipsLeft}>
        <span className={`${styles.chip} ${styles.chipTopic}`}>{topic}</span>
        <span className={styles.chipSep}>/</span>
        <span className={`${styles.chipSource} font-code`}>{source}</span>
        <span className={styles.chipSep}>/</span>
        <span className={`${styles.chipSentiment} font-code font-medium`}>{sentiment}</span>
      </div>
      {sparkline && (
        <div className={styles.sparkWrap}>
          <span className={`${styles.sparkLabel} font-code`}>波动:</span>
          <svg className={styles.spark} viewBox="0 0 64 16" fill="none" aria-hidden="true">
            <path
              d={sparkline}
              stroke="currentColor"
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth="1.5"
            />
          </svg>
        </div>
      )}
    </div>
  )
}

function ConfidenceRow({
  score,
  summary,
  badge,
}: {
  score: string
  summary: string
  badge?: string
}) {
  return (
    <div className={styles.confRow}>
      <div className={styles.confLeft}>
        <span className={styles.confDot} />
        <span className={`${styles.confScore} font-code font-medium`}>{score}</span>
      </div>
      <span className={styles.confSep} />
      <div className={styles.confMid}>
        <IconSpan name="groups" size={13} className={styles.confIcon} />
        <span className={`${styles.confSummary} font-code`}>{summary}</span>
      </div>
      {badge && (
        <>
          <span className={`${styles.confSepHidden} hidden sm:block`} />
          <span className={`${styles.confBadge} font-code hidden sm:inline`}>{badge}</span>
        </>
      )}
    </div>
  )
}

function BottomActions({
  category,
  errorCode,
  memoryWeight,
  tailTag,
  onMarkRead,
}: {
  category: NotificationCategory
  errorCode?: string
  memoryWeight?: string
  tailTag?: string
  onMarkRead: () => void
}) {
  let left: React.ReactNode = null
  let right: React.ReactNode = (
    <IconAction icon="check_circle" title="标为已读" onClick={onMarkRead} hoverTone="primary" />
  )

  if (category === 'subscriptions') {
    left = (
      <>
        <button type="button" className={`${styles.actionPrimary} font-headline-sm`}>
          <span>查看详情</span>
          <IconSpan name="arrow_forward" size={14} />
        </button>
        <button type="button" className={`${styles.actionGhost} font-body-sm`}>
          定位至知识拓扑
        </button>
      </>
    )
  } else if (category === 'reports') {
    left = (
      <>
        <button type="button" className={`${styles.actionPillPrimary} font-headline-sm`}>
          <IconSpan name="auto_stories" size={14} />
          <span>阅读报告</span>
        </button>
        <button type="button" className={`${styles.actionGhost} font-body-sm`}>
          <IconSpan name="download" size={14} />
          <span>导出 PDF/Markdown</span>
        </button>
      </>
    )
    right = (
      <>
        {right}
        <IconAction icon="share" title="分享报告" hoverTone="default" onClick={onMarkRead} />
      </>
    )
  } else if (category === 'memory') {
    left = (
      <>
        <a className={`${styles.linkPrimary} font-headline-sm`} href="#">
          <span>管理记忆项</span>
          <IconSpan name="arrow_outward" size={13} />
        </a>
        <span className={`${styles.dotSep} font-code`}>·</span>
        <span className={`${styles.memoryWeight} font-label-sm`}>{memoryWeight}</span>
      </>
    )
  } else if (category === 'weekly') {
    left = (
      <>
        <a className={`${styles.linkPlain} font-body-sm`} href="#">
          <span>查看归档</span>
          <IconSpan name="arrow_forward" size={13} />
        </a>
        <span className={`${styles.tailTag} font-code`}>{tailTag}</span>
      </>
    )
  } else if (category === 'system') {
    left = (
      <>
        <button type="button" className={`${styles.actionWarn} font-body-sm`}>
          <IconSpan name="settings_backup_restore" size={13} className={styles.actionWarnIcon} />
          <span>修复数据源</span>
        </button>
        <span className={`${styles.errorCode} font-code`}>{errorCode}</span>
      </>
    )
  }

  return (
    <div className={styles.actions}>
      <div className={styles.actionsLeft}>{left}</div>
      <div className={styles.actionsRight}>{right}</div>
    </div>
  )
}

function IconAction({
  icon,
  title,
  onClick,
  hoverTone,
}: {
  icon: string
  title: string
  onClick: () => void
  hoverTone: 'primary' | 'default'
}) {
  const iconHoverClass =
    hoverTone === 'primary' ? styles.iconBtnIconPrimary : styles.iconBtnIconDefault
  return (
    <button type="button" className={styles.iconBtn} title={title} onClick={onClick}>
      <IconSpan name={icon} size={16} className={iconHoverClass} />
    </button>
  )
}
