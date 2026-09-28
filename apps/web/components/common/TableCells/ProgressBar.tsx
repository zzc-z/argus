import * as React from 'react'
import styles from './cells.module.css'

export interface ProgressBarProps {
  /** 进度条上方文字（如 "Embedding 78%"） */
  label: React.ReactNode
  /** 进度 0-100 */
  percent: number
  /** label 额外 className */
  labelClassName?: string
}

/**
 * ProgressBar —— 横向 4px 进度条 + 上方 label
 *  - 默认紫色填充（var(--token-primary)）；如需换色后续可加 tone prop
 */
export function ProgressBar({ label, percent, labelClassName }: ProgressBarProps) {
  const clamped = Math.max(0, Math.min(100, percent))
  return (
    <div className={styles.progressWrap}>
      <div className={styles.progressHead}>
        <span className={`${styles.progressLabel} ${labelClassName ?? ''}`}>{label}</span>
      </div>
      <div className={styles.progressBar}>
        <div className={styles.progressFill} style={{ width: `${clamped}%` }} />
      </div>
    </div>
  )
}