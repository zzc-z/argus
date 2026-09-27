/**
 * PageHeader — 1:1 with argus_dashboard/code.html top control row.
 */

import { IconSpan } from '@/components/common/IconSpan'
import styles from './index.module.css'

export interface PageHeaderProps {
  title: string
  titleChip: string
  greeting: string
  date: string
  notifications: number
  activeSubscriptions: number
}

export function PageHeader({ title, titleChip, greeting, date, notifications }: PageHeaderProps) {
  return (
    <div className={styles.root}>
      <div className={styles.left}>
        <div className={styles.titleRow}>
          <span className={styles.title}>{title}</span>
          <span className={styles.titleChip}>{titleChip}</span>
        </div>
        <div className={styles.meta}>
          <span className={styles.greeting}>{greeting}</span>
          <span className={styles.sep}>/</span>
          <span>{date}</span>
          <span className={styles.sep}>/</span>
          <span className={styles.statusBlock}>
            <span className={styles.statusDot} aria-hidden="true" />
            推理拓扑已就绪
          </span>
        </div>
      </div>

      <div className={styles.right}>
        <button type="button" aria-label="通知中心" className={styles.notifyBtn}>
          <IconSpan name="notifications" size={20} />
          {notifications > 0 && <span className={styles.notifyCount}>{notifications}</span>}
        </button>

        <button type="button" className={styles.tuneBtn}>
          <IconSpan name="tune" size={18} />
          <span className={styles.tuneLabel}>偏好配置</span>
        </button>

        <button type="button" className={styles.primaryBtn}>
          <IconSpan name="add" size={18} />
          <span className={styles.primaryLabel}>发起新研究</span>
          <kbd className={styles.kbd}>⌘N</kbd>
        </button>
      </div>
    </div>
  )
}
