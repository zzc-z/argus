import * as React from 'react'
import { IconSpan } from '@/components/common/IconSpan'
import styles from './cells.module.css'

export interface IconLabelProps {
  /** Material icon name */
  icon: string
  /** icon 颜色 className（如 'text-secondary'） */
  iconClassName?: string
  /** icon 尺寸（默认 15） */
  iconSize?: 13 | 14 | 15 | 16 | 18 | 20 | 22 | 24
  /** 文字 */
  label: React.ReactNode
  /** 整体额外 className */
  className?: string
}

/**
 * IconLabel —— icon + 文字
 *  - 适用于 sources cite 列、topics 频次下拉等"单 icon + 文字"组合
 */
export function IconLabel({
  icon,
  iconClassName,
  iconSize = 15,
  label,
  className,
}: IconLabelProps) {
  return (
    <span className={`${styles.iconLabel} ${className ?? ''}`}>
      <IconSpan name={icon} size={iconSize} className={iconClassName} />
      <span>{label}</span>
    </span>
  )
}