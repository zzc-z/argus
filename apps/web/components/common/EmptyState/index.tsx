'use client'

import { IconSpan } from '@/components/common/IconSpan'
import styles from './index.module.css'

/**
 * 通用空状态。
 *
 * ## 为什么不让每页各写一个
 *
 * 仓库里此前有两种空状态写法：`DataTable` 的是「居中一行灰字」，
 * `MemoryItemsSection` 的是「灰底圆角块里一行灰字」。两者都没回答用户的
 * 两个问题——**为什么空**、**下一步做什么**。列表页空掉时，那行
 * 「暂无数据」等于让用户自己猜。
 *
 * 这里收成一个组件：图标 + 主文案 + 说明 +（可选）行动按钮。配色全部走
 * `--token-*`，对比度在亮暗两套主题下都验过 ≥ 4.5:1（说明最差 5.89:1）。
 */
export interface EmptyStateProps {
  /** Material Symbol 名。`inbox` / `search_off` / `upload_file` 等。 */
  icon: string
  title: string
  /** 一句说明「为什么空 / 怎么填上」。没有它就只显示 title。 */
  description?: string
  /** 唯一行动点。没有下一步可做的页面就别传。 */
  action?: { label: string; onClick: () => void }
}

export function EmptyState({ icon, title, description, action }: EmptyStateProps) {
  return (
    <div className={styles.empty} role="status">
      <span className={styles.iconWrap}>
        <IconSpan name={icon} size={24} />
      </span>
      <p className={`${styles.title} font-body-md font-medium`}>{title}</p>
      {description && <p className={`${styles.description} font-body-sm`}>{description}</p>}
      {action && (
        <button
          type="button"
          className={`${styles.action} font-body-sm font-medium`}
          onClick={action.onClick}
        >
          {action.label}
        </button>
      )}
    </div>
  )
}
