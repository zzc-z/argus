'use client'

import * as React from 'react'
import { NotificationItem } from '../NotificationItem'
import type { NotificationSection as Section } from '../../mock'
import styles from './index.module.css'

export interface NotificationSectionProps {
  section: Section
  /** 标为已读 → `NotificationsContext.markRead` */
  onMarkRead: (id: string) => void
  /** 移除 → `NotificationsContext.dismissNotification` */
  onDismiss: (id: string) => void
}

/**
 * 一组通知的标题栏 + 条目容器。
 *
 * 原版还有"勾选 + 筛选 + 更早之前可折叠"这些能力，全部服务于那份 mock 分组数据
 * （今天 / 昨天 / 更早，共 42 条）。真实数据只有一列推送事件，没有分组也没有分页，
 * 所以那些区块随 mock 一起删除。
 */
export function NotificationSection({ section, onMarkRead, onDismiss }: NotificationSectionProps) {
  if (section.items.length === 0) return null

  return (
    <section className={styles.section}>
      <div className={styles.header}>
        <div className={styles.titleWrap}>
          {section.live && <span className={styles.liveDot} />}
          <h2 className={`${styles.title} font-headline-sm font-semibold`}>{section.title}</h2>
          <span className={`${styles.count} font-code`}>{section.count}</span>
        </div>
        {section.tail && <span className={`${styles.tail} font-code`}>{section.tail}</span>}
      </div>

      <div className={styles.items}>
        {section.items.map((item) => (
          <NotificationItem
            key={item.id}
            item={item}
            onMarkRead={() => onMarkRead(item.id)}
            onDismiss={() => onDismiss(item.id)}
          />
        ))}
      </div>
    </section>
  )
}
