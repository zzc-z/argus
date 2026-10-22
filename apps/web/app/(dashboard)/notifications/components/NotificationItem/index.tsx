'use client'

import * as React from 'react'
import { IconSpan } from '@/components/common/IconSpan'
import type { NotificationWithMeta } from '../../mock'
import styles from './index.module.css'

export interface NotificationItemProps {
  item: NotificationWithMeta
  onMarkRead: () => void
  onDismiss: () => void
}

/**
 * 单条通知卡片。
 *
 * 卡片本体（左侧徽标 / 标签 / 标题 / 时间 / 正文 / chips / 置信度行）保持原样；
 * 底部的操作行改为只保留**真实可执行**的两个动作：
 *
 * - 标为已读 → `NotificationsContext.markRead`（内存态）
 * - 移除 → `NotificationsContext.dismissNotification`（同时从 localStorage 移除）
 *
 * 原先按 category 展开的"查看详情 / 阅读报告 / 导出 PDF / 管理记忆项 /
 * 修复数据源 / 查看归档"都是指向不存在功能的死链接，已删除。
 */
export function NotificationItem({ item, onMarkRead, onDismiss }: NotificationItemProps) {
  const compact = isCompact(item)
  const containerClass = compact
    ? styles.compactContainer
    : item.unread
      ? `${styles.container} ${styles.unread}`
      : `${styles.container} ${styles.read}`

  return (
    <article className={containerClass}>
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
              className={`${styles.title} font-body-sm ${item.unread ? 'font-semibold' : 'font-medium'} truncate`}
            >
              {item.title}
            </span>
          </div>
          <span className={`${styles.time}`}>
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
          <BottomActions onMarkRead={onMarkRead} onDismiss={onDismiss} />
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
  onMarkRead,
  onDismiss,
}: {
  onMarkRead: () => void
  onDismiss: () => void
}) {
  return (
    <div className={styles.actions}>
      <div className={styles.actionsLeft} />
      <div className={styles.actionsRight}>
        <IconAction icon="check_circle" title="标为已读" onClick={onMarkRead} hoverTone="primary" />
        <IconAction icon="close" title="移除该事件" onClick={onDismiss} hoverTone="default" />
      </div>
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
