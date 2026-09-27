import * as React from 'react'
import { IconSpan } from '@/components/common/IconSpan'
import styles from './index.module.css'

export interface TemplateCardProps {
  icon: string
  title: string
  description: string
  sourceCount: number
  onApply?: () => void
}

/**
 * One preset template card under the main table — biomed / semiconductor
 * supply chain variants. Static card; the "一键载入" CTA is wired to `onApply`
 * (default = no-op), since templates currently have no destination route.
 */
export function TemplateCard({
  icon,
  title,
  description,
  sourceCount,
  onApply,
}: TemplateCardProps) {
  return (
    <article className={styles.card}>
      <div className={styles.head}>
        <div className={styles.titleRow}>
          <span className={styles.iconWrap}>
            <IconSpan name={icon} size={16} className="text-primary" />
          </span>
          <span className={`${styles.title} font-headline-sm font-semibold`}>{title}</span>
        </div>
        <span className={`${styles.chip} font-code`}>TEMPLATE</span>
      </div>
      <p className={`${styles.description} font-body-sm text-secondary`}>{description}</p>
      <div className={styles.foot}>
        <span className={`${styles.footMeta} font-label-sm text-secondary`}>
          包含 {sourceCount} 个信源预设
        </span>
        <button type="button" className={`${styles.apply} font-label-sm`} onClick={onApply}>
          <span>一键载入</span>
          <IconSpan name="arrow_forward" size={14} />
        </button>
      </div>
    </article>
  )
}
