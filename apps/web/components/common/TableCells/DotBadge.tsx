import * as React from 'react'
import { TONE, type Tone } from './tone'
import styles from './cells.module.css'

export interface DotBadgeProps {
  /** 语义 tone */
  tone: Tone
  /** 文字 */
  label: React.ReactNode
  /** 圆点动画：'spin' 旋转 / 'ping' 心跳 / null 无动画 */
  animate?: 'spin' | 'ping' | null
  /** 整体额外 className（如 font-label-sm） */
  className?: string
}

/**
 * DotBadge —— 圆点 + 文字徽章
 *  - tone 决定背景/文字/点色；新增 tone 时改 tone.ts
 *  - animate 用于 processing（spin）/ live（ping）
 */
export function DotBadge({ tone, label, animate, className }: DotBadgeProps) {
  const t = TONE[tone]
  const dotClass = animate === 'spin' ? 'animate-spin' : animate === 'ping' ? 'animate-ping' : ''
  return (
    <span
      className={`${styles.badge} ${styles[t.badgeBg]} ${styles[t.badgeText]} ${className ?? ''}`}
    >
      <span className={`${styles.dot} ${styles[t.dot]} ${dotClass}`} />
      {label}
    </span>
  )
}